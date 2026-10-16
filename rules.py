"""
Anima Weaver — Conflict Rules Engine

Defines mutually exclusive tag pairs and provides conflict checking
functions for tag prompts.

分层冲突模型（面向出图准确性）：
  旧版硬编码冲突对 + 检测/移除两套匹配逻辑不一致，
  实测只覆盖 2.1% 的行且误伤互补组合 88 次。
  新版分层模型：
    L0 豁免     伞形标签（multicolored_hair / heterochromia...）
                多人标签（2girls / multiple_girls...）
                -> 发色/瞳色维度整体跳过
    L1 硬互斥   发色 / 瞳色 / 构图（整组互斥）
                视角 / 发长（成对列举，因为组内混合了互斥与互补）
    L2 层级细化 very_long_hair ⊃ long_hair（可选，默认关）
    L3 互补白名单 明确不处理
  冲突时删一个保留首个出现者（CLIP 对靠前 token 权重更高），
  全程确定性 —— 有冲突时不引入随机，否则种子复现又失效。
  检测（check_conflicts）与移除（resolve_conflicts）共用同一套逻辑，
  修掉「警告和实际删除对不上」的不一致。
"""

# ── Conflict pairs（保留旧符号：assembly.py 仍 import）──────────────
# 旧 23 对已全部并入下方 PAIRWISE_EXCLUSIVE（归一化后），此表仅保留
# 符号兼容，新逻辑不再直接遍历它。

CONFLICT_PAIRS = [
    # 视角互斥 (Camera/Perspective)
    ("from front", "from behind"),
    ("from above", "from below"),
    ("looking at viewer", "facing away"),
    ("pov", "full body"),
    ("close-up", "full body"),

    # 身份互斥 (Identity)
    ("solo", "hetero"),
    ("solo", "yuri"),
    ("sleeping", "looking at viewer"),
    ("unconscious", "looking at viewer"),
    ("blindfold", "heart-shaped pupils"),
    ("blindfold", "rolling eyes"),

    # 服装互斥 (Clothing)
    ("pantyhose", "barefoot"),
    ("blindfold", "glasses"),

    # 动作互斥 (Action/Pose)
    ("standing sex", "lying"),
    ("standing sex", "on back"),
    ("missionary", "doggystyle"),
    ("cowgirl position", "prone bone"),

    # 细节过度 (Detail overload)
    ("spread toes", "toe scrunch"),
    ("spread fingers", "clenched fist"),
    ("bouncing breasts", "breasts squeeze together"),
    ("open mouth", "clenched teeth"),
    ("rolling eyes", "looking at viewer"),
    ("spread legs", "legs together"),
]

# ── Clothing keywords for "completely nude" check ──────────────────

CLOTHING_KEYWORDS = frozenset(
    word.lower().replace(" ", "_")
    for word in [
        "shirt", "tshirt", "t-shirt", "blouse", "top", "crop top", "tank top",
        "dress", "skirt", "shorts", "pants", "jeans", "trousers", "leggings",
        "jacket", "coat", "hoodie", "sweater", "cardigan", "vest",
        "underwear", "bra", "panties", "boxers", "briefs", "lingerie",
        "socks", "stockings", "tights", "pantyhose", "thighhighs",
        "shoes", "boots", "sandals", "sneakers", "heels",
        "hat", "cap", "headband", "hairband", "bow", "ribbon", "glasses",
        "gloves", "belt", "scarf", "tie", "bowtie", "watch", "necklace",
        "earrings", "ring", "bracelet", "choker", "collar",
        "uniform", "suit", "kimono", "yukata", "robe", "coat",
        "mask", "blindfold", "eyepatch", "veil",
        "pajamas", "nightgown", "bikini", "swimsuit", "swimwear",
        "apron", "overalls", "jumpsuit", "bodysuit", "catsuit",
        "armor", "cape", "cloak", "poncho", "shawl",
        "sash", "belt", "suspenders", "garter", "lace",
        "sleeves", "wristband", "armband", "wristwatch",
    ]
)


