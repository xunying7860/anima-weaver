# -*- coding: utf-8 -*-
"""
check_inputs.py —— anima_weaver.py 静态体检（防死参数/死控件复发）
=================================================================
- A 类：kwargs.get("X") 但 INPUT_TYPES 里没有 X → 死参数
  （四节点版曾命中：详细 NL 系统提示词、aspect_ratio —— 均已修）
- B 类：INPUT_TYPES 声明了 widget X，但 INPUT_TYPES 之外全文再无 "X"
  字面量 → 死控件（四节点版曾命中：场景类型 —— 已删）

判定口径（改判定前先读）：
- used 只认 kwargs/seed_kwargs/reroll_kwargs 这三个真实入参字典上的
  .get("字面量")；其余 .get（SeedRNG.get 子流名、os.environ.get、
  选项别名表 get、内部 _filter dict）一概不算，否则 must/artist/
  _filter 全是假阳性；
- declared 只取 INPUT_TYPES 函数里 required/optional 的**顶层**键，
  嵌套选项 dict 的 default/min/tooltip 不算 widget；
- 槽位类 widget 经 slot_keys 元组/循环变量间接读取，所以 B 类判
  「字面量是否出现在 INPUT_TYPES 函数体之外」而非「是否被字面 get」。

用法：python tools/check_inputs.py
退出码：0 = 两类均无；1 = 有报告项。
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "anima_weaver.py"

# 真实节点入参字典的变量名（其余 .get 不算读取节点输入）
RECVS = {"kwargs", "seed_kwargs", "reroll_kwargs"}
# 内部管道键：compose() 自写入 kwargs 下传，不属于 INPUT_TYPES
PIPE_KEYS = {"_filter", "_protected", "_preloaded"}


def literal_str(node):
    return (node.value if isinstance(node, ast.Constant)
            and isinstance(node.value, str) else None)


def find_input_types(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "INPUT_TYPES":
            return n
    return None


def collect_declared(it_fn):
    """required/optional 顶层键 = widget 名（其值应为 tuple）。"""
    declared = set()
    for n in ast.walk(it_fn):
        if not isinstance(n, ast.Dict):
            continue
        for k, v in zip(n.keys, n.values):
            if literal_str(k) in ("required", "optional") and isinstance(v, ast.Dict):
                for wk in v.keys:
                    s = literal_str(wk)
                    if s:
                        declared.add(s)
    return declared


def main() -> int:
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    it_fn = find_input_types(tree)
    if it_fn is None:
        print("找不到 INPUT_TYPES，体检失败")
        return 2

    declared = collect_declared(it_fn)

    used = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id in RECVS and n.args):
            s = literal_str(n.args[0])
            if s:
                used.add(s)

    class_a = sorted(used - declared - PIPE_KEYS)

    # B 类：widget 字面量在 INPUT_TYPES 函数体之外是否还存在
    it_span = (it_fn.lineno, it_fn.end_lineno)
    outside = "\n".join(line for i, line in enumerate(src.splitlines(), 1)
                        if not (it_span[0] <= i <= it_span[1]))
    class_b = sorted(d for d in declared
                     if not d.startswith("▸") and f'"{d}"' not in outside)

    print("A 类 死参数（kwargs.get 了但 INPUT_TYPES 没定义）:", class_a or "无")
    print("B 类 死控件（INPUT_TYPES 定义了但别处无人读）  :", class_b or "无")
    return 1 if (class_a or class_b) else 0


if __name__ == "__main__":
    sys.exit(main())
