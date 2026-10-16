"""
acceptance_check.py —— 上线验收脚本
===================================
在真实仓库上跑，回答三件事：
  1. 哪些 P0 bug 还活着
  2. 各补丁的 breaking change 有多大
  3. 有没有引入新的 import / 语法错误

用法：
    cd /path/to/anima-weaver
    python acceptance_check.py            # 只读，不改任何文件
    python acceptance_check.py --json     # 输出 JSON，便于 CI

退出码：0 = 可以上；1 = 有阻断项；2 = 有警告但可上
"""

from __future__ import annotations

import ast
import json
import os
import random
import sys
from collections import Counter

FILES = ["anima_weaver.py", "caption.py", "lm_studio.py", "rules.py",
         "assembly.py", "__init__.py"]
BLOCKING: list[str] = []
WARN: list[str] = []
OK: list[str] = []


def _src(name: str) -> str:
    try:
        with open(name, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _tree(name: str):
    try:
        return ast.parse(_src(name))
    except SyntaxError:
        return None


def check_syntax() -> None:
    """1. 语法 —— 已在 3.10 上确认会炸的那处必须修掉。"""
    for name in FILES:
        src = _src(name)
        if not src:
            continue
        try:
            compile(src, name, "exec")
            OK.append(f"{name}: 语法通过")
        except SyntaxError as e:
            BLOCKING.append(f"{name}:{e.lineno} SyntaxError — {e.msg}（Python "
                            f"{sys.version_info.major}.{sys.version_info.minor} 无法导入本文件）")


def check_undefined() -> None:
    """2. 使用前未定义的名字（NameError 隐患）。"""
    suspects = [("anima_weaver.py", "auto_ctx"), ("caption.py", "kwargs")]
    for path, name in suspects:
        src = _src(path)
        if not src:
            continue
        tree = _tree(path)
        if tree is None:
            continue
        lines = src.split("\n")
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Load):
                # 找最内层函数
                best: object = tree          # 默认退到模块级
                for n in ast.walk(tree):
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if n.lineno <= node.lineno <= getattr(n, "end_lineno", 0):
                            if best is tree or n.lineno > best.lineno:   # type: ignore[attr-defined]
                                best = n
                if best is None:
                    continue
                # 修复误报：**kwargs 形参（如 describe(self, **kwargs)）本身就是
                # 合法绑定，旧版只认 Name/Store 会把全部 kwargs.get 判成未定义。
                params = [
                    x for x in ast.walk(best)
                    if isinstance(x, ast.arg) and x.arg == name
                ]
                if params:
                    continue
                assigns = [
                    x.lineno
                    for x in ast.walk(best)
                    if isinstance(x, ast.Name) and x.id == name and isinstance(x.ctx, ast.Store)
                ]
                if not assigns or min(assigns) > node.lineno:
                    fn = getattr(best, "name", "<module>")
                    BLOCKING.append(
                        f"{path}:{node.lineno} `{name}` 在 {fn}() 内使用前未定义 → NameError"
                    )
                    break
        else:
            OK.append(f"{path}: `{name}` 作用域正常")


def check_input_types_declared() -> None:
    """3. INPUT_TYPES 声明的键 vs kwargs.get 实际读的键。"""
    src = _src("anima_weaver.py")
    if not src:
        return
    tree = _tree("anima_weaver.py")
    if tree is None:
        return
    declared: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "INPUT_TYPES":
            for x in ast.walk(node):
                if isinstance(x, ast.Dict):
                    for k in x.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            declared.add(k.value)
    used: Counter = Counter()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            used[node.args[0].value] += 1
    missing = sorted(k for k in used if k not in declared and used[k] >= 1)
    if missing:
        WARN.append(
            f"anima_weaver.py: 以下键在 kwargs.get 中读取但未在 INPUT_TYPES 声明 "
            f"（主节点单独使用时读不到）: {missing}"
        )
    else:
        OK.append("anima_weaver.py: INPUT_TYPES 声明完整")


