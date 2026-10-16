"""
02_artist_index.py —— 统一三处画师加载实现
==========================================
现状：画师索引用了 3 套彼此独立的实现，其中两套是 O(n) 全文件扫描：

  1. anima_weaver.py::_load_artists()
       一次性读全表到 list —— 这个是对的，但只在 anima_weaver 里
  2. artist_seed.py::_get_artist_count()
       每次调用扫一遍 804 KB 文件数 @ 开头的行
  3. artist_seed.py::_get_artist_name(idx)
       **每查一个画师扫一遍 804 KB 文件**，实测 9~23 ms/次
       批量 100 个种子 = 100 次全文件扫描 ≈ 1~2 s

    另外 anima_weaver 和 artist_seed 各自持有一份 artist 列表（内存里有两份 59k 条）。

改后：一个模块级单例，进程内只加载一次，O(1) 序号查名字。

改法：
  # artist_seed.py
  - from .artist_index import count, name, pick
  - _get_artist_count()  -> count()
  - _get_artist_name(i)  -> name(i)

  # anima_weaver.py
  - from .artist_index import name
  - _load_artists()      -> 删掉，直接用 name(idx)
"""

from __future__ import annotations

import os
import random
import threading
from typing import Optional

_FALLBACK_COUNT = 59676
_lock = threading.Lock()

_LIST: Optional[list[str]] = None
_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "tags", "Anima2B_Artist_Index_59k.txt")


def _load() -> list[str]:
    """
    只读一次。文件格式：一行一个 @画师名，跳过注释/空行/说明行。
    用列表存而不是 dict —— 59k 条按序号随机访问，list 更省内存。
    """
    global _LIST
    if _LIST is not None:
        return _LIST
    with _lock:
        if _LIST is not None:
            return _LIST
        out: list[str] = []
        try:
            with open(_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # 原实现的过滤条件：非空、非 # 注释、非 "This" 开头说明行
                    if not line or line.startswith("#") or line.startswith("This"):
                        continue
                    if line.startswith("@"):
                        out.append(line)
        except OSError as e:
            print(f"[Anima] artist index load failed: {e}")
            out = []
        _LIST = out
        return out


def count() -> int:
    """画师总数。加载失败时退回硬编码值（和原实现一致）。"""
    n = len(_load())
    return n if n > 0 else _FALLBACK_COUNT


def name(idx: int) -> str:
    """按 1-based 序号取画师名，O(1)。越界返回 '#idx'（保持原行为）。"""
    lst = _load()
    if not lst:
        return f"#{idx}"
    i = idx - 1
    if i < 0 or i >= len(lst):
        return f"#{idx}"
    return lst[i]


def pick(artist_seed: int, rng: Optional[random.Random] = None) -> tuple[int, str, str]:
    """
    统一 artist_seed.py::_pick_one 的语义，返回 (index, status_line, line)。
      -1 = 随机 / 0 = 无画师 / >=1 = 固定序号
    """
    n = count()
    if artist_seed == 0:
        return (0, "", "")
    if artist_seed == -1:
        r = rng or random
        s = r.randint(1, n)
    else:
        s = max(1, min(int(artist_seed), n))
    line = f"[{s}] {name(s)}"
    return (s, line, line)


def line(idx: int) -> str:
    """批量模式用的一行文本 '[序号] @画师名'。"""
    return f"[{idx}] {name(idx)}"


def reset() -> None:
    """只给测试/热重载用：清掉缓存强制重新加载。"""
    global _LIST
    _LIST = None
