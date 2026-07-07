"""
Anima Weaver — Random Resolution Selector

A standalone ComfyUI node that outputs random width, height,
and aspect-ratio string for use with the AnimaWeaver prompt builder.
"""

from __future__ import annotations

import random
from typing import Any

# ── Resolution presets ───────────────────────────────────────────────

ASPECT_PRESETS: dict[str, list[tuple[int, int]]] = {
    "1:1 (square)":       [(1024, 1024), (896, 896), (768, 768)],
    "4:3 (standard)":     [(1152, 896), (1216, 832), (1344, 1008)],
    "16:9 (landscape)":   [(1216, 704), (1344, 768), (1408, 800)],
    "9:16 (portrait)":    [(704, 1216), (768, 1344), (800, 1408)],
    "3:2 (photo)":        [(1216, 832), (1344, 896), (1408, 960)],
    "2:3 (photo portrait)": [(832, 1216), (896, 1344), (960, 1408)],
    "21:9 (ultrawide)":   [(1408, 640), (1536, 704), (1600, 736)],
    "16:10 (widescreen)": [(1152, 896), (1280, 800), (1408, 896)],
}

ASPECT_NAMES = list(ASPECT_PRESETS.keys())

# ── Node ─────────────────────────────────────────────────────────────

class RandomResolution:
    @classmethod
    def INPUT_TYPES(s) -> dict[str, Any]:
        return {
            "required": {
                "随机画幅": ("BOOLEAN", {"default": True,
                    "tooltip": "开启时随机选择比例和分辨率，关闭时使用下面的固定值"}),
                "固定比例": (ASPECT_NAMES, {"default": "1:1 (square)"}),
                "固定宽度": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 8}),
                "固定高度": ("INT", {"default": 1024, "min": 64, "max": 8192, "step": 8}),
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
        固定比例: str,
        固定宽度: int,
        固定高度: int,
    ) -> tuple[int, int, str]:
        if 随机画幅:
            ratio_name = random.choice(ASPECT_NAMES)
            candidates = ASPECT_PRESETS[ratio_name]
            width, height = random.choice(candidates)
        else:
            width, height = 固定宽度, 固定高度
            ratio_name = 固定比例

        return (width, height, ratio_name)


# ── Node registration ───────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "RandomResolution": RandomResolution,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "RandomResolution": "随机分辨率选择器",
}
