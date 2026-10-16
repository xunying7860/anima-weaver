"""
05_random_logic.py —— 主节点随机逻辑的纯逻辑修复（不需要任何模型）
=================================================================
实测发现 4 个问题，全是白送的收益：

【问题 1】3.1% 的标签是元数据/垃圾标签，直接进了提示词
-----------------------------------------------------
抽样 taglists-sensitive.txt 前 5000 行（241424 个标签）：

    垃圾标签 7554 个 (3.1%)
      absurdres(2281)  commentary(2245)  commentary_request(990)
      english_commentary(853)  artist_name(404)  bad_id(247)
      signature(209)  translated(70)

这些是 Danbooru 的**元数据**，不是画面内容。把 "commentary"、
"absurdres"、"bad_id" 塞进提示词，等于告诉 SD「请生成一张有评论的、
分辨率爆表的、ID 损坏的图」。SD 对这些 tag 要么无响应，要么产生
不可预测的副作用。

【问题 2】种子奇偶直接决定抽哪个文件
-------------------------------------
    rng = random.Random(seed)
    rng.shuffle(enabled_files)              # 洗牌结果被扔掉
    selected_file = enabled_files[seed % len(enabled_files)]   # ← 用的是 seed，不是 rng

默认 enabled_files 长度=2 → 所有偶数种子永远抽文件[0]，奇数种子永远抽文件[1]。
种子之间有强相关性，多样性直接砍半。

【问题 3】画师不随种子复现
-------------------------
    anima_weaver.py:410   s = random.randint(1, len(artists))      ← 全局 random
    anima_weaver.py:328   raw_seed = random.randint(...)           ← 全局 random

都没用 seeded rng。同一个种子每次跑出不同画师 —— 「固定种子复现结果」
这个基本承诺是失效的。

【问题 4】每行标签数失控
-------------------------
    min=18  中位=45  max=746

746 个标签的提示词毫无意义（CLIP 77 token 截断后只剩前几个）。
而且 assembly.SLOT_LIMITS 设计好的上限（appearance 最多 8 个等）
**从来没被应用过** —— assemble_prompt() 是死代码，pyflakes 报
'anima_weaver.py:26: assembly.assemble_prompt imported but unused'。
"""

from __future__ import annotations

import random
import re

# ─────────────────────────────────────────────────────────────────
# 1. 元数据 / 垃圾标签黑名单
# ─────────────────────────────────────────────────────────────────
# Danbooru 的非画面内容标签。分两类：
#   META_TAGS     —— 纯元数据，永远该删
#   QUALITY_TAGS  —— 质量标记，也该删（画质由采样器/模型决定，不是 tag 决定的）
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

QUALITY_TAGS = frozenset({
    "masterpiece", "best_quality", "high_quality", "normal_quality",
    "low_quality", "worst_quality", "amazing_quality", "great_quality",
    "very_high_quality", "hd", "8k", "4k",
})

# 默认只删 META_TAGS；QUALITY_TAGS 可选（有人刻意在提示词里放 masterpiece）
DEFAULT_DROP = META_TAGS


def filter_tags(tags: list[str], drop: frozenset[str] = DEFAULT_DROP) -> list[str]:
    """过滤掉元数据标签。用 frozenset 查表，O(n)。"""
    return [t for t in tags if t not in drop]


def filter_tag_string(tag_prompt: str, drop: frozenset[str] = DEFAULT_DROP) -> str:
    """对逗号分隔的标签串做过滤。"""
    parts = [t.strip() for t in tag_prompt.split(",") if t.strip()]
    kept = [t for t in parts if t.lower().replace(" ", "_") not in drop]
    return ", ".join(kept)


# ─────────────────────────────────────────────────────────────────
# 2. 种子派生的确定性 RNG（修复问题 2 / 3）
# ─────────────────────────────────────────────────────────────────
class SeedRNG:
    """
    从主种子派生出互相独立的子随机流。

    现在的写法是「一个 rng 干所有事」，于是：改了标签数量就会连锁改变
    画师的抽取结果，牵一发动全身。分成命名子流后，各部分互不干扰，
    而且每个子流都能单独复现。
    """

    def __init__(self, seed: int):
        self.seed = int(seed)
        self._streams: dict[str, random.Random] = {}

    def stream(self, name: str) -> random.Random:
        """按名字取一个独立的 Random 实例，同 seed + 同 name 必然同结果。"""
        r = self._streams.get(name)
        if r is None:
            # 用 name 做盐，避免不同子流碰撞
            salt = sum((i + 1) * ord(c) for i, c in enumerate(name))
            r = random.Random((self.seed * 0x9E3779B1 + salt) & 0xFFFFFFFFFFFFFFFF)
            self._streams[name] = r
        return r

    def pick_file(self, files: list[str]) -> str:
        """修复问题 2：用 rng 选，而不是 seed % len。"""
        if not files:
            return ""
        if len(files) == 1:
            return files[0]
        return self.stream("file").choice(files)

    def pick_artist(self, n_artists: int, mode: int = -1, fixed: int = 0) -> int:
        """
        修复问题 3：画师也走种子派生流。
        mode: -1 随机 / 0 无画师 / 1 固定
        """
        if mode == 0 or n_artists <= 0:
            return 0
        if mode == -1:
            return self.stream("artist").randint(1, n_artists)
        return max(1, min(int(fixed), n_artists))

    def reroll_seed(self, attempt: int) -> int:
        """重抽用的派生种子：attempt 不同则整条链路都不同。"""
        return (self.seed * 0x85EBCA6B + attempt * 0xC2B2AE35) & 0xFFFFFFFFFFFFFFFF


