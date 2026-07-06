"""
Anima Weaver — Conflict Rules Engine

Defines mutually exclusive tag pairs and provides conflict checking
functions for tag prompts.
"""

# ── Conflict pairs ──────────────────────────────────────────────────

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

# ── Body-part grouping for detail overload ─────────────────────────

BODY_PART_TAGS = {
    "eyes": ["eyes", "pupils", "iris", "eyelashes", "eyebrow", "eyelid",
             "heart-shaped pupils", "rolling eyes", "closed eyes",
             "looking at viewer", "looking away", "looking to side",
             "looking down", "looking up", "ahegao"],
    "mouth": ["mouth", "lips", "teeth", "tongue", "open mouth",
              "closed mouth", "smile", "grin", "frown", "pout",
              "clenched teeth", "tongue out", "drool", "saliva",
              "open mouth", "clenched teeth"],
    "hands": ["hands", "fingers", "palm", "fist", "spread fingers",
              "clenched fist", "pointing", "hand on cheek",
              "hand on hip", "hand on head", "hand in hair",
              "hand under chin", "holding hands"],
    "feet": ["feet", "toes", "soles", "barefoot", "spread toes",
             "toe scrunch", "arched foot", "foot focus"],
    "legs": ["legs", "thighs", "knees", "spread legs", "legs together",
             "crossed legs", "one leg up", "leg lift", "thigh gap",
             "wide spread legs", "legs up"],
    "chest": ["breasts", "chest", "bouncing breasts", "breasts squeeze together",
              "cleavage", "nipples", "areolae", "pecs"],
}

# ── Helper utilities ────────────────────────────────────────────────

def _normalise(tag: str) -> str:
    """Normalise a tag to lower-case, underscore-space-normalised form."""
    return tag.strip().lower().replace(" ", "_")


def _normalise_list(tags: list[str]) -> list[str]:
    """Normalise an entire list of tags."""
    return [_normalise(t) for t in tags]


def _find_tag(norm_tag: str, norm_all_tags: list[str]) -> int:
    """
    Find *norm_tag* in *norm_all_tags* (exact match).
    Returns the list index or -1.
    """
    for i, t in enumerate(norm_all_tags):
        if t == norm_tag:
            return i
    return -1


# ── Conflict checking ──────────────────────────────────────────────

def check_conflicts(tags: list[str]) -> list[str]:
    """
    Check a list of raw tag strings for mutually exclusive pairs.

    Parameters
    ----------
    tags : list[str]
        List of raw tag strings (e.g. from splitting a prompt on ',').

    Returns
    -------
    list[str]
        Human-readable conflict descriptions.  Empty list means no conflicts.
    """
    if not tags:
        return []

    norm_tags = _normalise_list(tags)
    conflicts: list[str] = []

    # ── 0. Special: "completely nude" + clothing tags ──────────────
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

    # ── 1. Static conflict pairs ───────────────────────────────────
    for tag_a, tag_b in CONFLICT_PAIRS:
        norm_a = _normalise(tag_a)
        norm_b = _normalise(tag_b)

        idx_a = _find_tag(norm_a, norm_tags)
        idx_b = _find_tag(norm_b, norm_tags)

        if idx_a >= 0 and idx_b >= 0:
            conflicts.append(
                f"'{tags[idx_a]}' conflicts with '{tags[idx_b]}'"
            )

    return conflicts


# ── Detail-overload checking ───────────────────────────────────────

def check_detail_overload(tags: list[str], max_per_body_part: int = 2) -> list[str]:
    """
    Check whether the same body part has too many detail tags.

    Parameters
    ----------
    tags : list[str]
        Raw tag strings.
    max_per_body_part : int
        Maximum number of tags allowed per body-part group.

    Returns
    -------
    list[str]
        Warning messages (e.g. "eyes: 3 tags (>2)").
    """
    if not tags:
        return []

    norm_tags = _normalise_list(tags)
    warnings: list[str] = []

    for part, part_keywords in BODY_PART_TAGS.items():
        part_norm_keywords = _normalise_list(part_keywords)
        count = 0
        found: list[str] = []

        for norm_t in norm_tags:
            if norm_t in part_norm_keywords:
                count += 1
                found.append(norm_t)

        if count > max_per_body_part:
            warnings.append(
                f"{part}: {count} tags (>{max_per_body_part}): {', '.join(found)}"
            )

    return warnings
