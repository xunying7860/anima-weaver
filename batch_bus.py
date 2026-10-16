"""
Anima批量合并 / Anima批量拆分 —— 两节点批量管线（中间挂 easy-use 提示词行）
==========================================================================

用户最终确认的标准管线（2026-10-16）：

    批量种子 / Anima随机提示词 / 随机分辨率   （各自的多行串，按行对齐）
            │
            ▼
    Anima批量合并   多行串 → 逐行打包的多行 JSON（合并输出）
            │
            ▼
    easy-use「easy promptLine（提示词行）」   按 index 选出一行 JSON
            │
            ▼
    Anima批量拆分   一行 JSON → 种子 / 提示词 / 宽度 / 高度（标量）
            │
            ▼
    KSampler(noise_seed) / CLIPTextEncode(text) / EmptyLatentImage(width,height)

通道只保留 种子 / 提示词 / 宽度 / 高度（分辨率串、反推串、画师串及
拆分侧的「合并输出」均已按用户要求裁剪；JSON行 只在拆分节点的入口）。

历史：sync_passthrough.py（合并）+ passthrough_split.py（拆分）先被合并成
带「模式」下拉的 AnimaBatchBus（11→8 轮），又试做过单节点内置选行
（2026-10-16 上午），最终按用户要求恢复为两个独立节点、由用户自行在
中间挂 easy-use 提示词行。旧工作流由 tools/migrate_workflows.py 按
「模式」widget 自动拆成对应的新节点。
"""

from __future__ import annotations

import json
from typing import Any

# ── 合并通道定义：(连线端口名, JSON 键) ────────────────────────────────
_CHANNELS: list[tuple[str, str]] = [
    ("种子串", "种子"),
    ("提示词串", "提示词"),
    ("宽度串", "宽度"),
    ("高度串", "高度"),
]
_INPUT_NAMES: list[str] = [name for name, _ in _CHANNELS]
_JSON_KEYS: list[str] = [key for _, key in _CHANNELS]

# 拆分标量的缺省值（与旧 passthrough_split.py 一致）
_SEED_DEFAULT = 0
_SIZE_DEFAULT = 512


def _window(text, start: int, max_rows: int, rm_empty: bool) -> list[str]:
    """行窗口：split('\n') →（可选去空行）→ [start:start+max_rows]。
    与 easy-use easy promptLine 的窗口参数同名同义。"""
    if text is None:
        text = ""
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        return []
    lines = text.split("\n")
    if rm_empty:
        lines = [ln for ln in lines if ln.strip()]
    end = start + max_rows
    return lines[start:end] if start < len(lines) else []


class AnimaBatchMerge:
    """Anima批量合并：多路多行串按行对齐打包成多行 JSON。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        optional: dict[str, Any] = {
            name: ("STRING", {"forceInput": True, "multiline": True,
                              "tooltip": "多行串，第 N 行与其他通道第 N 行对齐"})
            for name in _INPUT_NAMES
        }
        optional["start_index"] = ("INT", {"default": 0, "min": 0, "max": 9999,
                                       "tooltip": "行窗口起点（与 easy-use 提示词行同名同义）"})
        optional["max_rows"] = ("INT", {"default": 1000, "min": 1, "max": 9999})
        optional["remove_empty_lines"] = ("BOOLEAN", {"default": True})
        return {"optional": optional}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("合并输出",)
    FUNCTION = "merge"
    CATEGORY = "Anima Weaver / Batch"

    def merge(self, **kwargs) -> tuple:
        start = int(kwargs.get("start_index", 0) or 0)
        max_rows = int(kwargs.get("max_rows", 1000) or 1000)
        rm_empty = bool(kwargs.get("remove_empty_lines", True))

        all_rows: dict[str, list[str]] = {}
        for name in _INPUT_NAMES:
            all_rows[name] = _window(kwargs.get(name, ""), start, max_rows, rm_empty)

        counts = [len(v) for v in all_rows.values()]
        row_count = max(counts) if counts else 0

        lines_out: list[str] = []
        for i in range(row_count):
            obj: dict[str, str] = {}
            for input_name, json_key in zip(_INPUT_NAMES, _JSON_KEYS):
                rows = all_rows[input_name]
                obj[json_key] = rows[i] if i < len(rows) else ""
            lines_out.append(json.dumps(obj, ensure_ascii=False))
        return ("\n".join(lines_out),)


class AnimaBatchSplit:
    """Anima批量拆分：一行 JSON（通常来自上游 easy promptLine 选出的行）
    → 种子 / 提示词 / 宽度 / 高度 标量。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {"optional": {
            "JSON行": ("STRING", {"forceInput": True, "multiline": True,
                               "tooltip": "接入一行 JSON（上游 easy-use 提示词行选出的行；多行时取窗口第一行）"}),
            "start_index": ("INT", {"default": 0, "min": 0, "max": 9999,
                                 "tooltip": "直接喂多行 JSON 时的行窗口起点；上游已是单行则无影响"}),
            "max_rows": ("INT", {"default": 1000, "min": 1, "max": 9999}),
            "remove_empty_lines": ("BOOLEAN", {"default": True}),
        }}

    RETURN_TYPES = ("INT", "STRING", "INT", "INT")
    RETURN_NAMES = ("种子", "提示词", "宽度", "高度")
    FUNCTION = "split"
    CATEGORY = "Anima Weaver / Batch"

    def split(self, **kwargs) -> tuple:
        start = int(kwargs.get("start_index", 0) or 0)
        max_rows = int(kwargs.get("max_rows", 1000) or 1000)
        rm_empty = bool(kwargs.get("remove_empty_lines", True))

        window = _window(kwargs.get("JSON行", ""), start, max_rows, rm_empty)
        row = window[0] if window else ""

        try:
            data = json.loads(row.strip())
        except (json.JSONDecodeError, AttributeError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}

        def get_int(key: str, default: int) -> int:
            try:
                return int(data.get(key, default))
            except (ValueError, TypeError):
                return default

        return (
            get_int("种子", _SEED_DEFAULT),
            str(data.get("提示词", "")),
            get_int("宽度", _SIZE_DEFAULT),
            get_int("高度", _SIZE_DEFAULT),
        )


NODE_CLASS_MAPPINGS = {"AnimaBatchMerge": AnimaBatchMerge,
                       "AnimaBatchSplit": AnimaBatchSplit}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaBatchMerge": "Anima批量合并",
                              "AnimaBatchSplit": "Anima批量拆分"}
