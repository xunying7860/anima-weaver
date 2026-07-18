"""
Anima Weaver — Text List to JSON Array Node.
Accumulates text items across batch executions into a JSON array string.
"""

from __future__ import annotations
import time
import json as _json


class AnimaTextListToMultiline:
    """Accumulate text items across batch into a JSON array."""

    _acc: list[str] = []

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
    RETURN_NAMES = ("JSON数组",)
    FUNCTION = "convert"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs) -> float:
        return time.time()

    def convert(self, 文本列表: str) -> tuple[str]:
        txt = 文本列表.strip() if 文本列表 else ""
        if txt and (not self._acc or txt != self._acc[-1]):
            self._acc.append(txt)
        return (_json.dumps(self._acc, ensure_ascii=False),)


NODE_CLASS_MAPPINGS = {"AnimaTextListToMultiline": AnimaTextListToMultiline}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaTextListToMultiline": "Anima列表转JSON"}
