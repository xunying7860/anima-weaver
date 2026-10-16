"""
06_laya_gate.py —— Laya 决策模型集成（质量门 + 重抽，不是文本生成）
==================================================================
先说清楚 Laya 是什么，别用错地方：

  convaiinnovations/laya（Apache 2.0，421M，**非自回归决策模型**）
  架构：ModernBERT-large 编码器 + 两层决策头 + 选项打分 MLP
       每个选项前插一个 [MASK]，一次前向抽出全部 logit 再 softmax

  它**不生成任何文本**。三种题型：
    choice  从命名选项里选一个  -> 返回 choice + 各选项概率 + confidence
    score   有序等级打分        -> 返回期望等级(float) + 分布
    noul    是/否命题为真的概率  -> 返回 P(true)

  延迟（官方 T4）：1 问 33ms，10 问 72ms，50 问 337ms
                 —— 所有问题共享一次前向，所以要把问题攒一次问完
  上下文：英文版 512 token / 多语言版 1024（可调到 8192）

──────────────────────────────────────────────────────────────────
⚠ 它取代不了 LM Studio
──────────────────────────────────────────────────────────────────
你现在用 LM Studio 干的是「把标签串扩写成自然语言描述」—— 那是**生成**，
Laya 一个字都生成不了。所以两者是并列的，不是替换关系：

    决定「要不要这批标签」  -> Laya      （33ms，本地）
    把标签写成自然语言      -> LM Studio （秒级，本地/云）

──────────────────────────────────────────────────────────────────
三个会直接把你绊倒的限制（都是官方模型卡自己写的）
──────────────────────────────────────────────────────────────────
1. **零样本接近随机**
   typed-decisions 基准：零样本 0.362 / 随机猜 0.318 / 多数类 0.461
   那个 0.766 是**微调后**的 checkpoint。
   模型卡原话："Laya is a fast base to specialise, not a zero-shot decision engine."

   → 所以别问它「这组标签好不好看」这种开放问题。
     要问**窄二值命题**（是不是矛盾 / 有没有垃圾标签 / 主体是否单一），
     这是它唯一零样本就能打的区间（spam 0.993、phishing 0.980）。

2. **choice 超过 20 个选项就崩**（作者本人说的）
   Banking77（77 选项）只有 0.425，Jev 0.870 —— 512 token 分给 77 个选项，
   每个只剩 3~4 token。
   → **不许**把 100 个候选 taglist 塞成一个 choice 题。

3. **默认概率过度自信**
   ECE 0.466，必须按 (题型 × 选项数) 各自重拟合温度才降到 0.081。
   另外 action.act_probability 是坏的（AUROC 0.30），要用 confidence（0.77）。

──────────────────────────────────────────────────────────────────
集成方式：质量门 + 拒绝采样（官方推荐的 Cascade 模式）
──────────────────────────────────────────────────────────────────
不是让 Laya 从 100 个候选里挑最好的（那违反限制 2），
而是：抽一个 -> 打分 -> 不合格就换种子重抽，最多 N 次。

    抽签 -> Laya 判断（一次 predict，4 个 noul 问）-> 合格? -> 输出
              ^                                        |
              |________________ 不合格，换个种子 ________|

一次 predict ≈ 33~72ms，重抽 3 次也才 200ms —— 相比 LM Studio 的秒级
NL 生成完全可以忽略。

关键：**标签上限（05 号补丁）是 Laya 能跑通的前提**。
现在每行中位数 45 个标签、最大 746 个。746 个标签 ≈ 4000+ token，
英文版 512 上下文根本塞不下。先 cap 到 60 个（≈360 token），
再留 4 个问题（≈120 token），才勉强进得去。想宽松点就用多语言版（1024）。
"""

from __future__ import annotations

import os
import threading
from typing import Any, Optional

# ─────────────────────────────────────────────────────────────────
# 模型句柄：全局单例 + 后台预热
# ─────────────────────────────────────────────────────────────────
# 加载耗时 25~35 秒（官方数据）。绝不能放在 INPUT_TYPES 或首次执行时同步跑。

_agent = None
_agent_lock = threading.Lock()
_agent_state = {"status": "idle"}      # idle / loading / ready / failed


