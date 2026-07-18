"""
Anima Weaver — Text to Multiline Node.
Passes a text string through as multiline output.
"""

from __future__ import annotations


class AnimaTextJoin:
    """Convert a text string to multiline output."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        return {
            "required": {
                "文本": (
                    "STRING",
                    {"multiline": True, "forceInput": True,
                     "tooltip": "输入文本"},
                ),
            },
        }

    CATEGORY = "Anima Weaver / Utils"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("多行文本",)
    FUNCTION = "join"
    OUTPUT_NODE = False

    def join(self, 文本: str) -> tuple[str]:
        return (文本,)


NODE_CLASS_MAPPINGS = {"AnimaTextJoin": AnimaTextJoin}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaTextJoin": "Anima文本合成"}
