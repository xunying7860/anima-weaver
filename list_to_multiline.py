"""
Anima Weaver — Text List to Multiline Node.
Passes through text items, one per batch execution.
Each batch item gets its own line, naturally aligned with image order.
"""

from __future__ import annotations


class AnimaTextListToMultiline:
    """Pass text through, one line per batch execution."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        return {
            "required": {
                "文本列表": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "接入 WD14 等节点的文本输出"},
                ),
            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("多行文本",)
    FUNCTION = "convert"
    OUTPUT_NODE = False

    def convert(self, 文本列表: str) -> tuple[str]:
        return (文本列表,)


NODE_CLASS_MAPPINGS = {"AnimaTextListToMultiline": AnimaTextListToMultiline}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaTextListToMultiline": "Anima列表转多行"}
