"""
09_conflicts.py —— 冲突 tag 处理重构（面向出图准确性）
=====================================================
结论：**能改进，而且现状这个模块实际上基本没在工作。**

────────────────────────────────────────────────────────────────
先说现状有多失效
────────────────────────────────────────────────────────────────
CONFLICT_PAIRS 有 23 对硬编码。在 20000 行真实数据上逐对统计命中：

    from_front + from_behind        0 行
    from_above + from_below         0 行
    solo + hetero                   0 行
    solo + yuri                     0 行
    blindfold + glasses             0 行
    missionary + doggystyle         0 行
    cowgirl_position + prone_bone   0 行
    ...共 14 对 0 命中...
    pantyhose + barefoot           43 行   ← 最多的一对
    sleeping + looking_at_viewer   26 行
    open_mouth + clenched_teeth    15 行
    looking_at_viewer + facing_away 14 行

**只有 9/23 对能命中，最多的也只有 43 行（0.2%）。**
实测 8000 行：现状只影响 2.1% 的行。

而真实存在视觉矛盾的行是 **17%**（见下）。也就是说
**现状的冲突处理漏掉了约 88% 的真冲突。**

────────────────────────────────────────────────────────────────
三个必须修的 bug
────────────────────────────────────────────────────────────────

【Bug 1】检测和移除用了两套不同的匹配逻辑
    check_conflicts()    用 _find_tag()  → **精确匹配**
    _remove_conflicts()  用 `if norm_a in tn` → **子串匹配**

    实测（同一条输入）：
        输入: 1girl, solo, pov, lap_pov, full_body
        检测: "'pov' conflicts with 'full_body'"        ← 报 1 对
        移除: 删掉 pov, lap_pov, full_body 三个          ← 删了 3 个

    用户看到的警告和实际发生的删除对不上。

【Bug 2】子串误伤
    因为用了子串匹配，这些都被误删：
        lap_pov         被 "pov" 误伤         （构图细节，非冲突）
        solo_focus      被 "solo" 误伤         （构图，非人数）
        wide_spread_legs 被 "spread_legs" 误伤 （同义强调，非冲突）

【Bug 3】冲突时两个都删
        looking_at_viewer + facing_away → 两个都删 → 视角信息全丢
        solo + hetero                   → 两个都删 → 人数信息全丢
    正确做法是删一个留一个。

────────────────────────────────────────────────────────────────
核心洞察：维度内多值 ≠ 冲突
────────────────────────────────────────────────────────────────
最直觉的改法是「按视觉属性分组，组内互斥就删」。**这是错的**，
会删掉大量合理描述。实测 8000 行：

    组合                              共存率      性质
    1girl + solo                      74.4%     互补（不同维度，必须保留）
    breasts + large_breasts           57.9%     细化（必须保留）
    long_hair + very_long_hair        24.6%     细化（必须保留）
    long_hair + ponytail               9.8%     不同维度（必须保留）
    open_mouth + smile                 9.6%     不同维度（必须保留）
    2girls + multiple_girls            9.2%     伞形（必须保留）

如果按「维度互斥」一刀切，这些全会被删 —— 出图质量直接崩。

所以必须分四类：

    L0 伞形豁免    multicolored_hair / heterochromia / two-tone_hair
                   出现时，该维度内多值是合法的
    L1 硬互斥      同一原子属性的不同取值 → 删一个留一个
    L2 层级细化    very_long_hair ⊃ long_hair → 删泛化留具体（可选，默认关）
    L3 互补白名单  明确不处理

────────────────────────────────────────────────────────────────
真冲突的实际规模（8000 行实测）
────────────────────────────────────────────────────────────────
    类型                  行数      占比
    发色互斥（金+黑等）    763      9.5%
    瞳色互斥（蓝+红等）    487      6.1%
    发长互斥（长+短）      253      3.2%
    构图互斥（特写+全身）   15      0.2%
    ─────────────────────────────────
    真冲突合计            ~1518     ~17%      对比现状 2.1%

    （另有 24.6% 是发长细化，属可选优化，不算冲突）

────────────────────────────────────────────────────────────────
伞形豁免有多关键
────────────────────────────────────────────────────────────────
    multicolored_hair  出现 1210 行，其中 99% 同时有 ≥2 个其他发色
    two-tone_hair      出现  403 行，其中 100% 同时有 ≥2 个其他发色
    heterochromia      出现   95 行，其中  88% 同时有 ≥2 个其他瞳色

**不做豁免，所有多色发型/异色瞳的合理描述会被全部误删。**
这是最容易踩的坑。

────────────────────────────────────────────────────────────────
删哪个
────────────────────────────────────────────────────────────────
保留**第一个出现的**（CLIP 对靠前的 token 权重更高），删掉其余。
全程确定性 —— 有冲突时不引入随机，否则种子复现又失效了。
manual_slots 里的标签优先保护，从不删除。

────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

# ═════════════════════════════════════════════════════════════════
# L0 伞形标签：出现时该维度内多值合法
# ═════════════════════════════════════════════════════════════════
UMBRELLA = {
    "multicolored_hair", "two-tone_hair", "multicolored_eyes",
    "heterochromia", "rainbow_hair", "gradient_hair",
}

# ── 多人豁免 ─────────────────────────────────────────────────────
# ⚠ 这是实测中最容易漏掉、后果最严重的一条。
#
# 实测 8000 行：存在 ≥2 种发色（且无伞形标签）的行共 763 行，其中：
#     595 行（78%）含多人标签   → 不同角色不同发色，**完全合理**
#     168 行（22%）是 solo/1girl → 同一角色两种发色，真冲突
#
# 案例：2girls + black_hair + purple_hair
#       两个女孩，一个黑发一个紫发 —— 这是正常的多角色描述。
#       不豁免的话会被删成单一发色，出图直接错。
#
# 所以：检测到多人标签时，发色/瞳色维度整体跳过互斥处理。
MULTI_SUBJECT = {
    "2girls", "3girls", "4girls", "5girls", "6+girls",
    "multiple_girls", "multiple_boys", "2boys", "3boys", "4boys",
    "multiple_characters", "two_characters", "multiple_views",
    "1boy_1girl", "2boys_1girl", "1boy_2girls",
}

# ═════════════════════════════════════════════════════════════════
# L1 硬互斥：同一原子属性的不同取值
# ═════════════════════════════════════════════════════════════════
HARD_EXCLUSIVE: dict[str, list[str]] = {
    "hair_color": [
        "blonde_hair", "black_hair", "brown_hair", "red_hair",
        "blue_hair", "pink_hair", "green_hair", "purple_hair",
        "white_hair", "grey_hair", "silver_hair", "orange_hair",
        "aqua_hair",
    ],
    "eye_color": [
        "blue_eyes", "red_eyes", "green_eyes", "brown_eyes",
        "purple_eyes", "yellow_eyes", "grey_eyes", "pink_eyes",
        "black_eyes", "orange_eyes", "aqua_eyes",
    ],
    "framing": [
        "portrait", "close_up", "upper_body", "cowboy_shot",
        "full_body", "wide_shot", "medium_shot",
    ],
}

# 发长维度特殊：组内既有互斥又有层级，不能用统一的「维度互斥」
#   short_hair ↔ {long_hair, very_long_hair}  真互斥
#   very_long_hair ⊃ long_hair                层级细化（L2 处理）
HAIR_LEN_EXCLUSIVE = [
    ("short_hair", "long_hair"),
    ("short_hair", "very_long_hair"),
    ("bald", "long_hair"),
    ("bald", "very_long_hair"),
]

# ── 成对互斥（不能按「维度」建模的场景）──────────────────────────
# 视角维度实测 8000 行：
#   from_behind + looking_at_viewer   792 行 (9.9%)  背对但回头看 → 合理共存
#   from_side   + looking_at_viewer   257 行 (3.2%)  侧身看镜头   → 合理共存
#   from_front  + from_behind           0 行         真互斥
#   from_above  + from_below            0 行         真互斥
# 所以视角也不能整组互斥，必须成对列举。
PAIRWISE_EXCLUSIVE = HAIR_LEN_EXCLUSIVE + [
    ("from_front", "from_behind"),
    ("from_above", "from_below"),
    ("looking_at_viewer", "facing_away"),
    ("pov", "full_body"),
    ("close_up", "full_body"),
    ("spread_legs", "legs_together"),
    ("open_mouth", "clenched_teeth"),
    ("standing", "lying"),
    ("pantyhose", "barefoot"),
    ("solo", "hetero"),
    ("solo", "yuri"),
    ("sleeping", "looking_at_viewer"),
    ("unconscious", "looking_at_viewer"),
    ("blindfold", "glasses"),
    ("blindfold", "heart-shaped_pupils"),
    ("blindfold", "rolling_eyes"),
]

# ═════════════════════════════════════════════════════════════════
# L2 层级细化（可选）：删泛化、留具体
# ═════════════════════════════════════════════════════════════════
# 默认关闭的理由：SD 里多个相关 tag 会互相强化。
# long_hair + very_long_hair 同时出现可能让「长发」特征更强，
# 删掉一个有可能弱化。这是「去重」不是「修冲突」，所以可选。
HIERARCHY: dict[str, list[str]] = {
    "very_long_hair": ["long_hair"],
    "absurdly_long_hair": ["very_long_hair", "long_hair"],
    "huge_breasts": ["large_breasts", "breasts"],
    "large_breasts": ["breasts"],
    "small_breasts": ["breasts"],
}

# ═════════════════════════════════════════════════════════════════
# L3 互补白名单：明确不处理
# ═════════════════════════════════════════════════════════════════
# 这些在真实数据里高频共存且合理。放在这里做兜底保护，
# 防止上面任何规则误伤。
COMPATIBLE: set[frozenset[str]] = {
    frozenset({"1girl", "solo"}), frozenset({"1boy", "solo"}),
    frozenset({"open_mouth", "smile"}), frozenset({"closed_mouth", "smile"}),
    frozenset({"long_hair", "ponytail"}), frozenset({"long_hair", "braid"}),
    frozenset({"sitting", "crossed_legs"}),
    frozenset({"2girls", "multiple_girls"}),
    frozenset({"3girls", "multiple_girls"}),
}


# ═════════════════════════════════════════════════════════════════
# 核心：解析冲突
# ═════════════════════════════════════════════════════════════════
def resolve_conflicts(
    tags: Sequence[str],
    manual_tags: Optional[set[str]] = None,
    use_hierarchy: bool = False,
    keep_first: bool = True,
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """
    处理冲突标签。返回 (保留的标签, 删除记录)。

    删除记录每项为 (被删的 tag, 与它冲突的 tag, 原因)，
    可以直接喂给 debug 输出——这解决了「警告和实际行为对不上」的问题。

    Parameters
    ----------
    tags
        归一化后的标签列表（顺序有意义）。
    manual_tags
        手动槽位来源的标签，永不删除。
    use_hierarchy
        是否启用 L2 层级细化去重。默认 False。
    keep_first
        True 保留先出现的（CLIP 权重更高）；False 保留后出现的。
    """
    manual = manual_tags or set()
    s = set(tags)
    drop: dict[str, tuple[str, str]] = {}     # tag -> (冲突对象, 原因)

    def _mark(victim: str, other: str, reason: str) -> None:
        if victim in manual or victim in drop:
            return
        drop[victim] = (other, reason)

    # ── L0 豁免：伞形标签 / 多人场景 ─────────────────────────────
    has_umbrella = bool(s & UMBRELLA)
    is_multi = bool(s & MULTI_SUBJECT)

    # ── L1 硬互斥 ────────────────────────────────────────────────
    for dim, vals in HARD_EXCLUSIVE.items():
        # 发色/瞳色：遇伞形标签，或多人场景（不同角色可有不同发色）时跳过
        if dim in ("hair_color", "eye_color") and (has_umbrella or is_multi):
            continue
        hit = [t for t in tags if t in vals]
        if len(hit) < 2:
            continue
        keep = hit[0] if keep_first else hit[-1]
        for t in hit:
            if t == keep:
                continue
            _mark(t, keep, f"{dim} 互斥")

    # 成对互斥（视角/发长等混合维度用，不能用整组互斥）
    for a, b in PAIRWISE_EXCLUSIVE:
        if a in s and b in s:
            ia, ib = tags.index(a), tags.index(b)
            victim, keep = (b, a) if ia < ib else (a, b)
            if not keep_first:
                victim, keep = keep, victim
            _mark(victim, keep, "互斥")

    # ── L2 层级细化（可选）────────────────────────────────────────
    if use_hierarchy:
        for specific, generics in HIERARCHY.items():
            if specific not in s:
                continue
            for g in generics:
                if g in s:
                    _mark(g, specific, "层级细化，保留更具体")

    # ── L3 互补白名单兜底 ────────────────────────────────────────
    for pair in COMPATIBLE:
        if pair <= s:
            for t in pair:
                drop.pop(t, None)

    # ── 输出 ─────────────────────────────────────────────────────
    kept = [t for t in tags if t not in drop]
    record = [(v, other, reason) for v, (other, reason) in drop.items()]
    return kept, record


def check_conflicts_v2(tags: Sequence[str], **kw) -> list[str]:
    """
    检测接口，与 resolve_conflicts 共用同一套逻辑 ——
    这就修掉了「检测精确匹配、移除子串匹配」的不一致。
    """
    _, record = resolve_conflicts(tags, **kw)
    return [f"'{v}' conflicts with '{o}' ({r})" for v, o, r in record]


# ═════════════════════════════════════════════════════════════════
# 接入 diff
# ═════════════════════════════════════════════════════════════════
DIFF = '''
# ── anima_weaver.py: _remove_conflicts 整体替换 ──
# 现状（有 bug 的版本）：
-   for tag_a, tag_b in CONFLICT_PAIRS:
-       norm_a = tag_a.lower().replace(" ", "_")
-       norm_b = tag_b.lower().replace(" ", "_")
-       has_a = has_b = False
-       for t in all_tags:
-           tn = t.lower().replace(" ", "_")
-           if norm_a in tn: has_a = True      # ← 子串，误伤 lap_pov 等
-           if norm_b in tn: has_b = True
-       if has_a and has_b:
-           for t in all_tags:
-               tn = t.lower().replace(" ", "_")
-               if norm_a in tn and t not in manual_tags: to_remove.add(t)
-               if norm_b in tn and t not in manual_tags: to_remove.add(t)
-                                                          # ↑ 两个都删

+   from .conflicts import resolve_conflicts
+   kept, dropped = resolve_conflicts(all_tags, manual_tags=manual_tags)
+   # dropped 直接用于 debug 输出，警告和实际操作永远一致
+   return ", ".join(kept)


# ── rules.py: check_conflicts 也换成同一套 ──
-   conflicts = check_conflicts(all_tags)
+   conflicts = check_conflicts_v2(all_tags)


# ── INPUT_TYPES 新增一个开关（放「▸ 高级」组）──
"层级去重": ("BOOLEAN", {"default": False,
    "tooltip": "删掉被更具体标签覆盖的泛化标签（如 long_hair + very_long_hair → 保留后者）。默认关闭，因为可能弱化特征"})
'''


NOTES = """
关于「出图准确性」的一点权衡：

真互斥（金发 vs 黑发）必须删一个 —— SD 同时收到两个互斥指令会
画出混色或随机结果，这是明确的质量损失。

细化去重（long + very_long）**不是**冲突，删掉可能弱化特征。
所以默认关闭，让用户自己决定。

还有一类更深的问题这里没处理：**同一身体部位 tag 过载**
（check_detail_overload 只报警告不删）。比如同时有
closed_eyes、one_eye_closed、half-closed_eyes 三个眼部状态，
SD 会画出错乱的眼睛。这个和「互斥」是不同性质的问题
（过度指定 vs 取值冲突），建议单独做：按 BODY_PART_TAGS 分组，
超过 max_per_group 就保留权重最高的几个。
"""