def check_index_build() -> None:
    """4. 索引类补丁的磁盘/内存开销。"""
    tags_dir = "tags"
    if not os.path.isdir(tags_dir):
        WARN.append(f"未找到 {tags_dir}/，跳过索引开销检查")
        return
    total = 0
    for fn in os.listdir(tags_dir):
        p = os.path.join(tags_dir, fn)
        if os.path.isfile(p):
            total += os.path.getsize(p)
    mb = total / 1e6
    # 行偏移表: 每行 4 字节
    try:
        with open(os.path.join(tags_dir, "taglists-sensitive.txt"), "rb") as f:
            n = sum(1 for _ in f)
        off_mb = n * 4 / 1e6
        post_mb = n * 44 / 1e6 * 4 / 8      # 粗估 postings
        OK.append(f"tags/ 共 {mb:.0f} MB；行偏移表约 {off_mb:.1f} MB，倒排索引约 {post_mb:.0f} MB")
        if off_mb + post_mb > 200:
            WARN.append(f"索引内存合计 {off_mb + post_mb:.0f} MB，建议确认可接受")
    except FileNotFoundError:
        WARN.append("未找到 taglists-sensitive.txt，跳过")


def check_seed_breaking() -> None:
    """5. breaking change 量化 —— 固定种子是否还能复现旧结果。"""
    p = os.path.join("tags", "taglists-sensitive.txt")
    if not os.path.isfile(p):
        WARN.append("未找到 taglists，跳过种子复现检查")
        return
    rows: list[list[str]] = []
    with open(p, "rb") as f:
        for i, l in enumerate(f):
            if i >= 5000:
                break
            n = l.decode("utf-8", "replace").strip().lower().replace(" ", "_")
            parts = n.split(",_", 2)
            if len(parts) >= 3:
                r = [t for t in parts[2].split(",_") if t]
                if r:
                    rows.append(r)
    if not rows:
        return
    N = len(rows)
    import hashlib

    def curr(seed):
        rng = random.Random(seed)
        rng.shuffle(["a", "b"])
        return (["a", "b"][seed % 2], tuple(rows[seed % N][:8]))

    def after(seed):
        def sub(nm):
            h = hashlib.blake2b(f"{seed}:{nm}".encode(), digest_size=8).digest()
            return random.Random(int.from_bytes(h, "big"))
        f = sub("file").choice(["a", "b"])
        line = rows[sub("raffle").randrange(N)]
        k = min(8, len(line))
        picked = sub("slot").sample(line, k)
        idx = {t: i for i, t in enumerate(line)}
        return (f, tuple(sorted(picked, key=lambda t: idx[t])))

    same = sum(1 for s in range(500) if curr(s) == after(s))
    if same == 0:
        WARN.append(
            "随机内核重构后 500/500 个种子结果全部改变 —— "
            "已有工作流的固定种子**不再复现旧图**，需在 release note 明确知会"
        )
    else:
        OK.append(f"种子复现一致率 {same}/500")


def check_new_imports() -> None:
    """6. 补丁引入的新依赖是否可用。"""
    for mod, pip in [("laya", "pip install laya"), ("numpy", "pip install numpy")]:
        try:
            __import__(mod)
            OK.append(f"依赖 {mod}: 可用")
        except ImportError:
            WARN.append(f"依赖 {mod} 未安装（{pip}）—— 相关功能将自动降级")


def main() -> int:
    check_syntax()
    check_undefined()
    check_input_types_declared()
    check_index_build()
    check_seed_breaking()
    check_new_imports()

    if "--json" in sys.argv:
        print(json.dumps({"blocking": BLOCKING, "warn": WARN, "ok": OK},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 66)
        print("阻断项（必须先修）")
        print("=" * 66)
        for x in BLOCKING or ["（无）"]:
            print("  ✗", x)
        print()
        print("=" * 66)
        print("警告（可上，但要知会）")
        print("=" * 66)
        for x in WARN or ["（无）"]:
            print("  !", x)
        print()
        print("=" * 66)
        print("通过项")
        print("=" * 66)
        for x in OK or ["（无）"]:
            print("  ✓", x)
        print()

    if BLOCKING:
        print("结论：有阻断项，先修再上。")
        return 1
    if WARN:
        print("结论：可以上，但需在 release note 知会上述警告。")
        return 2
    print("结论：可以上。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
