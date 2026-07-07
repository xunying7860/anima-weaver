"""
Anima Weaver — Random Resolution Selector

Outputs random width, height, and aspect-ratio string based on
a target megapixel range and optional aspect ratio.
"""

from __future__ import annotations

import math
import random
from typing import Any

# ── Resolution helpers ─────────────────────────────────────────────

ASPECT_RATIOS: dict[str, tuple[float, float]] = {
    "1:1 (square)":          (1.0, 1.0),
    "4:3 (standard)":        (4.0, 3.0),
    "16:9 (landscape)":      (16.0, 9.0),
    "9:16 (portrait)":       (9.0, 16.0),
    "3:2 (photo)":           (3.0, 2.0),
    "2:3 (photo portrait)":  (2.0, 3.0),
    "21:9 (ultrawide)":      (21.0, 9.0),
    "16:10 (widescreen)":    (16.0, 10.0),
}

ASPECT_NAMES = list(ASPECT_RATIOS.keys())


def _resolve(megapixel: float, ratio: tuple[float, float], align: int = 8) -> tuple[int, int]:
    """Calculate width/height from megapixels and aspect ratio, snapped to align."""
    w_ratio, h_ratio = ratio
    area = megapixel * 1_000_000
    h = int(math.sqrt(area / (w_ratio / h_ratio)))
    w = int(h * (w_ratio / h_ratio))
    # snap to align
    align = max(1, align)
    w = max(64, (w // align) * align)
    h = max(64, (h // align) * align)
    return w, h


# ── Node ─────────────────────────────────────────────────────────────

class RandomResolution:
    @classmethod
    def INPUT_TYPES(s) -> dict[str, Any]:
        return {
            "required": {
                "随机画幅": (
                    "BOOLEAN",
                    {"default": True,
                     "tooltip": "开启时从可用比例中随机选择，关闭时使用固定比例"},
                ),
                "百万像素": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.0, "max": 32.0, "step": 0.01,
                     "tooltip": "目标百万像素范围（0.00 ~ 32.00 MP）"},
                ),
                "随机种子": (
                    "INT",
                    {"default": 0, "min": 0, "max": 0x7FFFFFFF},
                ),
                "固定比例": (
                    ASPECT_NAMES,
                    {"default": "1:1 (square)"},
                ),
                "对齐到": (
                    "INT",
                    {"default": 8, "min": 1, "max": 256, "step": 1,
                     "tooltip": "宽度和高度对齐到此值的倍数（如 8、16、64）"},
                ),
            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("INT", "INT", "STRING")
    RETURN_NAMES = ("宽度", "高度", "画幅比例")
    FUNCTION = "pick"
    OUTPUT_NODE = False

    def pick(
        self,
        随机画幅: bool,
        百万像素: float,
        随机种子: int,
        固定比例: str,
        对齐到: int = 8,
    ) -> tuple[int, int, str]:
        rng = random.Random(随机种子)

        if 随机画幅:
            ratio_name = rng.choice(ASPECT_NAMES)
        else:
            ratio_name = 固定比例

        w_ratio, h_ratio = ASPECT_RATIOS[ratio_name]
        width, height = _resolve(百万像素, (w_ratio, h_ratio), 对齐到)

        return (width, height, ratio_name)


# ── Node registration ───────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "RandomResolution": RandomResolution,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "RandomResolution": "随机分辨率选择器",
}
