"""
Passthrough Split — takes 1 JSON line → 7 typed outputs (INT for seed/width/height).
"""

from __future__ import annotations

import json
from typing import Any


class PassthroughSplit:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "JSON行": (
                    "STRING",
                    {"multiline": False, "default": "{}",
                     "forceInput": True,
                     "tooltip": "接入提示词行的输出，取 JSON 格式的当前行"},
                ),
            },
        }

    RETURN_TYPES = ("INT", "STRING", "STRING", "STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("种子", "提示词", "画师", "分辨率", "反推", "宽度", "高度")
    FUNCTION = "split"
    CATEGORY = "Anima Weaver / Batch"

    def split(self, JSON行: str) -> tuple[int, str, str, str, str, int, int]:
        try:
            data = json.loads(JSON行.strip())
        except (json.JSONDecodeError, AttributeError):
            data = {}

        def get_int(key: str, default: int = 0) -> int:
            try:
                return int(data.get(key, default))
            except (ValueError, TypeError):
                return default

        def get_str(key: str) -> str:
            return str(data.get(key, ""))

        return (
            get_int("种子"),        # 种子 INT
            get_str("提示词"),      # 提示词 STRING
            get_str("画师"),        # 画师 STRING
            get_str("分辨率"),      # 分辨率 STRING
            get_str("反推"),        # 反推 STRING
            get_int("宽度", 512),   # 宽度 INT
            get_int("高度", 512),   # 高度 INT
        )


NODE_CLASS_MAPPINGS = {"PassthroughSplit": PassthroughSplit}
NODE_DISPLAY_NAME_MAPPINGS = {"PassthroughSplit": "串行拆分"}
