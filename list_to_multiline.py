"""
Anima Weaver — Text List to Multiline Node.
Accumulates text items across batch executions into a single multiline STRING.
"""

from __future__ import annotations


class AnimaTextListToMultiline:
    """Accumulate text items across batch into one multiline text."""

    _accumulator: list[str] = []  # class-level cache shared across batch calls

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

    @classmethod
    def IS_CHANGED(cls, **kwargs) -> float:
        # Reset accumulator at the start of each new batch queue
        cls._accumulator = []
        return 0.0

    def convert(self, 文本列表: str) -> tuple[str]:
        if 文本列表 and 文本列表.strip():
            if 文本列表 not in self._accumulator:
                self._accumulator.append(文本列表.strip())
        return ("\n".join(self._accumulator),)


NODE_CLASS_MAPPINGS = {"AnimaTextListToMultiline": AnimaTextListToMultiline}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaTextListToMultiline": "Anima列表转多行"}
