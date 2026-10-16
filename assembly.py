"""
Anima Weaver — Prompt Assembler

只保留主节点实际用到的两样（anima_weaver.py）：
  - SLOT_ORDER    槽位顺序
  - mix_by_ratio  按标签/自然语言比例混合

死代码 assemble_prompt / _check_slot_limits / _count_tags / SLOT_LIMITS
已删除（全仓无调用点，见四节点精简方案 P5）。
"""

from __future__ import annotations

# ── Slot constants ─────────────────────────────────────────────────

SLOT_ORDER = [
    "count_identity",
    "appearance",
    "clothing",
    "pose_action",
    "expression",
    "camera",
    "scene",
    "detail_mood",
]

# ── Helper: mix by ratio ───────────────────────────────────────────

def mix_by_ratio(tag_part: str, nl_part: str, ratio: float) -> str:
    """
    Mix tag and natural-language parts according to *ratio*.

    Parameters
    ----------
    tag_part : str
        The pure-tag portion of the prompt.
    nl_part : str
        The natural-language portion.
    ratio : float
        0.0 → pure NL, 1.0 → pure tags.

    Returns
    -------
    str
        The mixed prompt.
    """
    tag_len = len(tag_part)
    nl_len = len(nl_part)

    # Edge cases
    if ratio >= 1.0 or nl_len == 0:
        return tag_part
    if ratio <= 0.0 or tag_len == 0:
        return nl_part

    # Both parts have content — scale
    # total = max(len(tag), len(nl)) / min(ratio, 1-ratio)
    min_ratio = min(ratio, 1.0 - ratio)
    if min_ratio == 0.0:
        # Shouldn't happen after the edge guards above, but be safe
        return f"{tag_part}, {nl_part}" if tag_part and nl_part else tag_part or nl_part

    total = max(tag_len, nl_len) / min_ratio
    tag_max = int(total * ratio)
    nl_max = int(total * (1.0 - ratio))

    # Truncate each part to its budget
    truncated_tag = tag_part[:tag_max].rstrip(",").rstrip()
    truncated_nl = nl_part[:nl_max].rstrip(",").rstrip()

    # Assemble
    if truncated_tag and truncated_nl:
        return f"{truncated_tag}, {truncated_nl}"
    return truncated_tag or truncated_nl
