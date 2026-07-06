"""
Anima Weaver — Prompt Assembler

Merges slot tags with natural language according to a ratio and
produces a final prompt string with debug info.
"""

from __future__ import annotations

from typing import Optional

try:
    from .rules import check_conflicts, check_detail_overload, CONFLICT_PAIRS
except ImportError:
    from rules import check_conflicts, check_detail_overload, CONFLICT_PAIRS

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


def _count_tags(text: str) -> int:
    """Count comma-separated tags in a string."""
    return len([t for t in text.split(",") if t.strip()])


def _check_slot_limits(
    slot_tags: dict[str, str],
) -> dict[str, str]:
    """
    Return a dict of slot -> warning message for slots that exceed
    or fall below their limits.
    """
    warnings: dict[str, str] = {}
    for slot, limit_range in SLOT_LIMITS.items():
        raw = slot_tags.get(slot, "").strip()
        n = _count_tags(raw)
        lo, hi = limit_range
        issues: list[str] = []
        if n < lo:
            issues.append(f"{n} tags (< min {lo})")
        if n > hi:
            issues.append(f"{n} tags (> max {hi})")
        if issues:
            warnings[slot] = f"{slot}: {'; '.join(issues)}"
    return warnings


# ── Main assemble function ─────────────────────────────────────────

def assemble_prompt(
    slot_tags: dict[str, str],
    natural_language: str = "",
    tag_ratio: float = 0.6,
    slot_order: Optional[list[str]] = None,
    conflict_check: bool = True,
) -> tuple[str, str]:
    """
    Build a final prompt string from slot tags and optional NL.

    Parameters
    ----------
    slot_tags : dict[str, str]
        Mapping: slot_name -> "tag1, tag2, ..."
    natural_language : str
        Free-form natural language description.
    tag_ratio : float
        0.0 = pure NL, 1.0 = pure tags.
    slot_order : list[str] | None
        Override slot ordering (default: SLOT_ORDER).
    conflict_check : bool
        Whether to run conflict detection (default True).

    Returns
    -------
    (final_prompt, debug_info)
        *final_prompt* is the assembled string ready for the sampler.
        *debug_info* is a newline-separated string with diagnostic data.
    """
    order = slot_order or SLOT_ORDER
    debug_parts: list[str] = []

    # ── 1. Assemble tag part ──────────────────────────────────────
    tag_segments: list[str] = []
    for slot in order:
        val = slot_tags.get(slot, "").strip()
        if val:
            tag_segments.append(val)
    tag_part = ", ".join(tag_segments)

    # Clean up leading/trailing whitespace and double commas
    import re as _re
    tag_part = _re.sub(r" ,", ",", tag_part)
    tag_part = _re.sub(r",,", ",", tag_part)
    tag_part = tag_part.strip().strip(",").strip()

    # ── 2. Calculate stats ────────────────────────────────────────
    tag_len = len(tag_part)
    nl_len = len(natural_language)
    total = tag_len + nl_len if (tag_len + nl_len) > 0 else 1
    tag_pct = 100.0 * tag_len / total
    nl_pct = 100.0 * nl_len / total

    debug_parts.append(f"Tag ratio: {tag_ratio}")
    debug_parts.append(f"Tags: {tag_len} chars ({tag_pct:.1f}%)")
    debug_parts.append(f"  tag count: {_count_tags(tag_part)}")
    debug_parts.append(f"NL:   {nl_len} chars ({nl_pct:.1f}%)")

    # ── 3. Conflict check ─────────────────────────────────────────
    if conflict_check and tag_part.strip():
        all_tags = [t.strip() for t in tag_part.split(",") if t.strip()]
        conflicts = check_conflicts(all_tags)
        if conflicts:
            debug_parts.append("⚠ Conflicts: " + "; ".join(conflicts))
        else:
            debug_parts.append("✓ No conflicts found")

        overloads = check_detail_overload(all_tags)
        if overloads:
            debug_parts.append("⚠ Detail overload: " + "; ".join(overloads))

    # ── 4. Slot-limit check ───────────────────────────────────────
    limit_warnings = _check_slot_limits(slot_tags)
    for _slot, msg in limit_warnings.items():
        debug_parts.append(f"⚠ Slot limit: {msg}")
    if not limit_warnings:
        # Still mention it
        pass

    # ── 5. Mix by ratio ───────────────────────────────────────────
    final_prompt = mix_by_ratio(tag_part, natural_language, tag_ratio)

    # ── 6. Final cleanup ─────────────────────────────────────────
    final_prompt = _re.sub(r" ,", ",", final_prompt)
    final_prompt = _re.sub(r",,", ",", final_prompt)
    final_prompt = final_prompt.strip().strip(",").strip()

    debug_info = "\n".join(debug_parts)
    return final_prompt, debug_info