# ═════════════════════════════════════════════════════════════════
# 分层冲突模型
# ═════════════════════════════════════════════════════════════════

# ── L0 伞形标签：出现时该维度内多值合法 ────────────────────────────
# 实测：multicolored_hair 出现 1210 行，其中 99% 同时有 ≥2 个其他发色；
# two-tone_hair 403 行 100%；heterochromia 95 行 88%。
# 不豁免，所有多色发型/异色瞳的合理描述会被全部误删。
UMBRELLA = {
    "multicolored_hair", "two-tone_hair", "multicolored_eyes",
    "heterochromia", "rainbow_hair", "gradient_hair",
}

# ── L0 多人豁免 ───────────────────────────────────────────────────
# ⚠ 实测中最容易漏掉、后果最严重的一条。
# 实测 8000 行：存在 ≥2 种发色（且无伞形标签）的行共 763 行，其中
# 595 行（78%）含多人标签 -> 不同角色不同发色，**完全合理**；
# 168 行（22%）是 solo/1girl -> 同一角色两种发色，真冲突。
# 案例：2girls + black_hair + purple_hair —— 两个女孩一个黑发一个紫发，
# 不豁免会被删成单一发色，出图直接错。
MULTI_SUBJECT = {
    "2girls", "3girls", "4girls", "5girls", "6+girls",
    "multiple_girls", "multiple_boys", "2boys", "3boys", "4boys",
    "multiple_characters", "two_characters", "multiple_views",
    "1boy_1girl", "2boys_1girl", "1boy_2girls",
}

# ── L1 硬互斥：同一原子属性的不同取值（整组互斥）──────────────────
HARD_EXCLUSIVE = {
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
#   from_behind + looking_at_viewer   792 行 (9.9%)  背对但回头看 -> 合理共存
#   from_side   + looking_at_viewer   257 行 (3.2%)  侧身看镜头   -> 合理共存
#   from_front  + from_behind           0 行         真互斥
#   from_above  + from_below            0 行         真互斥
# 所以视角也不能整组互斥，必须成对列举。
# 列表 = 09 号补丁的成对互斥 + 旧 CONFLICT_PAIRS 中尚未覆盖的对
# （只增不删，保证旧 23 对全部保留）。
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
    # ── 旧 CONFLICT_PAIRS 覆盖补充（旧 23 对中尚未覆盖的）──
    ("standing_sex", "lying"),
    ("standing_sex", "on_back"),
    ("missionary", "doggystyle"),
    ("cowgirl_position", "prone_bone"),
    ("spread_toes", "toe_scrunch"),
    ("spread_fingers", "clenched_fist"),
    ("bouncing_breasts", "breasts_squeeze_together"),
    ("rolling_eyes", "looking_at_viewer"),
]

