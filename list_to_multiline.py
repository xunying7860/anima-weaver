"""
Anima Weaver — Text List to JSON Array Node.
Uses INPUT_IS_LIST to receive ALL batch items in a single execution.
Outputs one complete multiline text.
"""

from __future__ import annotations


class AnimaTextListToMultiline:
    """Convert batch text list to JSON array in a single execution."""

    INPUT_IS_LIST = True

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

    def convert(self, 文本列表: list[str]) -> tuple[str]:
        # Receive ALL batch items as a list, output one complete JSON array
        items = [t.strip() for t in 文本列表 if t and t.strip()]
        return ("\n".join(items),)


NODE_CLASS_MAPPINGS = {"AnimaTextListToMultiline": AnimaTextListToMultiline}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaTextListToMultiline": "Anima列表转多行"}
