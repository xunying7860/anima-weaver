"""
Anima Weaver — Main ComfyUI Node

Provides the ``AnimaWeaver`` custom node that:
  - Accepts up to 8 tag slots
  - Optionally pulls random tags from Raffle taglist files
  - Merges manual + random tags (hybrid mode)
  - Runs conflict detection
  - Assembles a final prompt via ``assembly.assemble_prompt``
  - Optionally generates natural-language descriptions via LM Studio
"""

from __future__ import annotations

import json
import os
import random
import hashlib
import threading
from typing import Any, Optional

try:
    from .rules import check_conflicts, resolve_conflicts
    # P2 清理：assemble_prompt/SLOT_LIMITS 从未被引用（死 import，方案 §5）
    from .assembly import mix_by_ratio, SLOT_ORDER
    # P1/P5/P6: 行偏移索引、三级抽取、画师单例、laya 质量门
    from .tag_index import get_tag_index, get_category_map, get_slot_map
    from .tag_extract import pick_line, build_sync
    from .artist_index import all as _artist_index_all
    from . import laya_gate
except ImportError:
    from rules import check_conflicts, resolve_conflicts
    from assembly import mix_by_ratio, SLOT_ORDER
    from tag_index import get_tag_index, get_category_map, get_slot_map
    from tag_extract import pick_line, build_sync
    from artist_index import all as _artist_index_all
    import laya_gate


# ══════════════════════════════════════════════════════════════════
# P4: 随机内核 —— 命名子流 + 垃圾标签黑名单
# ══════════════════════════════════════════════════════════════════
# 旧写法「一个 rng 干所有事」：改了标签数量就会连锁改变画师，
# 「固定种子复现」实际失效。命名子流让每个抽样环节互不干扰：
# 同 (seed, name) 恒等，不同 name 完全无关。

def _substream(seed: int, name: str) -> random.Random:
    """从主种子派生一个独立的命名随机流（blake2b 做盐）。"""
    h = hashlib.blake2b(f"{seed}:{name}".encode("utf-8"), digest_size=8).digest()
    return random.Random(int.from_bytes(h, "big"))


class SeedRNG:
    """主种子 + 命名子流统一管理入口（替代旧的单一 rng）。"""

    __slots__ = ("seed", "_cache")

    def __init__(self, seed: int):
        self.seed = int(seed)
        self._cache: dict = {}

    def get(self, name: str) -> random.Random:
        r = self._cache.get(name)
        if r is None:
            r = _substream(self.seed, name)
            self._cache[name] = r
        return r


def sample_slot(srng: "SeedRNG", tags, slot: str, k: int = 8,
                keep_order: bool = True, protect: set = None) -> list:
    """
    P4: rng.sample 替代 raffle_tags[:8] 位置截断。

    Danbooru 行内标签是完全按字母序排列的（实测 400/400），[:8] 永远
    保留字母序最靠前的 8 个 —— 系统性字母序偏差（b 开头 +48%，
    t/s/w 开头 -31%~-69%）。随机抽样消除偏差；keep_order=True 时
    采样后按原始位置排序（只影响「留哪些」，不影响输出顺序）。
    """
    if len(tags) <= k:
        return list(tags)
    # 必含/受保护标签无条件保留（否则抽样 cap 会静默违反「标签列表必含」），
    # 剩余配额再从其余标签随机抽
    prot = [t for t in tags if protect and t in protect]
    rest = [t for t in tags if not (protect and t in protect)]
    kk = max(0, k - len(prot))
    chosen = prot + srng.get(f"slot:{slot}").sample(rest, min(kk, len(rest)))
    if keep_order:
        idx = {t: i for i, t in enumerate(tags)}
        chosen.sort(key=lambda t: idx.get(t, 1 << 30))
    return list(chosen)


# ── P4: Danbooru 元数据垃圾标签黑名单 ──────────────────────────────
# 这些是元数据不是画面内容（实测占抽中 tag 的 5.3%）。
# 把 commentary/absurdres/bad_id 塞进提示词 = 告诉 SD「请生成一张
# 有评论的、分辨率爆表的、ID 损坏的图」—— 要么无响应要么副作用。
META_TAGS = frozenset({
    # 评论 / 文字
    "commentary", "commentary_request", "english_commentary",
    "translated", "translation_request", "character_request",
    "tagme", "text", "english_text", "japanese_text", "chinese_text",
    "korean_text", "watermark", "signature", "artist_name",
    "artist_logo", "copyright_name", "censored", "uncensored",
    "bar_censor", "mosaic_censoring", "scanned", "scan",
    # 投稿 / 数据质量
    "bad_id", "bad_link", "bad_pixiv_id", "bad_anatomy", "bad_hands",
    "bad_feet", "bad_quality", "lowres", "low_quality", "worst_quality",
    "jpeg_artifacts", "compression_artifacts", "artifacts",
    "out_of_frame", "cropped", "off_topic", "duplicate",
    # 尺寸 / 分辨率（画面内容无关）
    "absurdres", "highres", "superres", "incredibly_absurdres",
    "monochrome_greyscale_only_if_not_forced",
    # 其它非视觉
    "sketch", "thumbnail", "commission", "patreon", "fanbox",
    "twitter_username", "pixiv_username", "unknown_artist",
})

# 质量标记：可选过滤（有人刻意在提示词里放 masterpiece），默认关
QUALITY_TAGS = frozenset({
    "masterpiece", "best_quality", "high_quality", "normal_quality",
    "low_quality", "worst_quality", "amazing_quality", "great_quality",
    "very_high_quality", "hd", "8k", "4k",
})

# ── Artist index (lazy loaded) ────────────────────────────────────────

import os as _os

_ARTIST_LIST: list[str] | None = None
_ARTIST_FILE = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "tags", "Anima2B_Artist_Index_59k.txt",
)

def _load_artists() -> list[str]:
    """
    P1: 统一走 artist_index 单例（进程内只加载一次，O(1) 序号查名）。
    保留本函数与 _ARTIST_LIST 缓存，兼容旧调用点。
    """
    global _ARTIST_LIST
    if _ARTIST_LIST is not None:
        return _ARTIST_LIST
    _ARTIST_LIST = _artist_index_all()
    print(f"Anima Weaver: loaded {len(_ARTIST_LIST)} artists")
    return _ARTIST_LIST


