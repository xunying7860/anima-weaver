"""
Anima Weaver — Bottom Controls Node

Provides the Raffle filter / bottom control fields as an optional input
to the main Anima Weaver node.
"""

from __future__ import annotations
import json
from typing import Any


class BottomControls:
    """Raffle filter + bottom slot provider for Anima Weaver."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "标签列表必含": ("STRING", {"multiline": True, "default": "1girl"}),
                "过滤标签":   ("STRING", {"multiline": True, "default": ""}),
                "排除含标签列表": ("STRING", {"multiline": True, "default": ""}),
                "排除标签分类": ("STRING", {"multiline": True, "default": ""}),
                "通用标签":  ("BOOLEAN", {"default": False}),
                "争议标签":  ("BOOLEAN", {"default": False}),
                "敏感标签":  ("BOOLEAN", {"default": True}),
                "露骨标签":  ("BOOLEAN", {"default": True}),
            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("底部数据",)
    FUNCTION = "pack"
    OUTPUT_NODE = False

    def pack(self, **kwargs) -> tuple[str]:
        data: dict[str, Any] = {}
        for key in [
            "标签列表必含", "过滤标签", "排除含标签列表", "排除标签分类",
            "通用标签", "争议标签", "敏感标签", "露骨标签",
        ]:
            data[key] = kwargs.get(key, "")
        return (json.dumps(data, ensure_ascii=False),)


NODE_CLASS_MAPPINGS = {"BottomControls": BottomControls}
NODE_DISPLAY_NAME_MAPPINGS = {"BottomControls": "底部控制"}
