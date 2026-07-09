"""
Anima Weaver — Prompt Slots Node

Provides the 8 tag slots + natural language text as an optional input
to the main Anima Weaver node.
"""

from __future__ import annotations
import json
from typing import Any


class PromptSlots:
    """Tag + NL slot provider for Anima Weaver."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "人数/身份": ("STRING", {"multiline": True, "default": "1girl, solo"}),
                "外貌":     ("STRING", {"multiline": True, "default": ""}),
                "服装":     ("STRING", {"multiline": True, "default": ""}),
                "姿势/动作": ("STRING", {"multiline": True, "default": ""}),
                "表情":     ("STRING", {"multiline": True, "default": ""}),
                "镜头":     ("STRING", {"multiline": True, "default": ""}),
                "场景/环境": ("STRING", {"multiline": True, "default": ""}),
                "细节/氛围": ("STRING", {"multiline": True, "default": ""}),
                "自然语言描述": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("槽位数据",)
    FUNCTION = "pack"
    OUTPUT_NODE = False

    def pack(self, **kwargs) -> tuple[str]:
        data: dict[str, str] = {}
        for key in [
            "人数/身份", "外貌", "服装", "姿势/动作",
            "表情", "镜头", "场景/环境", "细节/氛围",
            "自然语言描述",
        ]:
            data[key] = str(kwargs.get(key, ""))
        return (json.dumps(data, ensure_ascii=False),)


NODE_CLASS_MAPPINGS = {"PromptSlots": PromptSlots}
NODE_DISPLAY_NAME_MAPPINGS = {"PromptSlots": "提示词槽位"}
