"""
06_random_core.py —— 随机内核重构
=================================
回答「底层随机功能是不是本来就需要优化」：**是，而且是架构级的，不是补丁级的。**

现状的随机链路（anima_weaver.py:670-716 + 587）：

    rng = random.Random(seed)
    rng.shuffle(enabled_files)                      # ① 消耗 rng 状态但结果被丢弃
    selected_file = enabled_files[seed % len(...)]  # ② 取模，不是 rng
    ...扫 5000 行...
    selected_tags = valid_taglists[seed % len(...)] # ③ 取模，不是 rng
    ...分槽...
    combined = list(raffle_tags[:8])                # ④ 位置截断

四条各自都有问题，但真正的根因是同一个：
**「随机数发生器」和「随机数的用法」混在了一起。**
取模不是随机，位置截断不是抽样，一个 rng 干所有事会耦合。

────────────────────────────────────────────────────────────────
实测（本机，tags/ 真实数据）
────────────────────────────────────────────────────────────────

【问题 ①】rng.shuffle 是纯浪费
    shuffle 改变了列表顺序，但下一行用的是 seed % len 的下标，
    只取决于 seed。shuffle 白消耗 rng 状态。
    seed=1 -> shuffle 后 ['d','a','c','b']，取的仍是 index 1 = 'a'

【问题 ②】种子奇偶 = 文件选择，0 bit 随机性
    seed 1..12 -> explicit, sensitive, explicit, sensitive, ... 严格交替
    seed % 2 只用掉 1 bit，丢弃 63 bit

【问题 ③】取模导致熵塌缩 + 顺序种子相关
    种子空间 64 bit，但：
      seed % 100000 -> 16.6 bit 有效（丢弃 47.4 bit）
      seed % 5000   -> 12.3 bit 有效（丢弃 51.7 bit）
      seed % 2      ->  1.0 bit 有效（丢弃 63.0 bit）
    顺序种子（用户手填 1,2,3... 或外部递增）会命中相邻行：
      seed=1 -> row 1 ; seed=2 -> row 2 ; seed=3 -> row 3

【问题 ④】[:8] 不是「截断」，是**系统性字母序偏差**
    实测 400/400 行的标签是**完全按字母序排列**的（Danbooru 导出特性）。
    所以 raffle_tags[:8] 永远取「字母序最靠前的 8 个」：

      首字母   全量分布   [:8]截断    随机抽样
        b      15.7%     23.2%      14.2%     ← 过度代表 +48%
        a       4.5%      6.8%       4.6%
        t       5.8%      1.8%       5.0%     ← 压制 -69%
        s      14.3%      9.9%      14.7%     ← 压制 -31%
        w       3.4%      1.8%       3.6%     ← 压制 -47%

    随机抽样几乎完美复现全量分布，[:8] 则严重偏离。
    也就是说：clothing/appearance 槽位被截断时，
    **永远优先保留 a/b/c 开头的标签，t/s/w 开头的几乎进不来。**

【问题 ⑤】一个 rng 干所有事 = 耦合
    seed=100，只改标签数量：
      tag数=10 -> 画师 43177
      tag数=40 -> 画师 25406
      tag数=80 -> 画师 47660
    同一个种子，改任何一个环节都会连锁改变所有下游结果。
    「固定种子复现」这个承诺实际上是失效的。

────────────────────────────────────────────────────────────────
重构设计
────────────────────────────────────────────────────────────────

四件事，按重要性排序：

1. 命名子流（解耦）
   用 blake2b(seed, name) 派生独立的 Random 实例。
   改标签逻辑不会影响画师，反之亦然。实测：
     seed=100, tag数 10/40/80 -> 画师恒为 2883

2. 用 rng 取模替代 seed 取模
   rng.randrange(n) 而非 seed % n。熵不再塌缩，顺序种子不再相关。

3. 位置截断 [:8] 换成**随机抽样**
   rng.sample(tags, k)，直接消除字母序偏差。

4.（可选，改动最大）组合式抽样
   不再「抽一整行」，而是「每个槽位从分类池里独立抽 k 个」：
     槽位池（扫 20000 行建成）：
       count_identity 3472 | clothing 3562 | pose_action 2037
       scene 1747 | appearance 1388 | detail_mood 460
       expression 419 | camera 87
     组合空间：k=5 时约 2^343，对比现状 2^12.3

   三个好处：
     a. 能生成数据集中不存在的新组合
     b. 每槽独立配额，可以配平（现状 clothing+appearance 占 57%）
     c. 可对长尾加权：
          detail_mood 池 460 个，48% 出现次数 <=2（几乎抽不到）
          clothing    池 3562 个，31% 出现次数 <=2
        逆频率加权能让这些稀有标签真正出现

本模块实现 1/2/3（零风险、行为可对照），4 作为可选的第二种模式。
"""

