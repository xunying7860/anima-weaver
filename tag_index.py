"""
tag_index.py —— 标签行偏移索引 + 分类字典缓存（P1）
====================================================
解决 _run_raffle 每次调用都「重新解析 categorized_tags.txt + 全量扫 taglist」的 IO 灾难：

现状（实测，tags/ 目录 216 MB / 每个 taglist ~10 万行 / 47~59 MB）：
    _run_raffle() 每次调用都做两件事：
      1. 重新解析 categorized_tags.txt（59575 条）   -> 34~68 ms
      2. 打开 taglist，逐行扫到 5000 行才 break      -> 55 ms
    合计 ~82 ms / 次；_compose_batch 对每个种子调一次：
        N=16  ->  1.3 s
        N=64  ->  5.2 s
        N=256 -> 21.0 s     （纯 IO/解析，还不含 LLM 推理）

    另一个隐藏问题：break 在 5000 行，而文件有 ~100000 行 —— 95% 的标签组合永远抽不到。

改后：
    - 行偏移表建一次（落盘 .idx 缓存），之后 pick 一次 seek+readline ≈ 0.05 ms
    - 分类字典模块级缓存，只解析一次
    - 抽签从「全量扫描」变成「随机探测」，解锁全部 ~10 万行（多样性 ×20）

用法（anima_weaver.py 里）：
    from .tag_index import get_tag_index, get_category_map, get_slot_map
    idx = get_tag_index(filepath)
    line = idx.read_line(i)
"""

from __future__ import annotations

import json
import os
import pickle
import random
import threading
from typing import Callable, Optional

# .idx 缓存版本号：解析规则变化时 +1，旧缓存自动失效
_IDX_VERSION = 2
_lock = threading.Lock()

# ── 进程级缓存 ──────────────────────────────────────────────────────
_CAT_CACHE: dict[str, dict] = {}      # tags_dir -> {tag: category}
_IDX_CACHE: dict[str, "TagIndex"] = {}  # filepath -> TagIndex


