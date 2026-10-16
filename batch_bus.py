"""
AnimaBatchBus（Anima批量总线）—— 合并输出 + 按行拆分 一步到位
=============================================================

2026-10-16 用户反馈重构：删掉「模式」下拉与「JSON行」中间层，内置
easy-use「easy promptLine（提示词行）」的行窗口逻辑（start_index /
max_rows / remove_empty_lines 三个参数与其**同名同义**）。以前需要
「合并总线 → easy promptLine → 拆分总线」三个节点才能完成的
「多行对齐 + 选行」，现在一个节点直接给。

输入（4 路多行串，按行对齐；forceInput 连线端口）：
    种子串 · 提示词串 · 宽度串 · 高度串
输出（永远同时给齐，不再分模式）：
    合并输出  = 窗口内逐行打包的多行 JSON（键：种子/提示词/宽度/高度）
    种子/提示词/宽度/高度 = 窗口第一行（= 去空行后的第 start_index 行）的标量

历史沿革：由 sync_passthrough.py（合并）+ passthrough_split.py（拆分）
两节点合并而来；「画师」通道（画师已拼进提示词）与「分辨率串/反推串/
JSON行/分辨率/反推」（2026-10-16 用户裁剪）已删。旧工作流的连线与
widget 由 tools/migrate_workflows.py 按名字自动迁移（含 split 总线经
easy promptLine 反查合并总线的重接线）。
"""

from __future__ import annotations

import json
from typing import Any

# ── 通道定义：(连线端口名, JSON 键) ─────────────────────────────────────
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


class AnimaBatchBus:
    """多行对齐 + easy-use 提示词行选行，一个节点完成（无模式下拉）。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        # 通道串：全部 forceInput，只做连线端口，不占 widget
        optional: dict[str, Any] = {
            name: ("STRING", {"forceInput": True, "multiline": True,
                              "tooltip": "多行串，第 N 行与其他通道第 N 行对齐"})
            for name in _INPUT_NAMES
        }
        # 行窗口三参数：与 easy-use「easy promptLine（提示词行）」同名同义
        optional["start_index"] = ("INT", {"default": 0, "min": 0, "max": 9999,
                                       "tooltip": "行窗口起点：拆分标量输出=去空行后第 start_index 行"})
        optional["max_rows"] = ("INT", {"default": 1000, "min": 1, "max": 9999})
        optional["remove_empty_lines"] = ("BOOLEAN", {"default": True})

        return {"optional": optional}

    RETURN_TYPES = ("STRING", "INT", "STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("合并输出", "种子", "提示词", "宽度", "高度")
    FUNCTION = "run"
    CATEGORY = "Anima Weaver / Batch"

    # ── 入口 ────────────────────────────────────────────────────────────
    def run(self, **kwargs) -> tuple:
        """一次执行同时产出：合并 JSON 多行 + 窗口首行标量（提示词行逻辑）。

        未连线的可选输入 ComfyUI 根本不会传，用 **kwargs 兜住。
        """
        start = int(kwargs.get("start_index", 0) or 0)
        max_rows = int(kwargs.get("max_rows", 1000) or 1000)
        rm_empty = bool(kwargs.get("remove_empty_lines", True))

        # 每路通道按行拆开（空通道 = 0 行）；行窗口语义与 easy promptLine 一致
        all_rows: dict[str, list[str]] = {}
        for name in _INPUT_NAMES:
            text = kwargs.get(name, "")
            if text is None:
                text = ""
            if not isinstance(text, str):
                text = str(text)
            if not text.strip():
                all_rows[name] = []
                continue
            lines = text.split("\n")
            if rm_empty:
                lines = [ln for ln in lines if ln.strip()]
            end = start + max_rows
            all_rows[name] = lines[start:end] if start < len(lines) else []

        # 行数取各通道最大值，短的补 ""
        counts = [len(v) for v in all_rows.values()]
        row_count = max(counts) if counts else 0

        # 合并输出：逐行打包 JSON（ensure_ascii=False 保住中文）
        lines_out: list[str] = []
        for i in range(row_count):
            obj: dict[str, str] = {}
            for input_name, json_key in zip(_INPUT_NAMES, _JSON_KEYS):
                rows = all_rows[input_name]
                obj[json_key] = rows[i] if i < len(rows) else ""
            lines_out.append(json.dumps(obj, ensure_ascii=False))

        # 拆分标量：窗口第一行（= 去空行后的第 start_index 行）
        def row_val(name: str) -> str:
            rows = all_rows[name]
            return rows[0].strip() if rows else ""

        def row_int(name: str, default: int) -> int:
            try:
                return int(row_val(name))
            except (ValueError, TypeError):
                return default

        return (
            "\n".join(lines_out),                          # 合并输出
            row_int("种子串", _SEED_DEFAULT),               # 种子   INT
            row_val("提示词串"),                            # 提示词 STRING
            row_int("宽度串", _SIZE_DEFAULT),               # 宽度   INT
            row_int("高度串", _SIZE_DEFAULT),               # 高度   INT
        )


NODE_CLASS_MAPPINGS = {"AnimaBatchBus": AnimaBatchBus}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaBatchBus": "Anima批量总线"}