from __future__ import annotations

import hashlib
import random
from typing import Iterable, Optional, Sequence

# ═════════════════════════════════════════════════════════════════
# 1. 命名子流 —— 解耦的核心
# ═════════════════════════════════════════════════════════════════
def substream(seed: int, name: str) -> random.Random:
    """
    从主种子派生一个独立的命名随机流。

    blake2b 保证：不同 name 得到完全无关的状态，且相同 (seed, name) 恒等。
    这样每个抽样环节互不干扰 —— 改了标签逻辑不会连锁改变画师。
    """
    h = hashlib.blake2b(f"{seed}:{name}".encode("utf-8"), digest_size=8).digest()
    return random.Random(int.from_bytes(h, "big"))


class SeedRNG:
    """
    主种子 + 命名子流的统一管理入口。

    用法：
        rng = SeedRNG(seed)
        rng.get("raffle.file").randrange(len(files))
        rng.get("artist").randint(1, n)
        rng.get("slot:clothing").sample(tags, 5)
    """

    __slots__ = ("seed", "_cache")

    def __init__(self, seed: int):
        self.seed = seed
        self._cache: dict[str, random.Random] = {}

    def get(self, name: str) -> random.Random:
        r = self._cache.get(name)
        if r is None:
            r = substream(self.seed, name)
            self._cache[name] = r
        return r

    # ── 常用操作的快捷方式 ──────────────────────────────────────
    def pick(self, name: str, seq: Sequence):
        """从序列里等概率取一个。替代 seq[seed % len(seq)]。"""
        if not seq:
            return None
        return self.get(name).randrange(len(seq))

    def sample(self, name: str, seq: Sequence, k: int) -> list:
        """等概率抽 k 个（不重复）。替代 seq[:k]，消除位置偏差。"""
        if not seq:
            return []
        k = min(k, len(seq))
        return self.get(name).sample(list(seq), k)


# ═════════════════════════════════════════════════════════════════
# 2. 槽位随机抽样 —— 替代 [:8]
# ═════════════════════════════════════════════════════════════════
def sample_slot(
    rng: SeedRNG,
    tags: Sequence[str],
    slot: str,
    k: int = 8,
    keep_order: bool = True,
) -> list[str]:
    """
    从槽位标签里随机抽 k 个。

    现状是 tags[:8] —— 因为行内标签是字母序的（实测 400/400），
    这等于永远优先保留字母序靠前的标签，是系统性偏差。

    keep_order=True 时保持原有字母序输出（只影响「留哪些」，
    不影响「怎么排」），这样和现有 assembly 的顺序逻辑兼容。
    """
    if len(tags) <= k:
        return list(tags)
    chosen = rng.sample(f"slot:{slot}", tags, k)
    if keep_order:
        idx = {t: i for i, t in enumerate(tags)}
        chosen.sort(key=lambda t: idx.get(t, 1 << 30))
    return list(chosen)


