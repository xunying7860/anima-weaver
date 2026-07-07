"""
Anima Weaver — Random Resolution Selector

Selects a random resolution matching a target megapixel count
and aspect ratio.  Outputs width, height, and aspect-ratio label.
"""

from __future__ import annotations

import math
import random
from typing import Any

# ── Aspect ratios ─────────────────────────────────────────────────────

ASPECT_RATIOS: dict[str, tuple[float, float]] = {
    "1:1 (方形)":       (1, 1),
    "2:3 (竖幅照片)":    (2, 3),
    "3:2 (照片)":       (3, 2),
    "3:4 (竖幅标准)":    (3, 4),
    "4:3 (标准)":       (4, 3),
    "9:16 (竖幅宽屏)":   (9, 16),
    "16:9 (宽屏)":      (16, 9),
    "21:9 (超宽屏)":    (21, 9),
}

# ── ComfyUI Node ──────────────────────────────────────────────────────

class RandomResolution:
    """
    Picks a random (width, height) pair that approximately matches a
    user-specified megapixel target and an aspect ratio.
    """

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "宽高比": (list(ASPECT_RATIOS.keys()), {"default": "3:4 (竖幅标准)"}),
                "百万像素": ("FLOAT", {"default": 1.6, "min": 0.1, "max": 50.0, "step": 0.1}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 0x7FFFFFFF}),
            }
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("INT", "INT", "STRING", "FLOAT")
    RETURN_NAMES = ("宽度", "高度", "画幅比例", "实际百万像素")
    FUNCTION = "generate"

    def generate(
        self,
        宽高比: str,
        百万像素: float,
        种子: int,
    ) -> tuple[int, int, str, float]:
        rng = random.Random(种子)

        w_ratio, h_ratio = ASPECT_RATIOS[宽高比]

        # Target total pixels
        target_pixels = 百万像素 * 1_000_000

        # Base guess: w = sqrt(pixels * ratio), h = pixels / w
        base_w = math.sqrt(target_pixels * w_ratio / h_ratio)
        base_h = target_pixels / base_w

        # Round to nearest multiples of 64 (common for AI models)
        def _round64(x: int) -> int:
            return max(64, (x // 64) * 64)

        # Add ±10% jitter for variety
        jitter = rng.uniform(0.90, 1.10)
        w = _round64(int(base_w * jitter))
        h = _round64(int(base_h * jitter))

        # Ensure ratio is maintained
        actual_mp = round(w * h / 1_000_000, 2)

        return (w, h, 宽高比, actual_mp)
