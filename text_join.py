"""
Anima Weaver — Text List to Multiline Node.
Joins multiple text inputs into a single multiline STRING.
"""

from __future__ import annotations


class AnimaTextJoin:
    """Join multiple text inputs into a single multiline STRING."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        inputs = {
            "required": {},
            "optional": {},
        }
        for i in range(1, 9):
            inputs["optional"][f"文本{i}"] = (
                "STRING",
                {"forceInput": True, "multiline": True},
            )
        return inputs

    CATEGORY = "Anima Weaver / Utils"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("多行文本",)
    FUNCTION = "join"
    OUTPUT_NODE = False

    def join(self, **kwargs) -> tuple[str]:
        lines = []
        for i in range(1, 9):
            val = kwargs.get(f"文本{i}", "")
            if val and val.strip():
                lines.append(val.strip())
        return ("\n".join(lines),)


NODE_CLASS_MAPPINGS = {"AnimaTextJoin": AnimaTextJoin}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaTextJoin": "Anima文本合成"}
