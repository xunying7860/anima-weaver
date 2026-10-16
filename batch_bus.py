"""
AnimaBatchBus（Anima批量总线）—— 合并 / 拆分 二合一
=====================================================

由 sync_passthrough.py（合并：多路串 → 多行 JSON）+ passthrough_split.py
（拆分：1 行 JSON → 多路输出）合并而来，用「模式」下拉切换。两段逻辑逐行复刻原
两个文件的实现，两种模式互为逆运算（合并产出的 JSON 行喂回拆分模式必须逐字段还原）。

通道 ↔ JSON 键（2026-10 四节点版：**「画师」通道已删**，7 路 → 6 路；
画师名由主节点「画师种子」直接拼进提示词，不再单独成串）：
    种子串→种子 · 提示词串→提示词 · 分辨率串→分辨率
    反推串→反推 · 宽度串→宽度 · 高度串→高度
⚠ 删的是中间项，输入/输出两端其余通道的 slot 都前移了一位；
  旧工作流的连线由 tools/migrate_workflows.py 按名字重排（勿手工改数字）。

关于「分辨率通道」的取舍（方案 §1.3 注里点出的代码/文档不一致）：
    README 说「7路→6路（移除分辨率通道）」，但代码里 sync_passthrough.py 的
    _INPUT_NAMES 仍有「分辨率串」、passthrough_split.py 也仍返回「分辨率」。
    这里以源文件为准**保留**该通道：否则合并出来的 JSON 行里 分辨率 字段恒为空，
    喂回拆分模式无法逐字段还原输入，两模式就不再互逆了。

INPUT_TYPES 的 optional 顺序有讲究（改之前先读这段）：
    前面 6 项是通道串（forceInput → 显示成连线端口）；
    「JSON行」排在通道串之后（第 6 号端口）—— 旧 PassthroughSplit 的 JSON行 在 0 号端口，
    合并后必然位移，连线统一由 tools/migrate_workflows.py 按名字重排。

返回值固定一套 7 元组（RETURN_TYPES / RETURN_NAMES 两种模式共用），用不到的位置填空串 / 0。
"""

from __future__ import annotations

import json
from typing import Any

# ── 通道定义：(连线端口名, JSON 键)。「画师」通道已删（画师进提示词），
#    删的是中间项 → 其余通道两端 slot 各前移 1，旧连线按名字迁移 ──────────
_CHANNELS: list[tuple[str, str]] = [
    ("种子串", "种子"),
    ("提示词串", "提示词"),
    ("分辨率串", "分辨率"),
    ("反推串", "反推"),
    ("宽度串", "宽度"),
    ("高度串", "高度"),
]
_INPUT_NAMES: list[str] = [name for name, _ in _CHANNELS]
_JSON_KEYS: list[str] = [key for _, key in _CHANNELS]

# 拆分模式的取值默认值（与 passthrough_split.py 逐字一致）
_SEED_DEFAULT = 0
_SIZE_DEFAULT = 512