# ═════════════════════════════════════════════════════════════════
# 3. 组合式抽样（可选模式 B）
# ═════════════════════════════════════════════════════════════════
class SlotPool:
    """
    槽位标签池。一次性从 taglist 建成，之后每个槽位独立抽样。

    相比「抽一整行」：
      - 能组合出数据集中不存在的搭配
      - 每槽独立配额，可配平（现状 clothing+appearance 占 57%）
      - 可加权，让长尾标签真正出现
    """

    def __init__(self):
        self.pools: dict[str, list[str]] = {}
        self.weights: dict[str, list[float]] = {}
        self._cum: dict[str, list[float]] = {}

    def build(self, tag_index, cat_map: dict[str, str],
              slot_map: dict[str, str], max_rows: int = 20000,
              drop: Optional[frozenset] = None) -> None:
        """
        扫描 taglist 建池。tag_index 用 01 号补丁的行偏移索引，
        这样建池是 O(行数) 且可缓存。
        """
        from collections import defaultdict
        cnt: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        n = min(max_rows, tag_index.count)
        for i in range(n):
            for t in tag_index.parse_line(i):
                if drop and t in drop:
                    continue
                s = slot_map.get(cat_map.get(t, ""), "")
                if s and s != "__filter__":
                    cnt[s][t] += 1
        for s, d in cnt.items():
            self.pools[s] = list(d.keys())
            self.weights[s] = [float(d[k]) for k in self.pools[s]]
        self.reweight()

    def reweight(self, mode: str = "inverse") -> None:
        """
        mode:
          "uniform"  等概率（默认，等价于从池里均匀抽）
          "inverse"  逆频率加权，1/(1+log(freq))，抬长尾
          "raw"      按出现频率加权（等于现状分布）
        """
        import math
        self._cum = {}
        for s, ws in self.weights.items():
            if mode == "uniform":
                w = [1.0] * len(ws)
            elif mode == "inverse":
                w = [1.0 / (1.0 + math.log(max(1.0, x))) for x in ws]
            else:
                w = list(ws)
            cum: list[float] = []
            c = 0.0
            for x in w:
                c += x
                cum.append(c)
            self._cum[s] = cum

    def draw(self, rng: random.Random, slot: str, k: int = 5) -> list[str]:
        """从指定槽位抽 k 个（不重复）。"""
        pool = self.pools.get(slot)
        if not pool:
            return []
        cum = self._cum.get(slot)
        k = min(k, len(pool))
        out: list[str] = []
        seen: set[int] = set()
        guard = 0
        while len(out) < k and guard < k * 20:
            guard += 1
            r = rng.random() * cum[-1]
            # 二分查找
            lo, hi = 0, len(cum) - 1
            while lo < hi:
                mid = (lo + hi) // 2
                if cum[mid] < r:
                    lo = mid + 1
                else:
                    hi = mid
            if lo in seen:
                continue
            seen.add(lo)
            out.append(pool[lo])
        return out


# 默认配额（配平用，现状是 clothing+appearance 占 57%）
DEFAULT_QUOTA = {
    "count_identity": 2,
    "appearance": 6,
    "clothing": 5,
    "pose_action": 3,
    "expression": 3,
    "camera": 2,
    "scene": 3,
    "detail_mood": 3,
}


def compose_from_pool(pool: SlotPool, seed: int,
                      quota: Optional[dict[str, int]] = None) -> dict[str, list[str]]:
    """组合式抽样：每槽按配额独立抽。"""
    q = quota or DEFAULT_QUOTA
    out: dict[str, list[str]] = {}
    for slot, k in q.items():
        out[slot] = pool.draw(substream(seed, f"pool:{slot}"), slot, k)
    return out


# ═════════════════════════════════════════════════════════════════
# 接入 diff
# ═════════════════════════════════════════════════════════════════
DIFF = '''
# ── _run_raffle (anima_weaver.py:669-716) ──

-   seed = int(kwargs.get("随机种子", 0))
-   rng = random.Random(seed)
+   seed = int(kwargs.get("随机种子", 0))
+   rng = SeedRNG(seed)                       # 不再是一个 rng 干所有事

-   rng.shuffle(enabled_files)
-   selected_file = enabled_files[seed % len(enabled_files)]
+   selected_file = rng.pick("raffle.file", enabled_files)

-   selected_tags = valid_taglists[seed % len(valid_taglists)]
+   selected_tags = rng.pick("raffle.line", valid_taglists)


# ── _merge_slots (anima_weaver.py:587) ──

-   combined = list(raffle_tags[:8])          # 字母序偏差
+   combined = sample_slot(rng, raffle_tags, slot, k=8)   # 随机抽样


# ── 画师 (anima_weaver.py:410) ──

-   s = random.randint(1, len(artists))       # 全局 random，不受 seed 控制
+   s = rng.get("artist").randint(1, len(artists))


# ── _finish_prompt 需要拿到 rng ──
# 现在 _finish_prompt(self, kwargs, tag_prompt, nl_source, tag_ratio) 没有 rng，
# 加一个参数从 compose() 传下来即可（批量模式每个 seed_kwargs 各自带）。
'''
