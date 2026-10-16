"""
07_laya_finetune.py —— Laya 微调数据与训练方案
=============================================
先回答「是不是该先微调」：**是。我前面把微调当成可选增强，这个判断偏保守了。**

理由很硬：零样本基础版在 typed-decisions 上只有 **0.362**，
而随机猜是 0.318、多数类是 0.461。也就是说零样本的 laya 质量门
**不只是没用，是负收益** —— 它白白加了 33ms 延迟，还会随机拒掉好结果、
随机放过坏结果。模型卡原话："Laya is a fast base to specialise,
not a zero-shot decision engine."

所以正确顺序是：**确定性修复 → 生成训练数据 → 微调 → 集成**。
跳过微调直接上零样本门，不如不上。

────────────────────────────────────────────────────────────────
⚠ 但「先微调」不等于「先微调，其他都不用做」
────────────────────────────────────────────────────────────────
确定性修复是微调的**前置条件**，不是可选项：

  训练数据里现在有 5.3% 是元数据垃圾标签（commentary / absurdres /
  bad_id ...）。如果直接拿现状输出去训练，laya 会学到
  「commentary 是正常标签」。先跑黑名单，训练数据才干净。

  [:8] 的字母序偏差同理 —— 用它生成的数据训练，模型会把
  "a/b/c 开头的标签更常见" 当成真实分布。

────────────────────────────────────────────────────────────────
自动标注：不用人工标，但有个必须避开的陷阱
────────────────────────────────────────────────────────────────
你有 10 万行真实 Danbooru 标签行，天然就是「正例」——
这些标签在真实图片里确实共现过。负例可以合成。看起来完美，
但**最直觉的那种负例会毁掉整个微调**。

【陷阱】N1 跨行混拼（把两行各取一半拼起来）

    实测：随机拼出的角色对，在真实数据里出现过的比例 = **0.00%**

也就是说正负例可以被「这个组合我见没见过」**完美分开**。
模型不需要理解任何语义，只要记住共现表就能拿满分。

后果是灾难性的：部署时组合式抽样产出的全是**新组合**，
一个只会记忆的模型会把它们 100% 判为「不连贯」→ 全部重抽
→ 退化成整行抽取。组合式抽样带来的多样性**全部作废**，
白搭上 33ms 延迟。

【正确做法】N2 温和扰动（频率匹配 + 槽位匹配 + 只换 1~2 个 tag）

    正例：真实行
    负例：真实行，但把 1 个 tag 换成「同槽位 + 同频率带」的另一个 tag

    实测（500 组，看平凡特征能否判别）：
        负例类型                     仅用「平均 tag 频率」判别 AUC
        N1 跨行混拼                  0.540
        N2 换1个同槽同频 tag          0.522   ← 平凡特征几乎无效

    N2 的负例在频率、槽位结构上和正例完全一致，
    唯一的区别就是**语义上搭不搭**。模型只能真的去学语义。

    示例：
        原: 1girl, bikini, blue_eyes, blue_hair, blush, breasts, butt_crack
        换: 1girl, bikini, blue_eyes, blue_hair, blush, wide_hips, butt_crack
                                                    ^^^^^^^^^ 同槽同频，但不搭

────────────────────────────────────────────────────────────────
验证集必须包含「新组合」
────────────────────────────────────────────────────────────────
训练/验证都从「真实 vs 合成」切分的话，验证集也是同一分布，
看不出模型是不是在记忆。必须单独留一组**真实但训练时没见过的行**，
以及一组**组合式抽样真实产出的候选**做人工抽查。

    训练:  80% 真实行的 N2 扰动对
    验证A: 10% 真实行的 N2 扰动对（同分布，看拟合）
    验证B: 10% 真实行（从未参与训练）+ 组合式抽样产出
          ↑ 这个才是部署时的真实输入分布

如果在验证A 上 0.9 但在验证B 上 0.5，说明模型在记忆，白训了。

────────────────────────────────────────────────────────────────
数据量
────────────────────────────────────────────────────────────────
官方 laya-typed-decisions 用了 1200 case / 6000 decision 训到 0.766。
所以不是「几万条」才够，**几千条高质量 N2 对**就有机会。
建议：5000~10000 对起步，优先保证负例质量（N2）而非数量。

────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Optional


# ═════════════════════════════════════════════════════════════════
# 负例构造
# ═════════════════════════════════════════════════════════════════
class NegativeSampler:
    """
    按 slot + 频率带构造「温和扰动」负例。

    N2 的核心：换进去的 tag 和换出来的 tag 在
      - 槽位相同
      - 出现频率同带（按 freq//5 分桶，上限 20）
    所以任何基于频率、槽位分布、标签数的平凡判别器都失效，
    模型只能学语义冲突。
    """

    def __init__(self, freq: Counter, cat_map: dict, slot_map: dict,
                 bucket_size: int = 5, max_bucket: int = 20):
        self.freq = freq
        self.cat = cat_map
        self.slot = slot_map
        self.bs = bucket_size
        self.mb = max_bucket
        # (slot, freq_bucket) -> [tag...]
        self.buckets: dict[tuple, list[str]] = defaultdict(list)
        for t, c in freq.items():
            s = slot_map.get(cat_map.get(t, ""), "")
            if not s or s == "__filter__":
                continue
            self.buckets[(s, self._bucket(c))].append(t)

    def _bucket(self, c: int) -> int:
        return min(c // self.bs, self.mb)

    def swap(self, tags: list[str], rng: random.Random,
             n_swaps: int = 1) -> list[str]:
        """把 n_swaps 个 tag 换成同槽同频的另一个。返回 None-ish 表示没换成功。"""
        out = list(tags)
        done = 0
        for _ in range(50):
            if done >= n_swaps:
                break
            i = rng.randrange(len(out))
            t = out[i]
            s = self.slot.get(self.cat.get(t, ""), "")
            if not s or s == "__filter__":
                continue
            b = self._bucket(self.freq.get(t, 0))
            cands = self.buckets.get((s, b))
            if not cands:
                continue
            # 排除自己
            pick = cands[rng.randrange(len(cands))]
            if pick == t:
                continue
            out[i] = pick
            done += 1
        return out


# ═════════════════════════════════════════════════════════════════
# 数据集生成
# ═════════════════════════════════════════════════════════════════
def build_dataset(tag_index, cat_map, slot_map, n_pairs: int = 8000,
                  seed: int = 0, drop: Optional[frozenset] = None,
                  n_swaps: int = 1, val_ratio: float = 0.2):
    """
    生成 (state, label) 对。label: 1=连贯（真实行）, 0=不连贯（N2 扰动）

    ⚠ 调用前必须先跑垃圾标签黑名单（META_TAGS）和标签上限，
       否则训练数据本身就是脏的。
    """
    rng = random.Random(seed)

    # 频率表（用采样估计，别全量扫，太慢）
    freq: Counter = Counter()
    sample_n = min(6000, tag_index.count)
    for _ in range(sample_n):
        for t in tag_index.parse_line(rng.randrange(tag_index.count)):
            if drop and t in drop:
                continue
            freq[t] += 1

    ns = NegativeSampler(freq, cat_map, slot_map)

    rows: list[list[str]] = []
    seen: set[int] = set()
    while len(rows) < n_pairs and len(seen) < tag_index.count:
        i = rng.randrange(tag_index.count)
        if i in seen:
            continue
        seen.add(i)
        tags = tag_index.parse_line(i)
        if drop:
            tags = [t for t in tags if t not in drop]
        if len(tags) < 5:
            continue
        rows.append(tags)

    data = []
    for tags in rows:
        neg = ns.swap(tags, rng, n_swaps=n_swaps)
        # 换失败了就跳过（说明这行没有可替换的槽位 tag）
        if neg == tags:
            continue
        data.append({"tags": ", ".join(tags), "label": 1})
        data.append({"tags": ", ".join(neg), "label": 0})

    rng.shuffle(data)
    cut = int(len(data) * (1 - val_ratio))
    return data[:cut], data[cut:]


# ═════════════════════════════════════════════════════════════════
# 转成 laya 的 typed question 格式
# ═════════════════════════════════════════════════════════════════
def to_laya_items(data: list[dict]) -> list[dict]:
    """
    转成 laya 微调接受的格式。一个问题，noul 原语（最强的那个，0.857）。

    指令要写成「这段文本说了什么」，不是「你该怎么办」——
    Laya 是编码器做文本蕴含，这样问才准。
    """
    items = []
    for d in data:
        items.append({
            "state": {"tags": d["tags"]},
            "questions": {
                "coherent": {
                    "type": "noul",
                    "instructions": (
                        "These tags describe one coherent subject or scene "
                        "where every tag fits with the others"
                    ),
                    "criteria": {
                        "true": "coherent, all tags fit together",
                        "false": "some tag does not fit the others",
                    },
                }
            },
            "answers": {"coherent": bool(d["label"])},
        })
    return items


# ═════════════════════════════════════════════════════════════════
# 训练
# ═════════════════════════════════════════════════════════════════
TRAIN_PLAN = """
# 1. 装 SDK
pip install laya          # 官方有 Kaggle 2xT4 免费 notebook，约 4~5 小时

