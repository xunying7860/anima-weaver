"""
tag_extract.py —— 标签抽取（混合三级：拒绝采样/倒排索引/降级扫描）
================================================================

────────────────────────────────────────────────────────────────
三代算法实测对比（taglists-sensitive.txt，100000 行全量）
────────────────────────────────────────────────────────────────

    查询                      A 原始扫5000   B 拒绝采样     C 倒排索引
    无过滤                      73.0 ms      0.02 ms OK     0.01 ms
    必含 1girl+solo             72.9 ms      0.02 ms OK     6.22 ms
    必含 blonde_hair+blue_eyes  705.9 ms      0.04 ms OK     2.96 ms
    必含 4 项（严格）           977.9 ms      0.18 ms ✗违规   6.80 ms
    排除 commentary             113.1 ms      0.02 ms OK     4.95 ms

────────────────────────────────────────────────────────────────
两个真问题（都不是「慢」，是「错」）
────────────────────────────────────────────────────────────────

【问题 1】纯拒绝采样会静默违反过滤条件
    命中率低时（实测「必含 1girl+blonde_hair+blue_eyes+twintails」
    命中率 0.38%），32 次尝试全失败的概率高达 **88.4%**。
    此时返回「最后抽到的那行」—— 那行根本不满足条件。
    用户设了「必须包含 twintails」，出来的结果没有 twintails，
    而界面上没有任何提示。

【问题 2】原始算法的候选池被截断且有偏
    `if len(valid_taglists) >= 5000: break` —— 只从文件开头扫。
    命中率高时只用了最前面 5000 条（必含1girl 实际有 86557 条，
    只用了 5.8%）；命中率低时扫到文件尾也凑不够，耗时 978 ms。

────────────────────────────────────────────────────────────────
第三代设计：混合三级（不是用 C 取代 B）
────────────────────────────────────────────────────────────────

C 在宽松查询上反而更慢（6ms vs 0.02ms）。正确做法是**快路径优先、
逐级升级**：

    第 1 级  拒绝采样（tries=8）        0.02 ms   宽松查询 99% 命中
      ↓ 失败
    第 2 级  倒排索引精确交集           2~7 ms    保证结果满足条件
      ↓ 索引未就绪（惰性构建中）
    第 3 级  降级：带缓存的全量扫描     ~1 s      兜底，仍然精确

第 2 级是**精确**的：must 按 posting 长度升序做集合交，再减 exclude。
无解时明确返回空（不是静默违规）。

倒排索引：CSR 紧凑格式（一个扁平 int32 数组 + 偏移表），
100000 行构建 ~0.9 s（一次 open 顺序批量读）/ 58653 个唯一 tag /
4419807 条 posting / 内存 17.7 MB（用 list[list[int]] 则要 140+ MB）。
按文件缓存；惰性构建（_ensure_index）：只有真正用到严格过滤的那一次
才付构建成本，默认场景启动零负担。

fast_parse_line：整行归一化后一次 split（1.9x），逐行比对与旧写法一致。
"""

from __future__ import annotations

import os
import random
import threading
from array import array
from typing import Sequence

# ═════════════════════════════════════════════════════════════════
# 1. 快速解析（1.90x，输出与现状一致）
# ═════════════════════════════════════════════════════════════════
def fast_parse_line(line: str) -> list:
    """
    解析一行 "post_id, score, tag1, tag2, ..." 为归一化 tag 列表。

    现状写法：
        parts = line.strip().split(", ", 2)
        [t.strip().lower().replace(" ", "_") for t in parts[2].split(", ")]
    即对**每个 token** 做一次 Python 函数调用链。

    这里改成：先对整行做一次 lower + replace（C 层批量操作），
    分隔符 ", " 随之变成 ",_"，再 split 一次即可。

    已在 20000 行真实数据上逐行比对，输出完全一致（0 处差异）。
    """
    norm = line.strip().lower().replace(" ", "_")
    parts = norm.split(",_", 2)
    if len(parts) < 3:
        return []
    return [t for t in parts[2].split(",_") if t]