# ═════════════════════════════════════════════════════════════════
# L2 层级细化（可选）：删泛化、留具体
# ═════════════════════════════════════════════════════════════════
# 默认关闭的理由：SD 里多个相关 tag 会互相强化。
# long_hair + very_long_hair 同时出现可能让「长发」特征更强，
# 删掉一个有可能弱化。这是「去重」不是「修冲突」，所以可选。
HIERARCHY = {
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
COMPATIBLE = {
    frozenset({"1girl", "solo"}), frozenset({"1boy", "solo"}),
    frozenset({"open_mouth", "smile"}), frozenset({"closed_mouth", "smile"}),
    frozenset({"long_hair", "ponytail"}), frozenset({"long_hair", "braid"}),
    frozenset({"sitting", "crossed_legs"}),
    frozenset({"2girls", "multiple_girls"}),
    frozenset({"3girls", "multiple_girls"}),
}


# ── Helper utilities ────────────────────────────────────────────────

def _normalise(tag: str) -> str:
    """Normalise a tag to lower-case, underscore-space-normalised form."""
    return tag.strip().lower().replace(" ", "_")


def _normalise_list(tags: list) -> list:
    """Normalise an entire list of tags."""
    return [_normalise(t) for t in tags]


def _find_tag(norm_tag: str, norm_all_tags: list) -> int:
    """
    Find *norm_tag* in *norm_all_tags* (exact match).
    Returns the list index or -1.
    """
    for i, t in enumerate(norm_all_tags):
        if t == norm_tag:
            return i
    return -1


# ═════════════════════════════════════════════════════════════════
# 核心：解析冲突（检测与移除共用 —— 修掉两套逻辑不一致）
# ═════════════════════════════════════════════════════════════════
def resolve_conflicts(
    tags: list,
    manual_tags: set = None,
    use_hierarchy: bool = False,
    keep_first: bool = True,
) -> tuple:
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
    drop: dict = {}     # tag -> (冲突对象, 原因)

    def _mark(victim: str, other: str, reason: str) -> None:
        if victim in manual or victim in drop:
            return
        drop[victim] = (other, reason)

    # ── L0 豁免：伞形标签 / 多人场景 ─────────────────────────────
    has_umbrella = bool(s & UMBRELLA)
    # L0 多人豁免：除了 2girls/1boy_1girl 这类「单标签即多人」，
    # 「1boy」+「1girl」两个独立标签同时出现同样是多人（实测 taglists 行
    # 里两人组合就是分开写的两个 tag），不同角色不同发色/瞳色完全合理。
    is_multi = bool(s & MULTI_SUBJECT) or ("1boy" in s and "1girl" in s)

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


def check_conflicts_v2(tags: list, **kw) -> list:
    """
    检测接口，与 resolve_conflicts 共用同一套逻辑 ——
    这就修掉了「检测精确匹配、移除子串匹配」的不一致。
    """
    _, record = resolve_conflicts(tags, **kw)
    return [f"'{v}' conflicts with '{o}' ({r})" for v, o, r in record]


# ── Conflict checking ──────────────────────────────────────────────

def check_conflicts(tags: list, manual_tags: set = None,
                    use_hierarchy: bool = False) -> list:
    """
    Check a list of raw tag strings for mutually exclusive pairs.

    与 resolve_conflicts 共用同一套分层逻辑（检测与移除不再分叉：
    旧版检测用精确匹配、移除用子串匹配，存在误伤且警告与
    实际删除对不上）。

    Parameters
    ----------
    tags : list[str]
        List of raw tag strings (e.g. from splitting a prompt on ',').
    manual_tags : set | None
        手动槽位标签（永不删除，仅影响移除侧；检测侧照常报告）。
    use_hierarchy : bool
        是否启用 L2 层级细化（默认关）。

    Returns
    -------
    list[str]
        Human-readable conflict descriptions.  Empty list means no conflicts.
    """
    if not tags:
        return []

    norm_tags = _normalise_list(tags)
    conflicts: list = []

    # ── 0. Special: "completely nude" + clothing tags（保留旧逻辑，精确匹配）──
    nude_variants = ["completely nude", "completely_nude", "nude", "fully nude", "fully_nude"]
    has_nude = any(
        _find_tag(nv, norm_tags) >= 0 for nv in nude_variants
    )
    if has_nude:
        for tag in norm_tags:
            if tag in CLOTHING_KEYWORDS:
                # Find the original form in *tags* (not normalised)
                original_idx = _find_tag(tag, norm_tags)
                if original_idx >= 0:
                    conflicts.append(
                        f"'{tags[original_idx]}' conflicts with 'completely nude'"
                    )

    # ── 1. 分层冲突模型（与移除共用同一逻辑）────────────────────
    _, record = resolve_conflicts(
        norm_tags, manual_tags=manual_tags, use_hierarchy=use_hierarchy
    )
    conflicts.extend(f"'{v}' conflicts with '{o}' ({r})" for v, o, r in record)

    return conflicts