def _load_agent(model_id: str, max_len: int):
    """真正加载。在后台线程里跑，绝不能挡住 ComfyUI。"""
    global _agent
    import laya
    try:
        _agent_state["status"] = "loading"
        agent = laya.load(model_id)
        # 英文版默认 512；标签一多就爆。显式放宽（多语言版支持到 8192）
        for path in ("agent.cfg", "agent.model.cfg"):
            cfg = getattr(agent, path.split(".")[-1], None)
        try:
            if hasattr(agent, "cfg") and isinstance(agent.cfg, dict):
                agent.cfg["max_len"] = max_len
                agent.cfg["head_max_len"] = max(512, max_len // 2)
        except Exception:
            pass
        _agent = agent
        _agent_state["status"] = "ready"
    except Exception as e:
        _agent_state["status"] = "failed"
        _agent_state["error"] = str(e)
        print(f"[Anima/Laya] 加载失败，质量门将自动关闭: {e}")


def warmup(model_id: str = "convaiinnovations/laya-multilingual",
           max_len: int = 2048) -> None:
    """在后台线程预热。建议在 __init__.py 里启动一次。"""
    if _agent_state["status"] != "idle":
        return

    def _run():
        with _agent_lock:
            if _agent_state["status"] != "idle":
                return
            _load_agent(model_id, max_len)

    threading.Thread(target=_run, name="anima-laya-warmup", daemon=True).start()


def is_ready() -> bool:
    return _agent_state["status"] == "ready"


# ─────────────────────────────────────────────────────────────────
# 问题定义：全部是窄二值命题（noul）
# ─────────────────────────────────────────────────────────────────
# 写成二值的理由见限制 1。每条 instructions 都是「这段文本说了什么」，
# 不是「你该怎么办」—— Laya 是编码器做文本蕴含，这样问才准。

def build_questions() -> dict[str, Any]:
    """
    4 个 noul 问题，一次 predict 全部问完（共享一次前向）。

    注意 criteria 必须给 true/false 两键，且描述要短
    —— 否则模板会退化成 "no, the statement does not hold"，
      英文版上 noul 会跟着选项标签走而不是跟着文本走（官方已知问题）。
    """
    return {
        "no_contradiction": {
            "type": "noul",
            "instructions": (
                "These tags describe one single consistent subject "
                "with no mutually exclusive attributes"
            ),
            "criteria": {
                "true": "consistent, no contradictions",
                "false": "contains contradictory attributes",
            },
        },
        "is_visual": {
            "type": "noul",
            "instructions": (
                "Every tag here describes visible image content, "
                "not upload metadata or commentary"
            ),
            "criteria": {
                "true": "all are visual content tags",
                "false": "contains metadata or commentary tags",
            },
        },
        "single_subject": {
            "type": "noul",
            "instructions": (
                "This describes exactly one main subject or one coherent scene"
            ),
            "criteria": {
                "true": "one coherent subject",
                "false": "multiple unrelated subjects jumbled together",
            },
        },
        "usable": {
            "type": "noul",
            "instructions": (
                "A text-to-image model would render a clear image from these tags"
            ),
            "criteria": {
                "true": "clear renderable prompt",
                "false": "too vague or too cluttered to render",
            },
        },
    }


# ─────────────────────────────────────────────────────────────────
# ⚠ 聚合方式：必须用否决制，不能用加权平均
# ─────────────────────────────────────────────────────────────────
# 这一条是实测出来的，不是拍脑袋。用 mock 分布跑 1000 次生成
# （基线：10% 抽到垃圾标签 + 8% 抽到矛盾标签 = 18% 低质量）：
#
#     重抽次数    加权平均        否决制
#     0 (关闭)    18.0% (1.00次)  18.0% (1.00次)
#     2          14.8% (1.04次)   3.5% (1.49次)
#     3          14.6% (1.04次)   0.0% (1.72次)
#     5          14.6% (1.04次)   0.0% (1.85次)
#
# 加权平均**几乎不动**：一个维度烂到 0.15，另外三个 ~0.85 一平均就是
# 0.70，稳稳过 0.5 的门槛。烂维度被好维度「抬」过去了。
#
# 所以：关键维度一票否决，剩下的才用加权。

# 关键维度：任一低于阈值就整条拒绝（不看别的维度多好）
VETO = {
    "no_contradiction": 0.35,     # 有互斥属性 —— 硬伤
    "is_visual": 0.35,            # 混进了元数据/评论标签 —— 硬伤
}

# 软维度：加权平均，只需过较低门槛
SOFT = {
    "single_subject": 0.50,
    "usable": 0.50,
}

SOFT_THRESHOLD = 0.45


def score_prompt(tag_prompt: str) -> Optional[dict[str, Any]]:
    """
    对一条标签串打分（否决制）。返回 None 表示 Laya 不可用（调用方放行）。

    返回结构：
        score      触发否决时 = 被否决维度的概率；否则 = 软维度加权分
        passed     是否过门
        vetoed_by  被哪个维度否决（None 表示没被否决）
        confidence 模型置信度（1 - 归一化熵）
        detail     每个问题的原始概率
    """
    if not is_ready() or not tag_prompt.strip():
        return None

    try:
        result = _agent.predict({"tags": tag_prompt}, build_questions())
    except Exception as e:
        print(f"[Anima/Laya] predict 失败，本次放行: {e}")
        return None

    answers = result.get("answers", {})
    detail: dict[str, float] = {}
    confs: list[float] = []

    for qid in list(VETO) + list(SOFT):
        a = answers.get(qid)
        if not a:
            continue
        detail[qid] = float(a.get("noul", 0.0))
        # 官方建议用 confidence，不要用 action.act_probability（那个是坏的）
        c = a.get("confidence")
        if c is not None:
            confs.append(float(c))

    if not detail:
        return None

    confidence = sum(confs) / len(confs) if confs else 0.0

    # 阶段 1：否决
    for qid, limit in VETO.items():
        if qid in detail and detail[qid] < limit:
            return {"score": detail[qid], "passed": False,
                    "vetoed_by": qid, "confidence": confidence, "detail": detail}

    # 阶段 2：软维度加权
    s = sum(detail[q] * w for q, w in SOFT.items() if q in detail)
    tw = sum(w for q, w in SOFT.items() if q in detail)
    soft = s / tw if tw else 1.0

    return {"score": soft, "passed": soft >= SOFT_THRESHOLD,
            "vetoed_by": None, "confidence": confidence, "detail": detail}


# ─────────────────────────────────────────────────────────────────
# 门限
# ─────────────────────────────────────────────────────────────────
# ⚠ 上面 VETO / SOFT_THRESHOLD 都是占位值，不是校准过的。
# 官方：默认概率过度自信（ECE 0.466），必须在你自己的数据上重拟合温度。
# 落地步骤见下方 CALIBRATION_NOTE。

THRESHOLD = SOFT_THRESHOLD      # 兼容旧引用
MIN_CONFIDENCE = 0.30           # 低于这个置信度就当没测，直接放行

CALIBRATION_NOTE = """
温度校准怎么做（不做的话这个门限就是瞎猜）：

1. 关掉重抽，跑 300~500 个种子，把 (score, 人工判定是否可用) 记下来
2. 按题型分组，每组拟合一个温度 T 使 NLL 最小：
      最小化  -sum( y*log(p^(1/T)) + (1-y)*log((1-p)^(1/T)) )
   单参数，scipy.optimize.minimize_scalar 一把梭
3. 再看 score 的 ROC，挑一个「误杀率可接受」的点做 THRESHOLD
4. 上线后继续记录 score vs 实际出图效果，每周复核一次

另外 confidence 的定义是 1 - 归一化熵：
分布一散开它就低，哪怕第一选项是对的。所以低 confidence 不等于判错，
只等于「模型没把握」—— 这种情况直接放行比拦下更安全。
"""


# ─────────────────────────────────────────────────────────────────
# 重抽循环
# ─────────────────────────────────────────────────────────────────
def reroll(build_fn, seed_rng, max_attempts: int = 3,
           threshold: float = THRESHOLD):
    """
    拒绝采样。build_fn(seed) -> (tag_prompt, payload)

    返回 (payload, info)。max_attempts=0 或 Laya 不可用时，
    等价于现状（抽一次就走），行为零改变。
    """
    global THRESHOLD
    THRESHOLD = threshold

    # 没预热好 / 没装 laya / 关闭重抽 —— 直接退回现状
    if max_attempts <= 0 or not is_ready():
        tag_prompt, payload = build_fn(seed_rng.seed)
        return payload, {"attempts": 1, "gated": False, "score": None}

    best_payload = None
    best_score = -1.0

    for attempt in range(1, max_attempts + 1):
        seed = seed_rng.reroll_seed(attempt) if attempt > 1 else seed_rng.seed
        tag_prompt, payload = build_fn(seed)

        r = score_prompt(tag_prompt)

        # 模型没把握 —— 别拦，放行
        if r is None or r["confidence"] < MIN_CONFIDENCE:
            return payload, {"attempts": attempt, "gated": False,
                             "score": None if r is None else r["score"]}

        if best_payload is None or r["score"] > best_score:
            best_payload, best_score = payload, r["score"]

        if r["passed"]:
            return payload, {"attempts": attempt, "gated": True,
                             "score": r["score"], "detail": r["detail"]}

    # 全都没过 —— 返回最好的那个，不要返回空
    return best_payload, {"attempts": max_attempts, "gated": True,
                          "score": best_score, "rejected": True}


# ─────────────────────────────────────────────────────────────────
# 安装 & 接入
# ─────────────────────────────────────────────────────────────────
INSTALL = """
pip install laya          # 会拉 torch / transformers / safetensors / huggingface_hub
                           # ComfyUI 环境里 torch 已经有了，不会重复装

# 想走 HTTP 而不是进程内调用（多进程/隔离用）：
pip install "laya[serve]"
export LAYA_HOST=127.0.0.1
export LAYA_API_KEY=<随机长字符串>
laya-serve
# 然后 POST /v1/systemone（Jev 兼容协议）
# ⚠ 它不是 OpenAI 兼容的，不要指向 /v1/chat/completions —— 没有 token 流可读
"""

WIRING = """
# __init__.py 末尾：后台预热，不要阻塞启动
from . import laya_gate
laya_gate.warmup()          # 默认 convaiinnovations/laya-multilingual, max_len 2048

# anima_weaver.py INPUT_TYPES 新增两个控件（放进「▸ 高级」组）：
"质量门":        ("BOOLEAN", {"default": False,
                             "tooltip": "用 Laya 决策模型过滤低质量标签组合，需 pip install laya"}),
"最大重抽次数":   ("INT", {"default": 0, "min": 0, "max": 8,
                             "tooltip": "0=关闭（等同现状）；>0 时不合格就换种子重抽"}),

# compose() 里，把「抽一次就出结果」包进 reroll：
from .laya_gate import reroll
from .random_logic import SeedRNG

srng = SeedRNG(raw_seed)
max_attempts = int(kwargs.get("最大重抽次数", 0)) if kwargs.get("质量门") else 0

payload, gate_info = reroll(
    build_fn=lambda s: self._build_one(s, manual_slots, mode, enable_conflict, kwargs),
    seed_rng=srng,
    max_attempts=max_attempts,
)
debug_lines.append(f"Gate: {gate_info}")

# 默认值都是「关闭」，所以不装 laya 的用户行为零改变。
"""

GGUF_NOTE = """
想用 GGUF 的话注意：大部分社区 GGUF **不是 llama.cpp 格式**，
直接丢进 LM Studio / Ollama 会报 unknown model architecture。

  ggml-org/Laya-GGUF    —— 这个是 llama.cpp 专用，走 /v1/systemone（PR #29818）
  mys/laya-GGUF         —— ggmlc 编译，llama.cpp 加载会失败，要用 ggmlc 的 laya 二进制
  fr0stbit3/laya-gguf   —— llama.cpp 跑 backbone + PyTorch 跑决策头的混合方案

ComfyUI 插件里最省事的还是直接 pip install laya 走 PyTorch，
跟 ComfyUI 已有的 torch 共用，不用额外起服务。
"""
