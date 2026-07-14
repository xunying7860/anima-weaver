"""
Batch Seed Node — generates N random seeds as a multiline STRING.
"""

from __future__ import annotations

import random
from typing import Any


class BatchSeedNode:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "数量": ("INT", {"default": 1, "min": 1, "max": 4096, "step": 1,
                                "tooltip": "生成的种子数量"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("种子串",)
    FUNCTION = "generate"
    CATEGORY = "Anima Weaver / Batch"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs) -> float:
        return random.random()

    def generate(self, 数量: int) -> tuple[str]:
        seeds = [str(random.randint(1, 0x7FFFFFFFFFFFFFFF)) for _ in range(数量)]
        return ("\n".join(seeds),)


NODE_CLASS_MAPPINGS = {"BatchSeedNode": BatchSeedNode}
NODE_DISPLAY_NAME_MAPPINGS = {"BatchSeedNode": "批量种子"}
