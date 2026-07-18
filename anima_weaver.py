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
import re
from typing import Any, Optional

try:
    from .rules import check_conflicts, CONFLICT_PAIRS
    from .assembly import assemble_prompt, mix_by_ratio, SLOT_ORDER, SLOT_LIMITS
except ImportError:
    from rules import check_conflicts, CONFLICT_PAIRS
    from assembly import assemble_prompt, mix_by_ratio, SLOT_ORDER, SLOT_LIMITS

# ── Artist index (lazy loaded) ────────────────────────────────────────

import os as _os

_ARTIST_LIST: list[str] | None = None
_ARTIST_FILE = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "tags", "Anima2B_Artist_Index_59k.txt",
)

def _load_artists() -> list[str]:
    global _ARTIST_LIST
    if _ARTIST_LIST is not None:
        return _ARTIST_LIST
    artists: list[str] = []
    try:
        with open(_ARTIST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("This"):
                    continue
                if line.startswith("@"):
                    artists.append(line)
        _ARTIST_LIST = artists
        print(f"Anima Weaver: loaded {len(artists)} artists")
    except Exception as e:
        print(f"Anima Weaver: failed to load artist index: {e}")
        _ARTIST_LIST = artists
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

        return {
            "required": {
                # ── Mode ──────────────────────────────────────────
                "模式": (
                    ["manual", "random", "hybrid"],
                    {"default": "hybrid"},
                ),
                "标签比例": (
                    "FLOAT",
                    {"default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05},
                ),
                "场景类型": (
                    [
                        "solo_display",
                        "couple_foreplay",
                        "couple_sex",
                        "group",
                        "yuri",
                        "special_theme",
                    ],
                ),

                # ── Natural Language ──────────────────────────────
                "自然语言来源": (
                    ["manual", "lm_studio"],
                    {"default": "manual"},
                ),
                "模型": (model_list,),
                "生成后卸载": (
                    "BOOLEAN",
                    {"default": False},
                ),
                "API密钥": (
                    "STRING",
                    {"default": ""},
                ),
                "云端模型名": (
                    "STRING",
                    {"default": "", "tooltip": "云端模型名（如 deepseek-chat），填 API 密钥时此值会覆盖下拉框的模型选择"},
                ),
                "上下文长度": (
                    "INT",
                    {"default": 8192, "min": 0, "max": 262144},
                ),
                "API地址": (
                    "STRING",
                    {"default": "http://localhost:1234/v1", "multiline": False,
                     "tooltip": "LM Studio API 地址（或兼容 OpenAI 的 API 地址）"},
                ),
                "云端模型名": (
                    "STRING",
                    {"default": "deepseek-chat", "tooltip": "云端模型名（如 deepseek-chat），填 API 密钥时此值会覆盖下拉框的模型选择"},
                ),
                "强制详细自然语言": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "开启后 NL 描述至少 10 句，非常详细（使用 512 tokens）"},
                ),
                "最大截断长度": (
                    "INT",
                    {"default": 0, "min": 0, "max": 1080, "step": 8,
                     "tooltip": "0=自动（普通256/详细512），256~1080=手动设置最大 token 数"},
                ),

                # ── Artist ──────────────────────────────────────────
                "画师种子": (
                    "INT",
                    {"default": 0, "min": -1, "max": 0x7FFFFFFF,
                     "tooltip": "-1=随机画师，0=无画师，1~=固定画师序号"},
                ),

                # ── Raffle random parameters ──────────────────────
                "冲突检查": (
                    "BOOLEAN",
                    {"default": True},
                ),
                "请求数": (
                    "INT",
                    {"default": 4, "min": 1, "max": 128, "step": 1,
                     "tooltip": "批量模式并发请求数。本地模型建议保持 4（默认）或更低，显存足够/云端模型可尝试更高的值，可能有其他未知问题"},
                ),
            },
            "optional": {
                "随机种子": (
                    "INT",
                    {"forceInput": True, "default": 0, "min": 0, "max": 0xFFFF_FFFF_FFFF_FFFF,
                     "tooltip": "从外部种子节点接入，不接则使用内部随机值"},
                ),
                "槽位数据": (
                    "STRING",
                    {"forceInput": True, "tooltip": "从「提示词槽位」节点接入标签和自然语言描述"},
                ),
                "底部数据": (
                    "STRING",
                    {"forceInput": True, "tooltip": "从「底部控制」节点接入 Raffle 过滤参数"},
                ),
                "自动上下文长度": (
                    "BOOLEAN",
                    {"default": False,
                     "tooltip": "启用后自动计算上下文长度 = 最大并发数 × 1684，仅本地模型有效"},
                ),
                "系统提示词": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "可选。自定义系统提示词，留空使用默认提示词"},
                ),
                "分辨率": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "接入分辨率（单值或多行每行一个），用于 NL 生成时描述构图"}
                ),
                "种子串": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "接入批量种子串（每行一个种子），开启批量模式"},
                ),
                "画师串": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "接入画师串（每行一个画师），与种子串行对齐"},
                ),

                "反推串": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "接入反推串（每行一个），与种子串行对齐"},
                ),

            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("生成的提示词", "调试信息", "画师串", "分辨率串", "反推串")
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
        """Always re-execute (seed is handled externally)."""
        import random
        return random.random()

    # ── Main composition entry point ──────────────────────────────

    def compose(self, **kwargs) -> tuple[str, str, str, str, str, str]:
        """
        Main node workflow. Returns 6-tuple (single_prompt, debug, +4 batch outs).
        """
        mode = kwargs.get("模式", "hybrid")
        tag_ratio = float(kwargs.get("标签比例", 0.6))
        nl_source = kwargs.get("自然语言来源", "manual")
        enable_conflict = bool(kwargs.get("冲突检查", True))

        # ── Mutually exclusive: 种子串 overrides 随机种子 ──────────────
        batch_seeds_str = kwargs.get("种子串", "")
        is_batch = bool(batch_seeds_str.strip())
        if is_batch:
            kwargs.pop("随机种子", None)  # 批量模式下忽略随机种子

        # ── Mutually exclusive: 分辨率串 overrides 分辨率 ──────────────
        res_str = kwargs.get("分辨率", "")
        if res_str.strip():
            kwargs.pop("分辨率", None)  # 分辨率串模式下忽略分辨率

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

        raffle_slots: dict[str, list[str]] = {}
        if mode in ("random", "hybrid"):
            raffle_slots = self._run_raffle(kwargs)

        merged = self._merge_slots(mode, manual_slots, raffle_slots)
        tag_prompt = self._slots_to_string(merged)

        # Conflict check & removal (single mode)
        if enable_conflict and tag_prompt.strip():
            all_tags = [t.strip() for t in tag_prompt.split(",") if t.strip()]
            conflicts = check_conflicts(all_tags)
            if conflicts:
                tag_prompt = self._remove_conflicts(tag_prompt, conflicts, manual_slots)
            seen: set[str] = set()
            deduped: list[str] = []
            for t in tag_prompt.split(","):
                t_clean = t.strip().lower().replace(" ", "_")
                if not t_clean:
                    continue
                if t_clean in seen:
                    continue
                seen.add(t_clean)
                deduped.append(t.strip())
            if len(deduped) < len(all_tags):
                tag_prompt = ", ".join(deduped)

        # ── Batch mode (raffle runs PER SEED inside _compose_batch) ──
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
                    s = random.randint(1, len(artists))
                    idx = max(0, min(s - 1, len(artists) - 1))
                    chosen = artists[idx]
                    if final:
                        final = final.rstrip(", ") + ", " + chosen
                    else:
                        final = chosen
                elif s > 0:
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
                        enable_conflict: bool, nl_source: str) -> tuple[str, str, str, str, str, str]:
        """Iterate over seeds, run raffle per seed, produce 4 aligned batch outputs."""
        seeds = [s.strip() for s in batch_seeds_str.split("\n") if s.strip()]
        artist_lines = [s.strip() for s in kwargs.get("画师串", "").split("\n") if s.strip()]
        res_lines = [s.strip() for s in kwargs.get("分辨率", "").split("\n") if s.strip()]
        cap_lines = [s.strip() for s in kwargs.get("反推串", "").split("\n") if s.strip()]

        prompts: list[str] = []
        artists_out: list[str] = []
        res_out: list[str] = []
        caps_out: list[str] = []

        should_unload = bool(kwargs.get("生成后卸载", False))
        kwargs["生成后卸载"] = False

        # ── Preload model once before parallel NL generation ──
        _model_preloaded = False
        if nl_source == "lm_studio" and not kwargs.get("API密钥", ""):
            lm_model_name = str(kwargs.get("模型", ""))
            if lm_model_name and lm_model_name != "(no models found)":
                try:
                    from .lm_studio import ensure_model_loaded
                    ctx = int(kwargs.get("上下文长度", 4096))
                    if ensure_model_loaded(lm_model_name, context_length=ctx, parallel=int(kwargs.get("最大并发数", 4))):
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
            raffle = self._run_raffle(seed_kwargs) if mode in ("random", "hybrid") else {}
            merged = self._merge_slots(mode, manual_slots, raffle)
            tag_prompt = self._slots_to_string(merged)
            if enable_conflict and tag_prompt.strip():
                from .rules import check_conflicts
                all_tags = [t.strip() for t in tag_prompt.split(",") if t.strip()]
                conflicts = check_conflicts(all_tags)
                if conflicts:
                    tag_prompt = self._remove_conflicts(tag_prompt, conflicts, manual_slots)
                # Dedup tag_prompt before NL generation
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

            # ── Override artist if batch provides it ───────────────────
            if i < len(artist_lines):
                al = artist_lines[i]
                if "[" in al and "]" in al:
                    try:
                        idx = int(al.split("[")[1].split("]")[0])
                        seed_kwargs["画师种子"] = idx
                    except (ValueError, IndexError):
                        pass

            # Per-seed resolution from 分辨率串
            if i < len(res_lines):
                seed_kwargs["分辨率"] = res_lines[i]

            seed_task_data.append((seed_kwargs, tag_prompt, i))

        # Mark all seed_kwargs as preloaded for parallel phase
        if _model_preloaded:
            for sk, _, _ in seed_task_data:
                sk["_preloaded"] = True

        # Phase 2: Parallel NL generation + final assembly
        prompts = [""] * len(seeds)
        artists_out = [""] * len(seeds)
        res_out = [""] * len(seeds)
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
                res_out[orig_i] = res_lines[orig_i] if orig_i < len(res_lines) else ""
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
            "\n".join(res_out),
            "\n".join(caps_out),
        )

    # ── Slot merging ───────────────────────────────────────────────

    @staticmethod
    def _merge_slots(
        mode: str,
        manual: dict[str, str],
        raffle: dict[str, list[str]],
    ) -> dict[str, str]:
        """
        Merge manual and Raffle tags per slot.

        Strategy:
          manual   → pure manual
          random   → pure Raffle
          hybrid   → Raffle (up to 8) + manual appended (higher weight)
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
                combined = list(raffle_tags[:8])  # cap Raffle at 8
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
            # Fallback default
            enabled_files = ["taglists-sensitive.txt", "taglists-explicit.txt"]

        # ── Load category → slot mapping ─────────────────────────
        cat_map_path = os.path.join(tags_dir, "category_to_slot.json")
        try:
            with open(cat_map_path, "r", encoding="utf-8") as f:
                cat_to_slot: dict[str, str] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

        # ── Load category tags index ─────────────────────────────
        #   Format: "[category] tag_name"
        tag_to_category: dict[str, str] = {}
        cat_tags_path = os.path.join(tags_dir, "categorized_tags.txt")
        try:
            with open(cat_tags_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Expected: "[category] tag"
                    if line.startswith("[") and "] " in line:
                        parts = line.split("] ", 1)
                        category = parts[0][1:]  # strip leading '['
                        tag = parts[1].strip().lower().replace(" ", "_")
                        tag_to_category[tag] = category
        except FileNotFoundError:
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

        # ── Seed random ──────────────────────────────────────────
        seed = int(kwargs.get("随机种子", 0))
        rng = random.Random(seed)

        # ── Pick a random file (weighted by seed) ────────────────
        rng.shuffle(enabled_files)
        selected_file = enabled_files[seed % len(enabled_files)]
        filepath = os.path.join(tags_dir, selected_file)

        # ── Scan for valid tag lists ─────────────────────────────
        valid_taglists: list[list[str]] = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    # Format: post_id, resolution, tag1, tag2, ...
                    parts = line.strip().split(", ", 2)
                    if len(parts) >= 3:
                        tags_str = parts[2]
                    else:
                        continue

                    tag_set: list[str] = [
                        t.strip().lower().replace(" ", "_")
                        for t in tags_str.split(", ")
                        if t.strip()
                    ]

                    # Filter: exclude lists containing certain tags
                    if exclude_containing:
                        if not set(tag_set).isdisjoint(exclude_containing):
                            continue

                    # Filter: must include certain tags
                    if must_include:
                        if not must_include.issubset(set(tag_set)):
                            continue

                    valid_taglists.append(tag_set)
                    if len(valid_taglists) >= 5000:
                        break
        except FileNotFoundError:
            return {}

        if not valid_taglists:
            return {}

        # ── Pick one line ────────────────────────────────────────
        selected_tags = valid_taglists[seed % len(valid_taglists)]

        # ── Classify into slots ─────────────────────────────────
        slot_tags: dict[str, list[str]] = {slot: [] for slot in SLOT_ORDER}

        for tag in selected_tags:
            tag_clean = tag.strip().lower().replace(" ", "_")

            if not tag_clean:
                continue
            if tag_clean in filter_out:
                continue

            category = tag_to_category.get(tag_clean, "")
            if not category:
                continue
            if category in excluded_cats:
                continue

            target_slot = cat_to_slot.get(category, "")
            if target_slot in slot_tags:
                slot_tags[target_slot].append(tag_clean)

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
            if lm_model and lm_model != "(no models found)":
                model_was_loaded = False
                nl = ""
                try:
                    from .lm_studio import (
                        ensure_model_loaded,
                        generate_nl_from_lm_studio,
                        get_loaded_models,
                        unload_all,
                    )
                    ctx = int(kwargs.get("上下文长度", 4096))
                    base_url = str(
                        kwargs.get("API地址", "http://localhost:1234/v1")
                    )
                    api_key = kwargs.get("API密钥", "")
                    cloud_model = kwargs.get("云端模型名", "").strip()
                    detailed_nl = bool(kwargs.get("强制详细自然语言", False))
                    aspect_ratio = str(kwargs.get("分辨率", "") or "")

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
                            model_was_loaded = ensure_model_loaded(lm_model, context_length=ctx, parallel=int(kwargs.get("最大并发数", 4)))
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

    # ── Conflict removal ──────────────────────────────────────────

    @staticmethod
    def _remove_conflicts(
        tag_prompt: str,
        conflicts: list[str],
        manual_slots: dict[str, str],
    ) -> str:
        """
        Remove Raffle-sourced conflicting tags from *tag_prompt*,
        preserving any tags that came from the manual slots.

        Parameters
        ----------
        tag_prompt : str
            The full comma-separated tag prompt.
        conflicts : list[str]
            Conflict descriptions from ``check_conflicts``.
        manual_slots : dict[str, str]
            Manual slot dictionary to identify protected tags.

        Returns
        -------
        str
            Cleaned tag prompt.
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

        all_tags = [t.strip() for t in tag_prompt.split(",") if t.strip()]
        to_remove: set[str] = set()

        for tag_a, tag_b in CONFLICT_PAIRS:
            norm_a = tag_a.lower().replace(" ", "_")
            norm_b = tag_b.lower().replace(" ", "_")

            has_a = False
            has_b = False
            for t in all_tags:
                tn = t.lower().replace(" ", "_")
                if norm_a in tn:
                    has_a = True
                if norm_b in tn:
                    has_b = True

            if has_a and has_b:
                for t in all_tags:
                    tn = t.lower().replace(" ", "_")
                    if norm_a in tn and t not in manual_tags:
                        to_remove.add(t)
                    if norm_b in tn and t not in manual_tags:
                        to_remove.add(t)

        result = [t for t in all_tags if t not in to_remove]
        return ", ".join(result)

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
