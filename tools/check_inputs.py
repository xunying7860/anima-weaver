"""
check_inputs.py —— anima_weaver.py 静态体检（防死参数/死控件复发）
=================================================================
静态解析 anima_weaver.py，报告两类问题：

- A 类：kwargs.get("X") 但 INPUT_TYPES 里没有 X → 死参数
  （2026-10-16 四节点版命中过：详细 NL 系统提示词、aspect_ratio）
- B 类：INPUT_TYPES 里有 widget Y，但全文件没人读 → 死控件
  （2026-10-16 四节点版命中过：场景类型）

用法：
    python tools/check_inputs.py

B 类需人工确认：compose() 可能用 kwargs.get 之外的路径取值
（例如形参默认值、**kwargs 透传），报出来先看一眼再动手删。
退出码：0 = 两类均无；1 = 有报告项。
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "anima_weaver.py"


def literal_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def main() -> int:
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)

    defined, used = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                s = literal_str(k)
                if s:
                    defined.add(s)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
            if n.args:
                s = literal_str(n.args[0])
                if s:
                    used.add(s)

    declared = {d for d in defined if not d.startswith("▸")}
    class_a = sorted(used - declared)
    class_b = sorted(d for d in declared
                     if d not in used and d not in {"模式", "标签比例"})
    print("A 类 死参数（读了但没定义）:", class_a or "无")
    print("B 类 死控件（定义了但没读）:", class_b or "无")
    print("（B 类需人工确认：compose 可能用 kwargs.get 之外的路径取值）")
    return 1 if (class_a or class_b) else 0


if __name__ == "__main__":
    sys.exit(main())
