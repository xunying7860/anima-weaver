"""
Anima Weaver — Text List to JSON Array Node.
Stores accumulated data in module-level shared dict for Anima反推 to read directly.
"""

from __future__ import annotations
import time
import json as _json

# ── Shared storage: Anima反推 reads from here ──
shared_json_data: list[str] = []


class AnimaTextListToMultiline:
    """Accumulate text items across batch, stores in shared_json_data."""

    _acc: list[str] = []
    _prev: str = ""

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
    OUTPUT_NODE = False

    @classmethod
    def IS_CHANGED(cls, **kwargs) -> float:
        return time.time()

    def convert(self, 文本列表: str) -> tuple[str]:
        global shared_json_data
        txt = 文本列表.strip() if 文本列表 else ""
        if txt and txt != self._prev:
            self._prev = txt
            self._acc.append(txt)
            shared_json_data = list(self._acc)  # sync to shared
        return (_json.dumps(self._acc, ensure_ascii=False),)


NODE_CLASS_MAPPINGS = {"AnimaTextListToMultiline": AnimaTextListToMultiline}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaTextListToMultiline": "Anima列表转JSON"}