# ── ComfyUI Node ────────────────────────────────────────────────────

class AnimaWeaver:
    """
    Anima Prompt Weaver — ComfyUI custom node.

    Combines manual tags, Raffle random tags, and optional LM Studio
    natural-language description into a single weighted prompt.
    """

    # 类级别缓存
    _raffle_tag_data = None  # 缓存已加载的 taglist

    # ── Input schema ──────────────────────────────────────────────

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        """Define the ComfyUI input widget schema."""
        # Try to get available LM Studio models
        model_list: list[str] = []
        try:
            from .lm_studio import get_models
            models = get_models()
            if models:
                model_list = models
        except Exception:
            pass
        if not model_list:
            model_list = ["(no models found)"]
        # P3 修正：占位符常列在列表尾部 —— 旧工作流里保存的占位值（检测中/
        # 无模型）在真列表到达后不会再被 COMBO 校验拒绝（Value not in list）；
        # 运行侧所有「无模型」判断都把占位符当 manual 兜底处理。
        for _s in ("(no models found)", "(检测中…)"):
            if _s not in model_list:
                model_list.append(_s)

        # ── P2: 分组 INPUT_TYPES（配合 js/anima_groups.js 折叠）────────
        # 硬约束1: 组开关（▸ xxx）必须排在它管理的 widget 前面（dict 顺序=前端顺序）
        # 硬约束2: 槽位/过滤 widget 默认值一律 "" —— compose() 只在 widget 为空时
        #          才用「槽位数据/底部数据」JSON 注入值，旧工作流因此零破坏
        # 硬约束3: 敏感/露骨默认 True 是真实开关的兜底行为，不能改
        return {
            # ══ 一级：常驻，永远可见 ══════════════════════════════════
            "required": {
                "模式": (["manual", "random", "hybrid"], {"default": "hybrid"}),
                "标签比例": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0,
                                    "step": 0.05}),
                "场景类型": (
                    ["solo_display", "couple_foreplay", "couple_sex",
                     "group", "yuri", "special_theme"],
                ),
            },

            # ══ 二级：分组，默认收起（勾选组开关展开）══════════════════
            "optional": {
                # ── 随机种子：用得频繁，放一级区底部，只是不渲染成 widget ──
                "随机种子": ("INT", {"forceInput": True, "default": 0,
                                 "min": 0, "max": 0xFFFF_FFFF_FFFF_FFFF,
                                 "tooltip": "从外部种子节点接入，不接则使用内部随机值"}),

                # ━━ 组1 标签槽位（吸收「提示词槽位」节点）━━━━━━━━━━━━━━
                "▸ 标签槽位": ("BOOLEAN", {"default": False,
                                      "tooltip": "组开关：勾选展开下方槽位控件"}),
                "人数/身份": ("STRING", {"multiline": True, "default": ""}),
                "外貌": ("STRING", {"multiline": True, "default": ""}),
                "服装": ("STRING", {"multiline": True, "default": ""}),
                "姿势/动作": ("STRING", {"multiline": True, "default": ""}),
                "表情": ("STRING", {"multiline": True, "default": ""}),
                "镜头": ("STRING", {"multiline": True, "default": ""}),
                "场景/环境": ("STRING", {"multiline": True, "default": ""}),
                "细节/氛围": ("STRING", {"multiline": True, "default": ""}),
                "自然语言描述": ("STRING", {"multiline": True, "default": ""}),

                # ━━ 组2 过滤控制（吸收「底部控制」节点）━━━━━━━━━━━━━━━━
                "▸ 过滤控制": ("BOOLEAN", {"default": False}),
                "标签列表必含": ("STRING", {"multiline": True, "default": ""}),
                "过滤标签": ("STRING", {"multiline": True, "default": ""}),
                "排除含标签列表": ("STRING", {"multiline": True, "default": ""}),
                "排除标签分类": ("STRING", {"multiline": True, "default": ""}),
                # 这四个是真实开关，默认值必须复刻原「底部控制」节点兜底
                "通用标签": ("BOOLEAN", {"default": False}),
                "争议标签": ("BOOLEAN", {"default": False}),
                "敏感标签": ("BOOLEAN", {"default": True}),
                "露骨标签": ("BOOLEAN", {"default": True}),

                # ━━ 组3 LLM 设置 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                "▸ LLM设置": ("BOOLEAN", {"default": False}),
                "自然语言来源": (["manual", "lm_studio"], {"default": "manual"}),
                "强制详细自然语言": ("BOOLEAN", {"default": False,
                                          "tooltip": "开启后 NL 描述至少 10 句，非常详细（使用 512 tokens）"}),
                "模型": (model_list,),
                "API地址": ("STRING", {"default": "http://localhost:1234/v1",
                                    "multiline": False,
                                    "tooltip": "LM Studio API 地址（或兼容 OpenAI 的 API 地址）"}),
                "API密钥": ("STRING", {"default": ""}),
                "云端模型名": ("STRING", {"default": "",
                                      "tooltip": "云端模型名（如 deepseek-chat），填 API 密钥时此值会覆盖下拉框的模型选择"}),
                "上下文长度": ("INT", {"default": 8192, "min": 0, "max": 262144}),
                "自动上下文长度": ("BOOLEAN", {"default": False,
                                          "tooltip": "启用后自动计算上下文长度 = 最大并发数 × 2048，仅本地模型有效"}),
                "最大截断长度": ("INT", {"default": 0, "min": 0, "max": 1080, "step": 8,
                                     "tooltip": "0=自动（普通256/详细512），256~1080=手动设置最大 token 数"}),
                "生成后卸载": ("BOOLEAN", {"default": False}),

                # ━━ 组4 批量（吸收「批量种子」节点的主节点内部等价）━━━━━
                "▸ 批量": ("BOOLEAN", {"default": False}),
                "批量数量": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 1,
                                  "tooltip": ">0 且未接种子串时，内部生成 N 个随机种子进入批量模式"}),
                "请求数": ("INT", {"default": 4, "min": 1, "max": 128, "step": 1,
                                "tooltip": "建议大于或等于最大并发数"}),
                "最大并发数": ("INT", {"default": 4, "min": 1, "max": 128, "step": 1,
                                    "tooltip": "控制本地模型加载时的 Max Concurrent Predictions（--parallel 参数），仅自动上下文长度开启时生效"}),
                "种子串": ("STRING", {"forceInput": True, "multiline": True,
                                   "tooltip": "接入批量种子串（每行一个种子），开启批量模式"}),
                "画师串": ("STRING", {"forceInput": True, "multiline": True,
                                   "tooltip": "接入画师串（每行一个画师），与种子串行对齐"}),
                "反推串": ("STRING", {"forceInput": True, "multiline": True,
                                   "tooltip": "接入反推串（每行一个），与种子串行对齐"}),

                # ━━ 组5 高级 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                "▸ 高级": ("BOOLEAN", {"default": False}),
                "画师种子": ("INT", {"default": 0, "min": -1, "max": 0x7FFFFFFF,
                                  "tooltip": "-1=随机画师，0=无画师，1~=固定画师序号"}),
                "冲突检查": ("BOOLEAN", {"default": True}),
                "系统提示词": ("STRING", {"forceInput": True, "multiline": True,
                                      "tooltip": "可选。自定义系统提示词，留空使用默认提示词"}),
                # 旧工作流兼容：两个 JSON 入口保留（折叠进高级组）
                "槽位数据": ("STRING", {"forceInput": True,
                                    "tooltip": "旧工作流兼容：「提示词槽位」节点的输出"}),
                "底部数据": ("STRING", {"forceInput": True,
                                    "tooltip": "旧工作流兼容：「底部控制」节点的输出"}),

                # ━━ 组6 laya 判定（质量门，默认关）━━━━━━━━━━━━━━━━━━━━
                "▸ laya判定": ("BOOLEAN", {"default": False}),
                "启用laya门控": ("BOOLEAN", {"default": False,
                                        "tooltip": "laya 质量门（不合格自动重抽一次）；零样本准确率低，建议微调后开启；模型未安装时自动降级原样放行"}),
                "过滤质量标签": ("BOOLEAN", {"default": False,
                                        "tooltip": "剔除 masterpiece/highres 等质量标签（有人刻意保留这类标签，故默认关）"}),
            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("生成的提示词", "调试信息", "画师串", "反推串")
    FUNCTION = "compose"
    OUTPUT_NODE = True

    # ── Cache control ─────────────────────────────────────────────
    #
    # NOTE(seed-randomize): ComfyUI 新版 web UI 对 IS_CHANGED 的支持因版本而异。
    # 如果 randomize 模式下种子仍不更新，可能是前端未正确传递变更信号。
    # 临时方案：在 compose() 中通过 kwargs["随机种子"] = random.randint(...)
    # 内部随机化，但 ComfyUI 缓存机制可能绕过 compose() 直接返回缓存结果。
    # 终极解决：等待 ComfyUI 新版修复前端 seed control 行为。

    @classmethod
    def IS_CHANGED(cls, **kwargs) -> float:
        """
        P4: 输入确定性哈希（替代旧 random.random()）。

        旧版永远返回随机值 → 每次执行都强制重算，和「用 seed 复现结果」
        直接冲突。新版：同输入 → 同值 → ComfyUI 可复用缓存；
        只有输入真正变化（如种子 randomize 给出新种子值）才重算。
        """
        try:
            # P2: 组开关（▸ xxx）只是前端折叠标记，展开/收起不应触发重算，
            # 从哈希输入里剔除，保证「同参数输入 → 同 IS_CHANGED → 复用缓存」
            payload_kwargs = {k: v for k, v in kwargs.items()
                              if not str(k).startswith("▸")}
            payload = json.dumps(payload_kwargs, sort_keys=True, default=str,
                                 ensure_ascii=False)
        except (TypeError, ValueError):
            payload = repr(sorted((str(k), str(v)) for k, v in kwargs.items()))
        h = hashlib.blake2b(payload.encode("utf-8", "replace"),
                            digest_size=8).digest()
        return float(int.from_bytes(h, "big")) / float(1 << 64)

    # ── Main composition entry point ──────────────────────────────

    def compose(self, **kwargs) -> tuple[str, str, str, str, str]:
        """
        Main node workflow. Returns 5-tuple (single_prompt, debug, +3 batch outs).
        """
        mode = kwargs.get("模式", "hybrid")
        tag_ratio = float(kwargs.get("标签比例", 0.6))
        nl_source = kwargs.get("自然语言来源", "manual")
        enable_conflict = bool(kwargs.get("冲突检查", True))

        # ── Mutually exclusive: 种子串 overrides 随机种子 ──────────────
        batch_seeds_str = kwargs.get("种子串", "")
        # ── P2: 吸收「批量种子」节点 —— 批量数量>0 且未接种子串时，
        #    内部生成 N 个随机种子进入批量模式（原 BatchSeedNode 的全部有效逻辑）
        if not batch_seeds_str.strip():
            try:
                _n = int(kwargs.get("批量数量", 0) or 0)
            except (TypeError, ValueError):
                _n = 0
            if _n > 0:
                batch_seeds_str = "\n".join(
                    str(random.randint(1, 0x7FFFFFFFFFFFFFFF)) for _ in range(_n))
        is_batch = bool(batch_seeds_str.strip())
        if is_batch:
            kwargs.pop("随机种子", None)  # 批量模式下忽略随机种子

        # ── Optional: merge slot data JSON ────────────────────────────
        slot_json = kwargs.get("槽位数据", "")
        if slot_json:
            try:
                slot_data = json.loads(slot_json)
                for k, v in slot_data.items():
                    if k not in kwargs or not str(kwargs.get(k, "")).strip():
                        kwargs[k] = v
            except (json.JSONDecodeError, TypeError):
                pass

        # ── Optional: merge bottom control JSON ────────────────────────
        bottom_json = kwargs.get("底部数据", "")
        if bottom_json:
            try:
                bottom_data = json.loads(bottom_json)
                for k, v in bottom_data.items():
                    if k not in kwargs or not str(kwargs.get(k, "")).strip():
                        kwargs[k] = v
            except (json.JSONDecodeError, TypeError):
                pass

        # ── 1-5. Build tag prompt (seed-independent) ──────────────────
        manual_slots: dict[str, str] = {}
        slot_keys = [
            ("人数/身份", "count_identity"),
            ("外貌", "appearance"),
            ("服装", "clothing"),
            ("姿势/动作", "pose_action"),
            ("表情", "expression"),
            ("镜头", "camera"),
            ("场景/环境", "scene"),
            ("细节/氛围", "detail_mood"),
        ]
        for kw_key, slot_name in slot_keys:
            val = kwargs.get(kw_key, "").strip()
            manual_slots[slot_name] = val

        # ── Batch mode (raffle runs PER SEED inside _compose_batch) ──
        # 批量模式在这里直接返回，单次的 tag_prompt 只在单次模式构建
        if is_batch:
            return self._compose_batch(kwargs, manual_slots, batch_seeds_str,
                                       mode, tag_ratio, enable_conflict, nl_source)

        # ── Single mode ─────────────────────────────────────────────────
        seed_val = kwargs.get("随机种子", None)
        if seed_val is None or str(seed_val) == "":
            raw_seed = random.randint(0, 0xFFFF_FFFF_FFFF_FFFF)
        else:
            raw_seed = int(seed_val)

        debug_lines: list[str] = [f"Mode: {mode}", f"Seed: {raw_seed}"]
        seed_kwargs = dict(kwargs)
        seed_kwargs["随机种子"] = raw_seed

        # P4: 抽签 / 槽位抽样 / 画师都从 raw_seed 派生独立子流
        srng = SeedRNG(raw_seed)
        raffle_slots: dict[str, list[str]] = {}
        if mode in ("random", "hybrid"):
            raffle_slots = self._run_raffle(seed_kwargs)

        merged = self._merge_slots(mode, manual_slots, raffle_slots, srng,
                                   self._must_protected(kwargs))
        tag_prompt = self._slots_to_string(merged)

        # Conflict check & removal + dedup (single mode)
        # P6: 检测与移除共用同一套分层逻辑（不再两套匹配分叉）
        # 必含标签与手动槽位同等保护，冲突层不得删除（否则必含被静默打破）
        if enable_conflict and tag_prompt.strip():
            tag_prompt = self._conflict_and_dedup(
                tag_prompt, manual_slots, self._must_protected(kwargs))

        # ── laya 质量门（默认关；关闭/未就绪/无模型 -> 原样，永不抛异常）──
        tag_prompt = self._gate_tag_prompt(
            tag_prompt, seed_kwargs, manual_slots, mode, enable_conflict
        )

        final, nl_used = self._finish_prompt(seed_kwargs, tag_prompt, nl_source, tag_ratio)
        # ── Final dedup: remove duplicate comma-separated tags ────────
        final = self._dedup_final(final)
        debug_lines.append(f"NL: {len(nl_used)} chars")
        debug_lines.append(f"Tags: {len(tag_prompt)} chars")
        return (final, "\n".join(debug_lines), "", "", "")

    @staticmethod
    def _dedup_final(text: str) -> str:
        """Final pass dedup on comma-separated tags while preserving order and non-tag content."""
        if not text.strip():
            return text
        parts = text.split(",")
        seen: set[str] = set()
        result: list[str] = []
        for p in parts:
            clean = p.strip().lower().replace(" ", "_").replace("-", "_")
            if not clean or clean in seen:
                continue
            seen.add(clean)
            result.append(p.strip())
        return ", ".join(result)

    # ── Finish prompt for one seed (steps 6-13) ─────────────────────

    def _finish_prompt(self, kwargs: dict, tag_prompt: str, nl_source: str, tag_ratio: float) -> tuple[str, str]:
        """NL generation, background reorder, assembly, artist. Returns (prompt, nl_used)."""
        # Step 6: Generate NL
        nl_prompt = self._get_nl(kwargs, tag_prompt, nl_source)

        # Step 6b: Reorder background content to end
        bg_tag_keywords = ["background", "outdoors", "outdoor"]
        bg_nl_keywords = [
            "background", "against a", "against the", "set in", "set against",
            "in the background", "in front of", "behind", "surrounded by",
            "scene is set", "environment",
        ]
        tag_items = [t.strip() for t in tag_prompt.split(",") if t.strip()]
        bg_tags = [t for t in tag_items
                   if any(kw in t.lower().replace("_", " ") for kw in bg_tag_keywords)]
        non_bg_tags = [t for t in tag_items if t not in bg_tags]

        import re
        nl_sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', nl_prompt) if s.strip()]
        bg_nl = [s for s in nl_sentences
                 if any(kw in s.lower() for kw in bg_nl_keywords)]
        non_bg_nl = [s for s in nl_sentences if s not in bg_nl]

        main_part = mix_by_ratio(
            ", ".join(non_bg_tags),
            " ".join(non_bg_nl),
            tag_ratio,
        )
        bg_tag_str = ", ".join(bg_tags)
        bg_nl_str = " ".join(bg_nl)
        bg_parts = []
        if bg_tag_str:
            bg_parts.append(bg_tag_str)
        if bg_nl_str and tag_ratio < 1.0:
            bg_parts.append(bg_nl_str)
        bg_part = ", ".join(bg_parts) if bg_parts else ""

        if bg_part:
            final = (main_part + ", " + bg_part) if main_part else bg_part
        else:
            final = main_part

        # Step 8: Artist
        artist_seed_val = kwargs.get("画师种子", None)
        if artist_seed_val is not None and str(artist_seed_val) != "":
            s = int(artist_seed_val)
            artists = _load_artists()
            if artists:
                if s == -1:
                    # P4: 画师走种子派生的命名子流 —— 可复现，
                    # 且不再受「标签数量/抽签环节」连锁影响（旧版用全局
                    # random.randint，同 seed 重跑画师会变）
                    srng = SeedRNG(int(kwargs.get("随机种子", 0)))
                    s = srng.get("artist").randint(1, len(artists))
                idx = max(0, min(s - 1, len(artists) - 1))
                chosen = artists[idx]
                if final:
                    final = final.rstrip(", ") + ", " + chosen
                else:
                    final = chosen
                # s == 0: 无画师，跳过

        return (final, nl_prompt)

    # ── Batch compose ─────────────────────────────────────────────────

    def _compose_batch(self, kwargs: dict, manual_slots: dict, batch_seeds_str: str,
                        mode: str, tag_ratio: float,
                        enable_conflict: bool, nl_source: str) -> tuple[str, str, str, str, str]:
        """Iterate over seeds, run raffle per seed, produce 3 aligned batch outputs."""
        seeds = [s.strip() for s in batch_seeds_str.split("\n") if s.strip()]
        artist_lines = [s.strip() for s in kwargs.get("画师串", "").split("\n") if s.strip()]
        cap_lines = [s.strip() for s in kwargs.get("反推串", "").split("\n") if s.strip()]

        prompts: list[str] = []
        artists_out: list[str] = []
        caps_out: list[str] = []

        should_unload = bool(kwargs.get("生成后卸载", False))
        kwargs["生成后卸载"] = False

        # ── Preload model once before parallel NL generation ──
        _model_preloaded = False
        if nl_source == "lm_studio" and not kwargs.get("API密钥", ""):
            lm_model_name = str(kwargs.get("模型", ""))
            if lm_model_name and lm_model_name not in ("(no models found)", "(检测中…)"):
                try:
                    from .lm_studio import ensure_model_loaded
                    ctx = int(kwargs.get("上下文长度", 4096))
                    # BUG-2 修复：auto_ctx 此前从未定义 → NameError 被外层
                    # except 吞掉 → 批量模式的模型预加载一直静默失败。
                    # 语义对齐单次路径(见 _get_nl 处)：自动上下文 = 最大并发数 × 2048
                    auto_ctx = bool(kwargs.get("自动上下文长度", False))
                    if auto_ctx:
                        ctx = int(kwargs.get("最大并发数", 4)) * 2048
                    if ensure_model_loaded(lm_model_name, context_length=ctx, parallel=int(kwargs.get("最大并发数", 4)) if auto_ctx else None, force=auto_ctx):
                        _model_preloaded = True
                        print(f"[AnimaWeaver] Preloaded model: {lm_model_name}")
                except Exception as e:
                    print(f"[AnimaWeaver] Preload failed: {e}")

        # Phase 1: Sequential raffle + tag assembly per seed
        from concurrent.futures import ThreadPoolExecutor, as_completed

        concurrency = int(kwargs.get("请求数", 4))
        seed_task_data: list[tuple[dict, str, int]] = []  # (seed_kwargs, tag_prompt, index)

        for i, seed_str in enumerate(seeds):
            try:
                raw_seed = int(seed_str)
            except ValueError:
                continue

            seed_kwargs = dict(kwargs)
            seed_kwargs["随机种子"] = raw_seed

            # ── Per-seed raffle + tag_prompt ──────────────────────────
            # P4: 每个种子独立 SeedRNG（子流派生，互不耦合）
            raffle = self._run_raffle(seed_kwargs) if mode in ("random", "hybrid") else {}
            merged = self._merge_slots(mode, manual_slots, raffle, SeedRNG(raw_seed),
                                       AnimaWeaver._must_protected(kwargs))
            tag_prompt = self._slots_to_string(merged)
            if enable_conflict and tag_prompt.strip():
                # P6: 检测与移除共用同一套分层逻辑；必含标签受保护
                tag_prompt = self._conflict_and_dedup(
                    tag_prompt, manual_slots,
                    AnimaWeaver._must_protected(kwargs))
            # ── laya 质量门（默认关；关闭/未就绪/无模型 -> 原样，永不抛异常）──
            tag_prompt = self._gate_tag_prompt(
                tag_prompt, seed_kwargs, manual_slots, mode, enable_conflict
            )

            # ── Override artist if batch provides it ───────────────────
            if i < len(artist_lines):
                al = artist_lines[i]
                if "[" in al and "]" in al:
                    try:
                        idx = int(al.split("[")[1].split("]")[0])
                        seed_kwargs["画师种子"] = idx
                    except (ValueError, IndexError):
                        pass

            seed_task_data.append((seed_kwargs, tag_prompt, i))

        # Mark all seed_kwargs as preloaded for parallel phase
        if _model_preloaded:
            for sk, _, _ in seed_task_data:
                sk["_preloaded"] = True

        # Phase 2: Parallel NL generation + final assembly
        prompts = [""] * len(seeds)
        artists_out = [""] * len(seeds)
        caps_out = [""] * len(seeds)
        seed_index_to_i: dict[int, int] = {}  # maps task index to original seed index
        for task_idx, (_, _, orig_i) in enumerate(seed_task_data):
            seed_index_to_i[task_idx] = orig_i

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            fut_to_idx: dict = {}
            for task_idx, (sk, tp, orig_i) in enumerate(seed_task_data):
                fut = executor.submit(self._finish_prompt, sk, tp, nl_source, tag_ratio)
                fut_to_idx[fut] = task_idx

            for future in as_completed(fut_to_idx):
                task_idx = fut_to_idx[future]
                orig_i = seed_index_to_i[task_idx]
                try:
                    final, _ = future.result()
                    final = self._dedup_final(final)
                    prompts[orig_i] = final
                except Exception as e:
                    print(f"[AnimaWeaver] batch seed {orig_i} error: {e}")
                    prompts[orig_i] = ""
                artists_out[orig_i] = artist_lines[orig_i] if orig_i < len(artist_lines) else ""
                caps_out[orig_i] = cap_lines[orig_i] if orig_i < len(cap_lines) else ""

        # Filter out empty results
        prompts = [p for p in prompts if p]

        if should_unload and prompts:
            try:
                from .lm_studio import unload_all
                unload_all()
            except Exception:
                pass

        debug = f"Batch: {len(seeds)} seeds, {len(prompts)} prompts"
        out_prompts = "\n".join(prompts)
        return (
            out_prompts,
            debug,
            "\n".join(artists_out),
            "\n".join(caps_out),
        )

    # ── Slot merging ───────────────────────────────────────────────

    @staticmethod
    def _merge_slots(
        mode: str,
        manual: dict[str, str],
        raffle: dict[str, list[str]],
        srng: Optional["SeedRNG"] = None,
        protect: set = None,
    ) -> dict[str, str]:
        """
        Merge manual and Raffle tags per slot.

        Strategy:
          manual   → pure manual
          random   → pure Raffle
          hybrid   → Raffle (up to 8) + manual appended (higher weight)

        P4: hybrid 的 Raffle 部分用随机抽样 sample_slot（替代 [:8]
        位置截断，消除字母序偏差）；srng 为 None（旧调用路径）时退回 [:8]。
        """
        merged: dict[str, str] = {}
        for slot in SLOT_ORDER:
            manual_tags = manual.get(slot, "").strip()
            raffle_tags = raffle.get(slot, [])

            if mode == "manual":
                merged[slot] = manual_tags

            elif mode == "random":
                merged[slot] = ", ".join(raffle_tags)

            elif mode == "hybrid":
                if srng is not None:
                    combined = sample_slot(srng, raffle_tags, slot, k=8, protect=protect)
                else:
                    combined = list(raffle_tags[:8])
                if manual_tags:
                    manual_list = [
                        t.strip()
                        for t in manual_tags.split(",")
                        if t.strip()
                    ]
                    combined.extend(manual_list)
                merged[slot] = ", ".join(combined)

        return merged

    # ── Raffle extraction ──────────────────────────────────────────

    @staticmethod
    def _run_raffle(kwargs: dict[str, Any]) -> dict[str, list[str]]:
        """
        Pick a random taglist line from the configured Raffle files,
        classify each tag via ``categorized_tags.txt``, and map
        categories to slots via ``category_to_slot.json``.

        P1: 行偏移表（.idx 磁盘缓存）+ 分类字典模块级缓存 ——
            不再每种子全文件扫描（批量 256 种子 21s -> ~0.1s），
            并解锁全部 ~10 万行（旧版只扫前 5000 行）。
        P4: 命名子流派生文件/行选择（替代 shuffle + seed%len）；
            META_TAGS 过滤元数据垃圾标签；QUALITY_TAGS 可选（默认关）。
        P5: 三级混合抽取（拒绝采样 -> 倒排索引 -> 全量扫描），
            「必含/排除」严格满足、0 静默违规；无解明确返回 {}。

        Returns a dict ``{slot_name: [tag_str, ...]}``.
        """
        extension_path = os.path.dirname(os.path.abspath(__file__))
        tags_dir = os.path.join(extension_path, "tags")

        # ── Determine which files to use ─────────────────────────
        file_flags = [
            ("通用标签", "taglists-general.txt"),
            ("争议标签", "taglists-questionable.txt"),
            ("敏感标签",  "taglists-sensitive.txt"),
            ("露骨标签",   "taglists-explicit.txt"),
        ]
        enabled_files: list[str] = []
        for flag, fname in file_flags:
            if kwargs.get(flag, False):
                enabled_files.append(fname)
        if not enabled_files:
            # Fallback default（保留：无启用文件时兜底 sensitive+explicit 旧逻辑）
            enabled_files = ["taglists-sensitive.txt", "taglists-explicit.txt"]

        # ── Load category → slot mapping（P1: 模块级缓存，只解析一次）──
        cat_to_slot: dict[str, str] = get_slot_map(tags_dir)
        if not cat_to_slot:
            return {}

        # ── Load category tags index（P1: 模块级缓存，只解析一次）──
        tag_to_category: dict[str, str] = get_category_map(tags_dir)
        if not tag_to_category:
            return {}

        # ── Filter parameters ────────────────────────────────────
        exclude_containing = _parse_comma_field(
            kwargs.get("排除含标签列表", "")
        )
        must_include = _parse_comma_field(
            kwargs.get("标签列表必含", "")
        )
        excluded_cats = _parse_comma_field(
            kwargs.get("排除标签分类", "")
        )
        filter_out = _parse_comma_field(
            kwargs.get("过滤标签", "")
        )

        # ── P4: 命名子流（替代旧的单一 rng + shuffle + seed%len）──
        # 旧版 rng.shuffle(enabled_files) 是纯浪费（shuffle 结果被丢弃），
        # enabled_files[seed % len] 让种子奇偶决定文件（0 bit 随机性）。
        seed = int(kwargs.get("随机种子", 0))
        srng = SeedRNG(seed)
        rng = srng.get("raffle")

        # ── Pick a random file: rng.randrange 替代 seed % len ─────
        selected_file = enabled_files[rng.randrange(len(enabled_files))]
        filepath = os.path.join(tags_dir, selected_file)

        # ── P1: 行偏移索引（建一次，.idx 磁盘缓存；文件缺失 -> {}）──
        try:
            idx = get_tag_index(filepath)
        except OSError:
            return {}

        # ── P5: 三级混合抽取（must/exclude 严格满足，无解明确返回）──
        selected_tags, source = pick_line(
            idx, rng, must=must_include, excl=exclude_containing
        )
        if not selected_tags:
            return {}  # 索引确认无解（或文件为空），明确返回

        # ── P4: 垃圾标签黑名单（META_TAGS 常开；QUALITY_TAGS 可选默认关）──
        drop = META_TAGS
        if bool(kwargs.get("过滤质量标签", False)):
            drop = META_TAGS | QUALITY_TAGS

        # ── Classify into slots ─────────────────────────────────
        # selected_tags 已由 fast_parse_line 归一化（lower + 空格转下划线）
        slot_tags: dict[str, list[str]] = {slot: [] for slot in SLOT_ORDER}

        for tag in selected_tags:
            if not tag:
                continue
            if tag in filter_out:
                continue
            if tag in drop:
                continue

            category = tag_to_category.get(tag, "")
            if not category:
                continue
            if category in excluded_cats:
                continue

            target_slot = cat_to_slot.get(category, "")
            if target_slot in slot_tags:
                slot_tags[target_slot].append(tag)

        return slot_tags

    # ── Tag-string utility ────────────────────────────────────────

    @staticmethod
    def _slots_to_string(merged_slots: dict[str, str]) -> str:
        """Flatten slot dict into a single comma-separated tag string."""
        parts: list[str] = []
        for slot in SLOT_ORDER:
            val = merged_slots.get(slot, "").strip()
            if val:
                parts.append(val)
        return ", ".join(parts)

    # ── NL generation ─────────────────────────────────────────────

    @staticmethod
    def _get_nl(
        kwargs: dict[str, Any],
        tag_prompt: str,
        nl_source: str,
    ) -> str:
        """
        Obtain the natural-language portion of the prompt.

        If ``nl_source == "lm_studio"`` and a model is configured, try
        to generate text via the LM Studio HTTP API (local or cloud).
        Otherwise return the manual NL text.
        """
        if nl_source == "lm_studio" and tag_prompt.strip():
            lm_model = kwargs.get("模型", "")
            if lm_model and lm_model not in ("(no models found)", "(检测中…)"):
                model_was_loaded = False
                nl = ""
                try:
                    from .lm_studio import (
                        ensure_model_loaded,
                        generate_nl_from_lm_studio,
                        unload_all,
                    )
                    ctx = int(kwargs.get("上下文长度", 4096))
                    base_url = str(
                        kwargs.get("API地址", "http://localhost:1234/v1")
                    )
                    api_key = kwargs.get("API密钥", "")
                    cloud_model = kwargs.get("云端模型名", "").strip()
                    detailed_nl = bool(kwargs.get("强制详细自然语言", False))
                    auto_ctx = bool(kwargs.get("自动上下文长度", False))
                    aspect_ratio = kwargs.get("aspect_ratio", "")

                    if api_key:
                        # 云端 API：跳过 lms load，直接发请求
                        model_for_api = cloud_model or lm_model
                        custom_sp = kwargs.get("详细 NL 系统提示词", "") if detailed_nl else kwargs.get("系统提示词", "")
                        max_tok = int(kwargs.get("最大截断长度", 0))
                        if max_tok == 0:
                            max_tok = 512 if detailed_nl else 256
                        nl = generate_nl_from_lm_studio(
                            tag_prompt, base_url,
                            api_key=api_key, model_name=model_for_api,
                            detailed=detailed_nl,
                            aspect_ratio=aspect_ratio,
                            timeout=180,
                            system_prompt=custom_sp,
                            max_tokens_override=max_tok,
                        )
                    else:
                        # 本地 LM Studio：先加载模型再调用 API
                        # 如果已在外部加载过（批量并发），跳过重复加载
                        if not kwargs.get("_preloaded"):
                            model_was_loaded = ensure_model_loaded(lm_model, context_length=ctx, parallel=int(kwargs.get("最大并发数", 4)) if auto_ctx else None, force=auto_ctx)
                        else:
                            model_was_loaded = True
                        if model_was_loaded:
                            # Custom system prompt: detailed takes priority if in detailed mode
                            custom_sp = kwargs.get("详细 NL 系统提示词", "") if detailed_nl else kwargs.get("系统提示词", "")
                            max_tok = int(kwargs.get("最大截断长度", 0))
                            if max_tok == 0:
                                max_tok = 512 if detailed_nl else 256
                            nl = generate_nl_from_lm_studio(
                                tag_prompt, base_url,
                                model_name=lm_model,
                                detailed=detailed_nl,
                                aspect_ratio=aspect_ratio,
                                timeout=180,
                                system_prompt=custom_sp,
                                max_tokens_override=max_tok,
                            )

                    if nl:
                        return nl
                except Exception:
                    pass
                finally:
                    # 无论成功失败，只要要求卸载且模型被加载过就卸载
                    if kwargs.get("生成后卸载", False) and model_was_loaded:
                        try:
                            from .lm_studio import unload_all
                            unload_all()
                        except Exception:
                            pass
        return kwargs.get("自然语言描述", "")

    # ── Conflict detection + removal (P6) ─────────────────────────

    @staticmethod
    def _must_protected(kwargs: dict) -> set:
        """「标签列表必含」→ 冲突层保护集（归一化，与手动槽位同等保护）。"""
        try:
            raw = str(kwargs.get("标签列表必含", "") or "")
        except Exception:
            return set()
        return {t.strip().lower().replace(" ", "_")
                for t in raw.split(",") if t.strip()}

    @staticmethod
    def _conflict_and_dedup(tag_prompt: str, manual_slots: dict[str, str],
                            extra_protected: set = None) -> str:
        """
        冲突检测 + 移除（P6：检测与移除共用 rules.resolve_conflicts 同一套
        分层逻辑，警告与实际删除永远一致）+ 标签去重。

        extra_protected: 「标签列表必含」等用户显式要求的标签 —— 与手动槽位
        同等保护，永不因冲突被删（否则必含过滤会被冲突层静默打破）。
        """
        if not tag_prompt.strip():
            return tag_prompt
        all_tags = [t.strip() for t in tag_prompt.split(",") if t.strip()]
        conflicts = check_conflicts(all_tags)
        if conflicts:
            tag_prompt = AnimaWeaver._remove_conflicts(tag_prompt, conflicts,
                                                       manual_slots, extra_protected)
        # Dedup tag_prompt（- 与 空格 统一归一后判重）
        seen: set[str] = set()
        deduped: list[str] = []
        for t in tag_prompt.split(","):
            tc = t.strip().lower().replace(" ", "_").replace("-", "_")
            if not tc or tc in seen:
                continue
            seen.add(tc)
            deduped.append(t.strip())
        if len(deduped) < len(all_tags):
            tag_prompt = ", ".join(deduped)
        return tag_prompt

    @staticmethod
    def _remove_conflicts(
        tag_prompt: str,
        conflicts: list[str],
        manual_slots: dict[str, str],
        extra_protected: set = None,
    ) -> str:
        """
        P6: 冲突移除（替代旧 CONFLICT_PAIRS 子串匹配双删版）。

        旧版三个 bug：
          1. 检测用精确匹配、移除用子串匹配（lap_pov/solo_focus 被误伤）
          2. 子串误伤（wide_spread_legs 被 spread_legs 误删）
          3. 冲突时两个都删（视角/人数信息全丢）

        现在检测与移除都走 rules.resolve_conflicts：
          - 只精确匹配，无子串误伤
          - 冲突时删一个、保留首个出现者（确定性，不引入随机）
          - 手动槽位标签永不删除
        """
        # Collect all manual tags (normalised)
        manual_tags: set[str] = set()
        for slot in SLOT_ORDER:
            val = manual_slots.get(slot, "").strip()
            if val:
                for t in val.split(","):
                    mt = t.strip().lower().replace(" ", "_")
                    if mt:
                        manual_tags.add(mt)
        # 用户显式必含的标签与手动槽位同等保护（归一化并入）
        if extra_protected:
            for t in extra_protected:
                mt = str(t).strip().lower().replace(" ", "_")
                if mt:
                    manual_tags.add(mt)

        all_tags = [t.strip() for t in tag_prompt.split(",") if t.strip()]
        norm_tags = [t.lower().replace(" ", "_") for t in all_tags]

        kept, _record = resolve_conflicts(norm_tags, manual_tags=manual_tags)

        # 把归一化 kept 映射回原始形式（保持原顺序/原始大小写）
        from collections import Counter
        kept_counter = Counter(kept)
        result: list[str] = []
        for t in all_tags:
            tn = t.lower().replace(" ", "_")
            if kept_counter.get(tn, 0) > 0:
                result.append(t)
                kept_counter[tn] -= 1
        return ", ".join(result)

    # ── laya quality gate (optional, default off) ────────────────

    def _gate_tag_prompt(self, tag_prompt: str, kwargs: dict,
                         manual_slots: dict, mode: str,
                         enable_conflict: bool) -> str:
        """
        laya 质量门（默认关闭；控件由母代理阶段 2 统一加到 INPUT_TYPES，
        这里只读 kwargs 键「启用laya门控」，默认 False）。

        - 关闭 / laya 未装 / 模型未就绪 / predict 失败：返回原样，永不抛异常
        - 开启且就绪：judge_keep 评分；不合格 -> 派生种子重抽一次；
          仍不合格 -> 保留原样（绝不返回空）
        """
        if not bool(kwargs.get("启用laya门控", False)):
            return tag_prompt
        try:
            if laya_gate.judge_keep(tag_prompt):
                return tag_prompt
            # 本次抽签不合格：派生种子重抽一次（确定性，可复现）
            seed = int(kwargs.get("随机种子", 0))
            reroll_kwargs = dict(kwargs)
            reroll_kwargs["随机种子"] = (
                seed * 0x85EBCA6B + 0xC2B2AE35
            ) & 0xFFFFFFFFFFFFFFFF
            raffle = self._run_raffle(reroll_kwargs) if mode in ("random", "hybrid") else {}
            merged = self._merge_slots(
                mode, manual_slots, raffle, SeedRNG(reroll_kwargs["随机种子"]),
                AnimaWeaver._must_protected(reroll_kwargs),
            )
            tp2 = self._slots_to_string(merged)
            if enable_conflict and tp2.strip():
                tp2 = self._conflict_and_dedup(
                    tp2, manual_slots,
                    AnimaWeaver._must_protected(reroll_kwargs))
            if laya_gate.judge_keep(tp2):
                return tp2
            return tag_prompt  # 两次都不合格 -> 保留原样，绝不空
        except Exception:
            return tag_prompt

    # ── Background reordering ─────────────────────────────────────

    @staticmethod
    def _reorder_background_to_end(text: str, is_tags: bool) -> str:
        """Move background-related content to the very end."""
        if not text.strip():
            return text
        bg_keywords = [
            "background", "wall", "window", "door", "curtain", "floor",
            "ceiling", "indoors", "outdoors", "indoor", "outdoor",
            "behind", "scenery", "environment", "setting", "surrounding",
        ]
        if is_tags:
            items = [t.strip() for t in text.split(",") if t.strip()]
            bg = [i for i in items if any(kw in i.lower().replace(" ", "_") for kw in bg_keywords)]
            other = [i for i in items if i not in bg]
            return ", ".join(other + bg) if bg else text
        else:
            import re
            ss = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
            bg = [s for s in ss if any(kw in s.lower() for kw in bg_keywords)]
            other = [s for s in ss if s not in bg]
            return " ".join(other + bg) if bg else text