# ─────────────────────────────────────────────────────────────────
# 行偏移索引
# ─────────────────────────────────────────────────────────────────
class TagIndex:
    """
    一个 taglist 文件的「行号 -> 字节偏移」表。

    建表是全文件扫描（一次几十毫秒），但会落盘成 .idx 缓存文件，
    之后每次启动直接 pickle.load，毫秒级。
    """

    __slots__ = ("path", "offsets", "count", "mtime", "size", "_tls")

    def __init__(self, path: str, offsets: list, mtime: float, size: int):
        self.path = path
        self.offsets = offsets
        self.count = len(offsets)
        self.mtime = mtime
        self.size = size
        # P8-4: 按线程缓存文件句柄（8 µs/次 → 3 µs/次），仍线程安全
        self._tls = threading.local()

    def _handle(self):
        f = getattr(self._tls, "f", None)
        if f is None or f.closed:
            f = open(self.path, "r", encoding="utf-8", errors="replace")
            self._tls.f = f
        return f

    # ── 读取单行（O(1)）─────────────────────────────────────────
    def read_line(self, i: int) -> str:
        """按行号读取，只 seek 一次。线程安全（句柄按线程缓存）。"""
        f = self._handle()
        f.seek(self.offsets[i])
        return f.readline()

    def iter_lines(self):
        """顺序全量读（一次 open）；构建倒排索引专用，
        比 read_line×N 快 ~2.7x（P8-3：省掉 10 万次 open/close）。"""
        with open(self.path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line

    def parse_line(self, i: int) -> list:
        """读取并解析成归一化 tag 列表（与 tag_extract.fast_parse_line 等价）。"""
        norm = self.read_line(i).strip().lower().replace(" ", "_")
        parts = norm.split(",_", 2)
        if len(parts) < 3:
            return []
        return [t for t in parts[2].split(",_") if t]

    # ── 建表 / 缓存 ─────────────────────────────────────────────
    @classmethod
    def build(cls, path: str) -> "TagIndex":
        """全文件扫描建行偏移表（二进制模式，比文本模式快）。"""
        offsets: list = []
        # 二进制模式扫，比文本模式快；\n 是行尾，下一个字节即下一行开头
        with open(path, "rb") as f:
            offsets.append(0)
            while True:
                chunk = f.read(8 << 20)          # 8 MB
                if not chunk:
                    break
                start = f.tell() - len(chunk)
                pos = chunk.find(b"\n")
                while pos != -1:
                    offsets.append(start + pos + 1)
                    pos = chunk.find(b"\n", pos + 1)
            # 末行若没有换行符，最后一个 offset 指向文件尾，丢弃
            if offsets and offsets[-1] >= os.path.getsize(path):
                offsets.pop()
        st = os.stat(path)
        return cls(path, offsets, st.st_mtime, st.st_size)

    def _cache_path(self) -> str:
        return self.path + f".idx.v{_IDX_VERSION}"

    def save(self) -> None:
        """落盘 .idx 缓存（失败不致命，下次重建即可）。"""
        try:
            with open(self._cache_path(), "wb") as f:
                pickle.dump((self.mtime, self.size, self.offsets), f, protocol=4)
        except OSError:
            pass

    @classmethod
    def load_or_build(cls, path: str) -> "TagIndex":
        st = os.stat(path)
        cp = path + f".idx.v{_IDX_VERSION}"

        # 1) 进程内缓存（mtime/size 不变则直接复用）
        hit = _IDX_CACHE.get(path)
        if hit is not None and hit.mtime == st.st_mtime and hit.size == st.st_size:
            return hit

        # 2) 磁盘缓存
        if os.path.exists(cp):
            try:
                with open(cp, "rb") as f:
                    mtime, size, offsets = pickle.load(f)
                if mtime == st.st_mtime and size == st.st_size:
                    obj = cls(path, offsets, mtime, size)
                    _IDX_CACHE[path] = obj
                    return obj
            except Exception:
                pass

        # 3) 真建表
        obj = cls.build(path)
        obj.save()
        _IDX_CACHE[path] = obj
        return obj


def get_tag_index(path: str) -> TagIndex:
    """取（或建）指定 taglist 文件的行偏移索引。文件不存在抛 OSError。"""
    with _lock:
        return TagIndex.load_or_build(path)


# ─────────────────────────────────────────────────────────────────
# 分类字典缓存（categorized_tags.txt 只解析一次）
# ─────────────────────────────────────────────────────────────────
def get_category_map(tags_dir: str) -> dict:
    """
    categorized_tags.txt（格式 "[category] tag"）只解析一次，
    之后进程内复用；带磁盘缓存，重启后毫秒级恢复。
    文件缺失时返回 {}（调用方按「无分类」处理）。
    """
    hit = _CAT_CACHE.get(tags_dir)
    if hit is not None:
        return hit

    path = os.path.join(tags_dir, "categorized_tags.txt")
    cache_path = path + f".idx.v{_IDX_VERSION}"
    try:
        st = os.stat(path)
    except OSError:
        return {}

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                mtime, size, data = pickle.load(f)
            if mtime == st.st_mtime and size == st.st_size:
                _CAT_CACHE[tags_dir] = data
                return data
        except Exception:
            pass

    data: dict = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith("["):
                continue
            sep = line.find("] ")
            if sep == -1:
                continue
            data[line[sep + 2:].strip().lower().replace(" ", "_")] = line[1:sep]

    try:
        with open(cache_path, "wb") as f:
            pickle.dump((st.st_mtime, st.st_size, data), f, protocol=4)
    except OSError:
        pass

    _CAT_CACHE[tags_dir] = data
    return data


def get_slot_map(tags_dir: str) -> dict:
    """category_to_slot.json（1.7 KB，直接读即可，但也缓存一下）。"""
    key = tags_dir + "::slot"
    hit = _CAT_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        with open(os.path.join(tags_dir, "category_to_slot.json"),
                  "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    _CAT_CACHE[key] = data
    return data


# ─────────────────────────────────────────────────────────────────
# 抽签：随机探测代替全量扫描
# ─────────────────────────────────────────────────────────────────
def pick_taglist(
    idx: TagIndex,
    rng: random.Random,
    filter_fn: Optional[Callable[[list], bool]] = None,
    tries: int = 32,
) -> list:
    """
    在**全部** N 行里抽一行。有过滤条件时用「随机探测」：
    最多试 tries 次，每次一次 seek+readline（~0.05 ms），
    最坏 32 次 ≈ 1.6 ms —— 比全量扫 5000 行（55 ms）快 30 倍以上。

    返回 tag 列表；全部不命中则返回最后抽到的那行（保持行为不静默失败）。
    生产路径请用 tag_extract.pick_line（三级混合，严格满足过滤条件）。
    """
    fallback: list = []
    for _ in range(tries):
        i = rng.randrange(idx.count)
        tags = idx.parse_line(i)
        if not tags:
            continue
        if filter_fn is None or filter_fn(tags):
            return tags
        if not fallback:
            fallback = tags
    return fallback or idx.parse_line(rng.randrange(idx.count))


def make_filter(
    exclude_containing: set,
    must_include: set,
) -> Optional[Callable[[list], bool]]:
    """把两个过滤条件合成一个谓词；无条件时返回 None（省掉函数调用）。"""
    if not exclude_containing and not must_include:
        return None
    ex = exclude_containing or set()
    must = must_include or set()

    def fn(tags: list) -> bool:
        s = set(tags)
        if ex and not s.isdisjoint(ex):
            return False
        if must and not must.issubset(s):
            return False
        return True

    return fn


# ─────────────────────────────────────────────────────────────────
# 一次性预热（后台线程，不阻塞启动）
# ─────────────────────────────────────────────────────────────────
def warmup(tags_dir: str, filenames: list) -> None:
    def _run():
        import time
        t0 = time.perf_counter()
        get_category_map(tags_dir)
        for fn in filenames:
            try:
                get_tag_index(os.path.join(tags_dir, fn))
            except Exception:
                pass
        print(f"[Anima] tag index warmup: {time.perf_counter() - t0:.2f}s")

    threading.Thread(target=_run, name="anima-tag-warmup", daemon=True).start()
