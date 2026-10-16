# -*- coding: utf-8 -*-
"""tools/bench.py —— 性能基准

合成 100 000 行 / 结构与真实 taglist 一致的文件，测：
  1) 倒排索引构建（顺序批量读，应 <1.0s）
  2) read_line（句柄复用后应 <4 µs/次）
  3) 全量扫描（不应再被自动触发；只做参照量级展示）

用法：python tools/bench.py [合成文件路径]
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tag_index import TagIndex                      # noqa: E402
from tag_extract import InvertedIndex, _scan, fast_parse_line  # noqa: E402

try:
    import resource
    def rss():
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
except ImportError:                          # Windows 无 resource 模块
    def rss():
        try:
            import ctypes
            class C(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_size_t), ("pgmin", ctypes.c_size_t)]
            c = C(ctypes.sizeof(C), 0)
            ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(c), c.cb)
            return c.pgmin / 1024.0
        except Exception:
            return -1.0


def gen(path, n=100_000):
    if os.path.exists(path):
        return path
    random.seed(7)
    V = [f"tag_{i:05d}" for i in range(3000)] + [
        "1girl", "solo", "blonde_hair", "blue_eyes", "smile"]
    with open(path, "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(f"{i}, {random.randint(0, 100)}, "
                    + ", ".join(random.sample(V, random.randint(20, 60))) + "\n")
    return path


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tools", "_bench_taglists.txt")
    print("合成语料:", p)
    t0 = time.perf_counter()
    gen(p)
    print(f"生成耗时: {time.perf_counter()-t0:.1f}s")
    idx = TagIndex.load_or_build(p)
    print("lines:", idx.count)

    # 1) 倒排索引构建（一次 open 顺序读）
    t0 = time.perf_counter()
    InvertedIndex.build(idx.iter_lines(), idx.count)
    dt = time.perf_counter() - t0
    print(f"build: {dt:.2f}s  RSS {rss():.0f} MB   （期望 <1.0s）")

    # 2) read_line 句柄复用
    for i in range(300):                       # 预热页缓存
        idx.read_line(i * 7 % idx.count)
    best = 1e9
    for _ in range(3):
        t0 = time.perf_counter()
        for i in range(2000):
            idx.read_line(i * 37 % idx.count)
        best = min(best, (time.perf_counter() - t0) / 2000 * 1e6)
    print(f"read_line: {best:.1f} us/次   （期望 <5us；机器负载高时会偏高）")

    # 3) 全量扫描参照（生产路径已不再自动触发）
    rng = random.Random(1)
    must = {"tag_00001", "tag_00002"}
    t0 = time.perf_counter()
    _scan(idx, rng, list(must), [], lambda t: must.issubset(set(t)))
    dt = time.perf_counter() - t0
    print(f"scan(参照,不应自动触发): {dt:.2f}s -> 若每种子一次,批量256={dt*256:.0f}s")


if __name__ == "__main__":
    main()