# ── Helpers ────────────────────────────────────────────────────────

def _parse_comma_field(text: str) -> set[str]:
    """
    Parse a multiline or comma-separated text field into a set of
    normalised strings.

    Examples
    --------
    >>> _parse_comma_field("1girl, solo\\nblush")
    {'1girl', 'solo', 'blush'}
    """
    if not text or not text.strip():
        return set()
    return set(
        t.strip().lower().replace(" ", "_")
        for t in text.replace("\n", ",").split(",")
        if t.strip()
    )


# ── 后台预热（P1 + P5）────────────────────────────────────────────
# 行偏移表（.idx 落盘缓存）+ 倒排索引（~1s/文件）全部放后台线程，
# 绝不阻塞节点启动/首跑。设 ANIMA_NO_WARMUP=1 可跳过（单测用）。

def _start_warmup() -> None:
    tags_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tags")
    files = [
        "taglists-general.txt",
        "taglists-questionable.txt",
        "taglists-sensitive.txt",
        "taglists-explicit.txt",
    ]

    def _run():
        # 分类字典（模块级缓存，只解析一次）
        try:
            get_category_map(tags_dir)
        except Exception:
            pass
        for fn in files:
            try:
                idx = get_tag_index(os.path.join(tags_dir, fn))
            except Exception:
                continue
            # P5: 该文件的倒排索引（严格过滤走第 2 级，~2-7ms）
            try:
                build_sync(idx)
            except Exception:
                pass

    threading.Thread(target=_run, name="anima-warmup", daemon=True).start()


if os.environ.get("ANIMA_NO_WARMUP") != "1":
    _start_warmup()
