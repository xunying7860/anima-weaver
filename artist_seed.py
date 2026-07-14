"""
Anima Weaver — Artist Seed Node
-1 = 随机画师, 0 = 无画师, 1~max = 固定画师.
Optional 种子串 input for batch mode.
"""

from __future__ import annotations

import os
import random
from typing import Any

_ARTIST_COUNT = 0
_ARTIST_CACHE: dict[int, str] = {}


def _get_artist_count() -> int:
    global _ARTIST_COUNT
    if _ARTIST_COUNT > 0:
        return _ARTIST_COUNT
    path = os.path.join(os.path.dirname(__file__), "tags", "Anima2B_Artist_Index_59k.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            count = 0
            for line in f:
                if line.strip().startswith("@"):
                    count += 1
        _ARTIST_COUNT = count
        return count
    except Exception:
        return 59676


def _get_artist_name(idx: int) -> str:
    if idx in _ARTIST_CACHE:
        return _ARTIST_CACHE[idx]
    path = os.path.join(os.path.dirname(__file__), "tags", "Anima2B_Artist_Index_59k.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            ct = 0
            for line in f:
                line = line.strip()
                if line.startswith("@"):
                    ct += 1
                    if ct == idx:
                        _ARTIST_CACHE[idx] = line
                        return line
    except Exception:
        pass
    return f"#{idx}"


class ArtistSeed:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        max_a = _get_artist_count()
        return {
            "required": {
                "artist_seed": (
                    "INT",
                    {"default": 0, "min": -1, "max": max_a, "step": 1,
                     "tooltip": "-1=随机画师, 0=无画师, 1~59676=固定画师序号"},
                ),
            },
            "optional": {
                "种子串": ("STRING", {"forceInput": True, "multiline": True,
                                      "tooltip": "接入批量种子串，每行一个种子（单次模式下无效）"}),
            },
        }

    RETURN_TYPES = ("INT", "STRING", "STRING")
    RETURN_NAMES = ("artist_seed", "状态", "画师串")
    FUNCTION = "pick"
    CATEGORY = "Anima Weaver / Seed"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs) -> float:
        return random.random()

    def _pick_one(self, artist_seed: int) -> tuple[int, str, str]:
        """Single artist selection: returns (index, status_line, single_line)."""
        max_a = _get_artist_count()
        if artist_seed == 0:
            # 无画师
            return (0, "", "")
        if artist_seed == -1:
            # 随机画师
            s = random.randint(1, max_a)
        else:
            # 固定画师
            s = max(1, min(artist_seed, max_a))
        name = _get_artist_name(s)
        line = f"[{s}] {name}"
        return (s, line, line)

    def pick(self, artist_seed: int, 种子串: str = "") -> tuple[int, str, str]:
        max_a = _get_artist_count()

        if 种子串.strip():
            # Batch mode — parse seeds, use each as random seed for artist selection
            seeds = [s.strip() for s in 种子串.split("\n") if s.strip()]
            lines = []
            for s in seeds:
                try:
                    seed_val = int(s)
                except ValueError:
                    continue
                if artist_seed == 0:
                    # 无画师：所有行空
                    lines.append("")
                elif artist_seed == -1:
                    # 随机：每个种子独立抽
                    rng = random.Random(seed_val)
                    idx = rng.randint(1, max_a)
                    name = _get_artist_name(idx)
                    lines.append(f"[{idx}] {name}")
                else:
                    # 固定画师：所有行相同
                    idx = max(1, min(artist_seed, max_a))
                    name = _get_artist_name(idx)
                    lines.append(f"[{idx}] {name}")
            if lines:
                first_line = lines[0]
                if first_line:
                    first_idx = int(first_line.split("]")[0].strip("["))
                    name = _get_artist_name(first_idx)
                    return (first_idx, first_line, "\n".join(lines))
                return (0, "", "\n".join(lines))
            return (0, "", "")

        # Single mode
        return self._pick_one(artist_seed)


NODE_CLASS_MAPPINGS = {"ArtistSeedNode": ArtistSeed}
NODE_DISPLAY_NAME_MAPPINGS = {"ArtistSeedNode": "画师Seed"}
