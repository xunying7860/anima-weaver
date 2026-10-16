"""
Anima Weaver — Artist Seed Node
-1 = 随机画师, 0 = 无画师, 1~max = 固定画师.
Optional 种子串 input for batch mode.
"""

from __future__ import annotations

import random
from typing import Any

# P1: 画师索引统一走 artist_index 单例
# （进程内只加载一次，O(1) 序号查名；替代原来每次调用全文件扫描）
try:
    from .artist_index import count as _artist_count, name as _artist_name
except ImportError:
    from artist_index import count as _artist_count, name as _artist_name


def _get_artist_count() -> int:
    """画师总数（artist_index.count：加载一次，O(1)）。"""
    return _artist_count()


def _get_artist_name(idx: int) -> str:
    """按 1-based 序号取画师名（artist_index.name：O(1)，替代旧的全文件扫描）。"""
    return _artist_name(idx)


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
