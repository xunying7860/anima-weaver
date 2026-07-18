"""
Anima Weaver — Text List to Multiline Node.
Converts a text list (STRING is_list) to a single multiline STRING.
"""

from __future__ import annotations


class AnimaTextListToMultiline:
    """Convert a text list input to multiline STRING output."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        return {
            "required": {
                "文本列表": (
                    "STRING",
                    {"forceInput": True, "multiline": True, "is_list": True,
                     "tooltip": "接入 WD14 等节点的文本列表输出"},
                ),
            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("多行文本",)
    FUNCTION = "convert"
    OUTPUT_NODE = False

    def convert(self, 文本列表: str | list[str]) -> tuple[str]:
        # is_list=True passes items one per batch execution as separate strings
        # ComfyUI collects them into a list when batch count > 1
        if isinstance(文本列表, list):
            return ("\n".join(文本列表),)
        return (文本列表,)


NODE_CLASS_MAPPINGS = {"AnimaTextListToMultiline": AnimaTextListToMultiline}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaTextListToMultiline": "Anima列表转多行"}
