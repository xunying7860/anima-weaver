"""
Anima Weaver — Text List to Multiline Node.
Accumulates text items across ALL batch executions into a single multiline STRING.
Uses OUTPUT_NODE to capture all batch outputs, then merges them.
"""

from __future__ import annotations
import time


class AnimaTextListToMultiline:
    """Accumulate text items across batch into one multiline text."""

    _acc: list[str] = []
    _batch_key: str = ""

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
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs) -> float:
        # Return current time to force execution every time
        return time.time()

    def convert(self, 文本列表: str) -> tuple[str]:
        txt = 文本列表.strip() if 文本列表 else ""
        if txt and (not self._acc or txt != self._acc[-1]):
            self._acc.append(txt)
        result = "\n".join(self._acc)
        return (result,)


NODE_CLASS_MAPPINGS = {"AnimaTextListToMultiline": AnimaTextListToMultiline}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaTextListToMultiline": "Anima列表转多行"}