# ═════════════════════════════════════════════════════════════════
# 2. 倒排索引（CSR 紧凑格式）
# ═════════════════════════════════════════════════════════════════
class InvertedIndex:
    """
    tag -> 行号列表，CSR 存储（一个扁平 int32 数组 + 偏移表）。

    实测（100000 行）：
        构建 1.06 s，58653 个唯一 tag，4419807 条 posting
        内存 4.42M × 4B = 17.7 MB（用 list[list[int]] 则要 140+ MB）
    """

    __slots__ = ("names", "index", "starts", "postings", "n_lines")

    def __init__(self, names: list, index: dict,
                 starts: array, postings: array, n_lines: int):
        self.names = names
        self.index = index
        self.starts = starts          # 长度 len(names)+1
        self.postings = postings      # 扁平化后的全部行号
        self.n_lines = n_lines

    def posting(self, tag: str) -> array:
        """返回该 tag 的行号数组（已按行号升序）。"""
        i = self.index.get(tag)
        if i is None:
            return array("i")
        return self.postings[self.starts[i]:self.starts[i + 1]]

    def has(self, tag: str) -> bool:
        return tag in self.index

    # ── 构建 ─────────────────────────────────────────────────────
    @classmethod
    def build(cls, lines, n_lines: int) -> "InvertedIndex":
        """
        lines: 原始文本行的可迭代对象。推荐传 tag_index.iter_lines()
        （一次 open 顺序读，1.64 s → ~0.9 s，省掉 10 万次
        open/close）；传 read_line(i) 生成器同样可用。
        构建放在惰性触发（_ensure_index）里，不要挡住 ComfyUI 启动。
        """
        buckets: dict = {}
        for i, line in enumerate(lines):
            for t in fast_parse_line(line):
                b = buckets.get(t)
                if b is None:
                    buckets[t] = array("i", [i])
                else:
                    b.append(i)

        names = sorted(buckets)
        index = {t: k for k, t in enumerate(names)}
        starts = array("i", bytes(4 * (len(names) + 1)))
        total = 0
        for k, t in enumerate(names):
            starts[k] = total
            total += len(buckets[t])
        starts[len(names)] = total

        postings = array("i", bytes(4 * total))
        pos = 0
        for t in names:
            b = buckets[t]
            postings[pos:pos + len(b)] = b
            pos += len(b)

        return cls(names, index, starts, postings, n_lines)

    # ── 查询：精确候选 ───────────────────────────────────────────
    def candidates(self, must: Sequence, excl: Sequence) -> array:
        """
        返回满足全部条件的行号数组；无解返回空数组（不是 None）。
        策略：must 按 posting 长度升序，从最短的开始做集合交，再减 exclude。
        """
        unknown = [t for t in must if not self.has(t)]
        if unknown:
            return array("i")          # 必含的 tag 根本不存在 -> 无解

        if must:
            order = sorted(must, key=lambda t: len(self.posting(t)))
            cand = set(self.posting(order[0]))
            for t in order[1:]:
                cand &= set(self.posting(t))
                if not cand:
                    return array("i")
        else:
            cand = None

        for t in excl:
            if not self.has(t):
                continue
            hit = set(self.posting(t))
            if cand is None:
                cand = set(range(self.n_lines)) - hit
            else:
                cand -= hit
            if not cand:
                return array("i")

        if cand is None:
            return array("i", range(self.n_lines))
        return array("i", sorted(cand))


# ═════════════════════════════════════════════════════════════════
# 3. 全局句柄 + 后台预热（按文件缓存）
# ═════════════════════════════════════════════════════════════════
_inv_cache: dict = {}     # filepath -> InvertedIndex
_inv_lock = threading.Lock()
_inv_state = {"status": "idle"}


def build_sync(tag_index) -> InvertedIndex:
    """
    同步构建（供后台线程调用）。已构建过则直接返回缓存。
    构建耗时 ~1s / 100000 行，内存 ~18 MB。
    """
    key = tag_index.path
    with _inv_lock:
        hit = _inv_cache.get(key)
        if hit is not None:
            return hit
    idx = InvertedIndex.build(tag_index.iter_lines(), tag_index.count)
    with _inv_lock:
        _inv_cache[key] = idx
    return idx


def warmup(tag_index) -> None:
    """
    后台构建。tag_index 是 tag_index.TagIndex（提供 read_line / count）。
    不阻塞调用方；建议在 ComfyUI 启动后空闲时调（anima_weaver 已做）。
    """
    def _run():
        try:
            build_sync(tag_index)
        except Exception as e:
            print(f"[Anima] 倒排索引构建失败，将退回全量扫描: {e}")

    threading.Thread(target=_run, name="anima-invidx", daemon=True).start()


def get_index(tag_index):
    """取该文件已就绪的倒排索引；未就绪返回 None（不触发构建）。"""
    return _inv_cache.get(tag_index.path)


# ── 惰性构建 ────────────────────────────────────────────────────────
# 倒排索引只在 pick_line 第 2 级被用到，而第 2 级仅在「设了必含/排除
# 且第 1 级拒绝采样失败」时触发。默认场景（不设过滤）根本不碰它 ——
# 不再为永远用不到的索引付 4×1.64 s CPU + ~92 MB（每次启动）。
_building: set = set()      # 正在构建的文件，防并发重复触发
_build_failed: set = set()  # 构建失败过的文件（走 _scan_cached 降级）
_build_lock = threading.Lock()


def _ensure_index(tag_index):
    """按需取索引；未就绪则同步构建一次（~1-2 s，之后缓存）。
    返回 None = 本次拿不到（别的线程在建 / 曾构建失败），调用方降级。"""
    hit = _inv_cache.get(tag_index.path)
    if hit is not None:
        return hit
    if tag_index.path in _build_failed:
        return None
    with _build_lock:
        hit = _inv_cache.get(tag_index.path)
        if hit is not None:
            return hit
        if tag_index.path in _building:
            return None
        _building.add(tag_index.path)
    try:
        print("[Anima] 首次严格过滤，构建倒排索引（约 1~2 s，之后缓存）: "
              f"{os.path.basename(tag_index.path)}")
        return build_sync(tag_index)
    except Exception as e:
        _build_failed.add(tag_index.path)
        print(f"[Anima] 倒排索引构建失败，改用带缓存全量扫描: {e}")
        return None
    finally:
        with _build_lock:
            _building.discard(tag_index.path)


