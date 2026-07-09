"""
Sync Passthrough — merges 7 inputs into multiline JSON (1 output).
Filtered by start_index / max_rows / remove_empty_lines.
"""

from __future__ import annotations

import json
from typing import Any

_INPUT_NAMES = ["种子串", "提示词串", "画师串", "分辨率串", "反推串", "宽度串", "高度串"]
_JSON_KEYS = ["种子", "提示词", "画师", "分辨率", "反推", "宽度", "高度"]


class SyncPassthrough:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        optional = {
            name: ("STRING", {"forceInput": True, "multiline": True})
            for name in _INPUT_NAMES
        }
        optional["start_index"] = ("INT", {"default": 0, "min": 0, "max": 9999})
        optional["max_rows"] = ("INT", {"default": 1000, "min": 1, "max": 9999})
        optional["remove_empty_lines"] = ("BOOLEAN", {"default": True})
        return {"optional": optional}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("合并输出",)
    FUNCTION = "merge"
    CATEGORY = "Anima Weaver / Batch"

    def merge(self, **kwargs) -> tuple[str]:
        start = int(kwargs.get("start_index", 0))
        max_rows = int(kwargs.get("max_rows", 1000))
        rm_empty = bool(kwargs.get("remove_empty_lines", True))

        # Parse each input into rows
        all_rows: dict[str, list[str]] = {}
        for name in _INPUT_NAMES:
            text = kwargs.get(name, "")
            if not text or not text.strip():
                all_rows[name] = []
                continue
            lines = text.split("\n")
            if rm_empty:
                lines = [ln for ln in lines if ln.strip()]
            end = start + max_rows
            all_rows[name] = lines[start:end] if start < len(lines) else []

        # Determine row count (use max across all inputs, pad short ones)
        counts = [len(v) for v in all_rows.values()]
        row_count = max(counts) if counts else 0

        # Build multiline JSON
        lines_out: list[str] = []
        for i in range(row_count):
            obj = {}
            for input_name, json_key in zip(_INPUT_NAMES, _JSON_KEYS):
                rows = all_rows[input_name]
                obj[json_key] = rows[i] if i < len(rows) else ""
            lines_out.append(json.dumps(obj, ensure_ascii=False))

        return ("\n".join(lines_out),)


NODE_CLASS_MAPPINGS = {"SyncPassthrough": SyncPassthrough}
NODE_DISPLAY_NAME_MAPPINGS = {"SyncPassthrough": "同步串行"}