class AnimaBatchBus:
    """合并 / 拆分 二合一的批量总线（原「同步串行」+「串行拆分」）。"""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        # 通道串：全部 forceInput，只做连线端口，不占 widget
        optional: dict[str, Any] = {
            name: ("STRING", {"forceInput": True, "multiline": True})
            for name in _INPUT_NAMES
        }
        # 拆分模式入口：放在通道串之后，理由见模块 docstring
        optional["JSON行"] = (
            "STRING",
            {"forceInput": True, "multiline": True,
             "tooltip": "拆分模式：接入一行 JSON（合并模式的输出行）"},
        )
        optional["start_index"] = ("INT", {"default": 0, "min": 0, "max": 9999})
        optional["max_rows"] = ("INT", {"default": 1000, "min": 1, "max": 9999})
        optional["remove_empty_lines"] = ("BOOLEAN", {"default": True})

        return {
            "required": {
                # 唯一的必填项，也是节点的第一个 widget
                "模式": (["合并", "拆分"], {"default": "合并"}),
            },
            "optional": optional,
        }

    # 两种模式共用同一套返回值，用不到的位置填空串 / 0
    RETURN_TYPES = ("STRING", "INT", "STRING", "STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("合并输出", "种子", "提示词", "反推", "分辨率", "宽度", "高度")
    FUNCTION = "run"
    CATEGORY = "Anima Weaver / Batch"

    # ── 入口 ────────────────────────────────────────────────────────────
    def run(self, 模式: str = "合并", **kwargs) -> tuple:
        """ComfyUI 按关键字传参：模式 + 各通道串 + JSON行 + 三个窗口参数。

        用 **kwargs 兜住所有可选输入（未连线的可选输入 ComfyUI 根本不会传），
        与源文件 sync_passthrough.py::merge 的写法保持一致。
        """
        if str(模式).strip() == "拆分":
            return self._split(kwargs)
        return self._merge(kwargs)

    # ── 合并：多路串 → 多行 JSON（复刻 sync_passthrough.py::merge）──────
    def _merge(self, kwargs: dict) -> tuple:
        start = int(kwargs.get("start_index", 0) or 0)
        max_rows = int(kwargs.get("max_rows", 1000) or 1000)
        rm_empty = bool(kwargs.get("remove_empty_lines", True))

        # 每路通道按行拆开（空通道 = 0 行）
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

        # 行数取各通道最大值，短的补 ""
        counts = [len(v) for v in all_rows.values()]
        row_count = max(counts) if counts else 0

        # 逐行打包成 JSON（ensure_ascii=False 保住中文）
        lines_out: list[str] = []
        for i in range(row_count):
            obj: dict[str, str] = {}
            for input_name, json_key in zip(_INPUT_NAMES, _JSON_KEYS):
                rows = all_rows[input_name]
                obj[json_key] = rows[i] if i < len(rows) else ""
            lines_out.append(json.dumps(obj, ensure_ascii=False))

        # 合并输出在本体，其余 6 个通道位填空串 / 0
        return ("\n".join(lines_out), 0, "", "", "", 0, 0)

    # ── 拆分：1 行 JSON → 各路输出（复刻 passthrough_split.py::split）───
    def _split(self, kwargs: dict) -> tuple:
        start = int(kwargs.get("start_index", 0) or 0)
        max_rows = int(kwargs.get("max_rows", 1000) or 1000)
        rm_empty = bool(kwargs.get("remove_empty_lines", True))

        raw = kwargs.get("JSON行")
        if raw is None:
            raw = ""
        if not isinstance(raw, str):
            raw = str(raw)

        # 与合并模式同一套行窗口语义：过滤空行 → 取 [start, start+max_rows) →
        # 窗口第一行即「当前行」。单行输入的典型用法下与 passthrough_split.py
        # 完全等价（0 号行 = 原实现直接 json.loads 整串），多行输入则支持
        # start_index 直接选第 N 行，正好和合并模式互逆。
        lines = raw.split("\n")
        if rm_empty:
            lines = [ln for ln in lines if ln.strip()]
        window = lines[start:start + max_rows] if 0 <= start < len(lines) else []
        row = window[0] if window else ""

        try:
            data = json.loads(row.strip())
        except (json.JSONDecodeError, AttributeError):
            data = {}
        # 合法 JSON 但不是对象（"12" / "[...]"）→ 原实现会在 data.get 处抛 AttributeError，
        # 这里统一按「读不到键」处理，等价于空对象（对 dict 输入行为完全一致）
        if not isinstance(data, dict):
            data = {}

        def get_int(key: str, default: int = 0) -> int:
            try:
                return int(data.get(key, default))
            except (ValueError, TypeError):
                return default

        def get_str(key: str) -> str:
            return str(data.get(key, ""))

        # 顺序与 RETURN_NAMES 对齐：合并输出留空
        # （旧 JSON 行里若还带「画师」字段，读不到键就跳过，其余 6 字段照旧还原）
        return (
            "",                                        # 合并输出
            get_int("种子", _SEED_DEFAULT),             # 种子  INT
            get_str("提示词"),                          # 提示词 STRING
            get_str("反推"),                            # 反推   STRING
            get_str("分辨率"),                          # 分辨率 STRING
            get_int("宽度", _SIZE_DEFAULT),             # 宽度   INT
            get_int("高度", _SIZE_DEFAULT),             # 高度   INT
        )


NODE_CLASS_MAPPINGS = {"AnimaBatchBus": AnimaBatchBus}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaBatchBus": "Anima批量总线"}