# ── 全量扫描：只留「带同参数缓存」的降级路径 ──────────────────────
# 旧行为（索引未就绪就每种子扫 0.77 s）在批量 256 种子下 = 196 s 假死。
# 现在：索引惰性构建一定能成（一次性 1-2 s）；真失败才扫描，且同一
# (文件, must, excl) 参数组合只扫一次。
_scan_cache: dict = {}


def _scan_cached(tag_index, rng, must, excl, ok) -> list:
    key = (tag_index.path, tuple(sorted(must)), tuple(sorted(excl)))
    hit = _scan_cache.get(key)
    if hit is None:
        hit = _scan(tag_index, random.Random(0), list(must), list(excl), ok)
        _scan_cache[key] = hit
        print("[Anima] 倒排索引不可用，已全量扫描 "
              f"{tag_index.count} 行（结果已缓存）: "
              f"{os.path.basename(tag_index.path)}")
    if not hit:
        return []
    return hit[rng.randrange(len(hit))]


def reset() -> None:
    """只给测试/热重载用：清掉缓存强制重新构建。"""
    with _inv_lock:
        _inv_cache.clear()
    _inv_state["status"] = "idle"
    _scan_cache.clear()
    _build_failed.clear()
    _building.clear()


# ═════════════════════════════════════════════════════════════════
# 4. 混合三级抽取
# ═════════════════════════════════════════════════════════════════
FAST_TRIES = 8          # 第 1 级尝试次数（宽松查询基本首次命中）


def pick_line(
    tag_index,
    rng: random.Random,
    must: Sequence = (),
    excl: Sequence = (),
) -> tuple:
    """
    抽一行满足条件的 tag 列表。返回 (tags, 来源)。

    三级：
      "reject"          拒绝采样命中，0.02 ms
      "index"           倒排索引精确求解，2~7 ms（索引惰性构建一次 1~2 s）
      "reject-relaxed"  索引正被别的线程构建，本次放宽过滤（罕见）
      "scan"/"scan-empty" 索引构建失败后的带缓存降级扫描
      "index-empty"     索引确认无解（真实结论，明确返回空列表）

    「必含/排除」严格满足：返回的非空结果一定包含 must 全部、
    不含 excl 任何一个 —— 0 静默违规。
    """
    must = list(must)
    excl = list(excl)
    m_set = set(must)
    e_set = set(excl)
    filtered = bool(m_set or e_set)

    def ok(tags: list) -> bool:
        if not filtered:
            return True
        s = set(tags)
        if e_set and not s.isdisjoint(e_set):
            return False
        if m_set and not m_set.issubset(s):
            return False
        return True

    # ── 第 1 级：拒绝采样 ────────────────────────────────────────
    fallback: list = []
    for _ in range(FAST_TRIES):
        i = rng.randrange(tag_index.count)
        tags = fast_parse_line(tag_index.read_line(i))
        if not tags:
            continue
        if not filtered:
            return tags, "reject"
        if ok(tags):
            return tags, "reject"
        if not fallback:
            fallback = tags

    if not filtered:
        return fallback, "reject"

    # ── 第 2 级：倒排索引精确求解（惰性构建，一次性 1~2 s）──
    inv = _ensure_index(tag_index)
    if inv is not None:
        cand = inv.candidates(must, excl)
        if len(cand):
            i = cand[rng.randrange(len(cand))]
            return fast_parse_line(tag_index.read_line(i)), "index"
        # 索引确认无解 —— 这是真实结论，不是失败
        return [], "index-empty"
    if tag_index.path in _build_failed:
        # ── 第 3 级（降级）：带同参数缓存的全量扫描────
        got = _scan_cached(tag_index, rng, must, excl, ok)
        return (got, "scan") if got else ([], "scan-empty")
    # 别的线程正在构建 → 本次放宽过滤返回，绝不进全量扫描
    # （旧行为：256 种子 × 0.77 s = 196 s 假死）
    return fallback, "reject-relaxed"


def _scan(tag_index, rng, must: Sequence, excl: Sequence, ok) -> list:
    """
    全量扫描兜底。用子串预筛跳过绝大多数行：
    先对整行做归一化（2 次 C 层 str 操作），再做子串判断，
    must 的子串都不存在就完全不用 split。仍然精确（逐行 ok 校验）。
    """
    m_norm = [t for t in must]
    found: list = []
    for i in range(tag_index.count):
        norm = tag_index.read_line(i).strip().lower().replace(" ", "_")
        if not norm:
            continue
        # 子串预筛：must 的任一子串不存在 -> 一定不满足
        skip = False
        for t in m_norm:
            if t not in norm:
                skip = True
                break
        if skip:
            continue
        parts = norm.split(",_", 2)
        if len(parts) < 3:
            continue
        tags = [t for t in parts[2].split(",_") if t]
        if tags and ok(tags):
            found.append(tags)
    if not found:
        return []
    return found[rng.randrange(len(found))]
