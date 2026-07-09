"""
Anima Weaver — Random Resolution Selector
Single + batch mode (via 种子串 input).
"""

from __future__ import annotations

import math
import random
from typing import Any

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
    w_ratio, h_ratio = ratio
    area = megapixel * 1_000_000
    h = int(math.sqrt(area / (w_ratio / h_ratio)))
    w = int(h * (w_ratio / h_ratio))
    align = max(1, align)
    w = max(64, (w // align) * align)
    h = max(64, (h // align) * align)
    return w, h


def _pick_one(随机画幅: bool, 固定比例: str, 百万像素: float, 对齐到: int,
              seed_val: int | None = None) -> tuple[int, int, str]:
    if seed_val is None:
        _seed = random.randint(0, 0x7FFFFFFF)
    else:
        _seed = seed_val
    rng = random.Random(_seed)
    ratio_name = rng.choice(ASPECT_NAMES) if 随机画幅 else 固定比例
    w_ratio, h_ratio = ASPECT_RATIOS[ratio_name]
    width, height = _resolve(百万像素, (w_ratio, h_ratio), 对齐到)
    return (width, height, f"{width}x{height}")


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
                    {"default": 1.0, "min": 0.0, "max": 32.0, "step": 0.01},
                ),
                "固定比例": (
                    ASPECT_NAMES,
                    {"default": "1:1 (square)"},
                ),
                "对齐到": (
                    "INT",
                    {"default": 8, "min": 1, "max": 256, "step": 1},
                ),
            },
            "optional": {
                "随机种子": (
                    "INT",
                    {"forceInput": True, "default": 0, "min": 0, "max": 0x7FFFFFFF},
                ),
                "种子串": ("STRING", {"forceInput": True, "multiline": True,
                                      "tooltip": "接入批量种子串，每行一个种子"}),
            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("INT", "INT", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("宽度", "高度", "分辨率", "分辨率串", "宽度串", "高度串")
    FUNCTION = "pick"
    OUTPUT_NODE = False

    def pick(self, 随机画幅: bool, 百万像素: float, 固定比例: str,
             对齐到: int = 8, 随机种子: int | None = None, 种子串: str = "") -> tuple[int, int, str, str, str, str]:
        if 种子串.strip():
            seeds = [s.strip() for s in 种子串.split("\n") if s.strip()]
            res_lines: list[str] = []
            w_lines: list[str] = []
            h_lines: list[str] = []
            for s in seeds:
                try:
                    seed_val = int(s)
                except ValueError:
                    continue
                w, h, ratio = _pick_one(随机画幅, 固定比例, 百万像素, 对齐到, seed_val)
                res_lines.append(ratio)
                w_lines.append(str(w))
                h_lines.append(str(h))
            first_w, first_h, first_ratio = _pick_one(随机画幅, 固定比例, 百万像素, 对齐到,
                                                       int(seeds[0]) if seeds else None)
            return (first_w, first_h, first_ratio, "\n".join(res_lines),
                    "\n".join(w_lines), "\n".join(h_lines))

        # Single mode
        w, h, ratio = _pick_one(随机画幅, 固定比例, 百万像素, 对齐到,
                                int(随机种子) if 随机种子 is not None and str(随机种子) != "" else None)
        return (w, h, ratio, ratio, str(w), str(h))


NODE_CLASS_MAPPINGS = {"RandomResolution": RandomResolution}
NODE_DISPLAY_NAME_MAPPINGS = {"RandomResolution": "随机分辨率选择器"}