# 2. 生成数据（本模块）
train, val = build_dataset(idx, cat_map, slot_map, n_pairs=8000)
# ⚠ 必须先用 META_TAGS 黑名单过滤，否则训练数据是脏的

# 3. 微调（RLCD，严格评分规则）
#    官方 notebook 的流程：load base -> 喂 typed questions -> 拟合温度
#    温度必须按 (题型 × 选项数) 各自拟合，clamp [0.5, 5.0]

# 4. 验证 —— 两个验证集都要看
#    验证A: 同分布 held-out（看有没有拟合）
#    验证B: 组合式抽样真实产出 + 未参与训练的真实行（看是不是在记忆）
#
#    A 高 B 低 = 在记忆，白训了，回去改负例构造

# 5. 拟合温度后再定阈值（原始 ECE 0.466，校准后 0.081）
#    不校准就定阈值 = 瞎猜
"""

CHECKLIST = """
上线前逐条确认：

[ ] 垃圾标签黑名单已跑（5.3%），训练数据里没有 commentary/absurdres
[ ] 标签上限已应用（中位 45 → cap 60），否则 512 token 塞不下
[ ] 负例用的是 N2 温和扰动，不是 N1 跨行混拼
[ ] 验证B（新组合）上的表现达标，不只是验证A
[ ] 温度已按题型拟合，不是用默认 ECE 0.466 的概率
[ ] 门控用 confidence，不是 action.act_probability（后者 AUROC 0.30）
[ ] 连续 N 次不合格有兜底（退回整行抽取），不会让节点出不来结果
"""