# ─────────────────────────────────────────────────────────────────
# 3. 标签数量上限（修复问题 4）
# ─────────────────────────────────────────────────────────────────
# SLOT_LIMITS 已经在 assembly.py 里定义好了但没用上，这里直接复用
SLOT_LIMITS = {
    "count_identity": (2, 4),
    "appearance": (3, 8),
    "clothing": (2, 10),
    "pose_action": (2, 8),
    "expression": (1, 4),
    "camera": (1, 5),
    "scene": (2, 6),
    "detail_mood": (1, 3),
}

TOTAL_TAG_CAP = 60          # 整条提示词最多保留多少个标签
PER_SLOT_CAP = 10           # 单个槽位最多多少个


def cap_slots(slot_tags: dict[str, list[str]],
              per_slot: int = PER_SLOT_CAP,
              total: int = TOTAL_TAG_CAP) -> dict[str, list[str]]:
    """
    按槽位截断，两阶段：

      1. 每槽截到 per_slot
      2. 全局截到 total —— **按比例分配**，不是从前往后切

    第二点很重要：从前往后切会让 budget 在前面几个槽就用光，
    导致 scene / detail_mood 永远为空（实测 8 槽 x 200 个时，
    朴素切法下最后两个槽直接归零，而场景恰恰是最不该丢的）。

    按比例切：每个槽分到 total * (该槽数量 / 总数量)，至少保留 1 个
    （只要它原本非空）。全程确定性，不影响复现。
    """
    order = ["count_identity", "appearance", "clothing", "pose_action",
             "expression", "camera", "scene", "detail_mood"]

    out: dict[str, list[str]] = {}
    for k, v in slot_tags.items():
        out[k] = list(v[:per_slot])

    grand = sum(len(v) for v in out.values())
    if grand <= total:
        return out

    # 按比例分配，余数给数量最多的槽
    quota: dict[str, int] = {}
    assigned = 0
    for slot in order:
        n = len(out.get(slot, []))
        if n == 0:
            continue
        q = max(1, round(total * n / grand))
        quota[slot] = q
        assigned += q

    # 分配超了就从大槽往下扣，没分满就补给大槽
    slots_by_size = sorted(quota, key=lambda s: -len(out[s]))
    i = 0
    while assigned != total and slots_by_size:
        s = slots_by_size[i % len(slots_by_size)]
        if assigned > total and quota[s] > 1:
            quota[s] -= 1
            assigned -= 1
        elif assigned < total:
            quota[s] += 1
            assigned += 1
        else:
            break
        i += 1

    return {k: (v[:quota[k]] if k in quota else v) for k, v in out.items()}


# ─────────────────────────────────────────────────────────────────
# 4. 去重只作用于标签部分（现有 bug）
# ─────────────────────────────────────────────────────────────────
# compose() 现在是这样：
#     final, nl_used = self._finish_prompt(...)   # final = 标签 + NL 混合
#     final = self._dedup_final(final)            # ← 对混合体按逗号切分去重
#
# NL 句子里本来就有逗号。_dedup_final 把整句切开当标签去重，
# 一旦有两个片段归一化后相同（比如 "wearing a red dress" 出现两次），
# 句子就会被截断。NL 不该按逗号切。
#
# 正确做法：在 mix_by_ratio 之前，只对 tag_prompt 去重。

_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')


def dedup_tags_only(tag_prompt: str) -> str:
    """只对纯标签串去重。安全，因为此时还没有混入 NL。"""
    seen: set[str] = set()
    out: list[str] = []
    for t in tag_prompt.split(","):
        s = t.strip()
        if not s:
            continue
        key = s.lower().replace(" ", "_").replace("-", "_")
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return ", ".join(out)


# ─────────────────────────────────────────────────────────────────
# 组装：_run_raffle 里该改的地方
# ─────────────────────────────────────────────────────────────────
RUN_RAFFLE_PATCH = '''
# ── 替换 _run_raffle 开头的种子处理 ──
-   seed = int(kwargs.get("随机种子", 0))
-   rng = random.Random(seed)
-   rng.shuffle(enabled_files)
-   selected_file = enabled_files[seed % len(enabled_files)]
+   seed = int(kwargs.get("随机种子", 0))
+   srng = SeedRNG(seed)
+   rng = srng.stream("raffle")            # 抽签用独立子流
+   selected_file = srng.pick_file(enabled_files)   # 不再用 seed % len

# ── 替换选行 ──
-   selected_tags = valid_taglists[seed % len(valid_taglists)]
+   selected_tags = valid_taglists[rng.randrange(len(valid_taglists))]

# ── 分类循环里加垃圾过滤 ──
    for tag in selected_tags:
        tag_clean = tag.strip().lower().replace(" ", "_")
        if not tag_clean:
            continue
        if tag_clean in filter_out:
            continue
+       if tag_clean in META_TAGS:          # ← 新增
+           continue
        category = tag_to_category.get(tag_clean, "")
        ...

# ── 返回前加上限 ──
-   return slot_tags
+   return cap_slots(slot_tags)

# ── _finish_prompt 里的画师 ──
-   if s == -1:
-       s = random.randint(1, len(artists))
+   srng = SeedRNG(kwargs.get("随机种子", 0)) if not kwargs.get("_srng") else kwargs["_srng"]
+   s = srng.pick_artist(len(artists), mode=-1)

# ── compose() 里的去重 ──
-   final, nl_used = self._finish_prompt(...)
-   final = self._dedup_final(final)
+   tag_prompt = dedup_tags_only(tag_prompt)     # 移到 _finish_prompt 之前
+   final, nl_used = self._finish_prompt(...)
+   # 不再对混合体调 _dedup_final
'''
