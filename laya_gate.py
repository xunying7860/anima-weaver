"""
laya_gate.py —— Laya 决策模型质量门（可选，默认关闭）
======================================================
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
「把标签串扩写成自然语言描述」是**生成**，Laya 一个字都生成不了。
两者是并列的，不是替换关系：

    决定「要不要这批标签」  -> Laya      （33ms，本地）
    把标签写成自然语言      -> LM Studio （秒级，本地/云）

──────────────────────────────────────────────────────────────────
为什么默认关闭
──────────────────────────────────────────────────────────────────
零样本基础版在 typed-decisions 上只有 **0.362**（随机猜 0.318、
多数类 0.461）—— 零样本门**不只是没用，是负收益**：白加 33ms 延迟，
还随机拒掉好结果、随机放过坏结果。模型卡原话："Laya is a fast base
to specialise, not a zero-shot decision engine."

所以本模块：
  - 默认关闭：由 kwargs 键「启用laya门控」驱动（默认 False），
    不改 INPUT_TYPES（控件由母代理阶段 2 统一加）。
  - 加载必须后台线程（25~35 秒，绝不阻塞启动/首跑）。
  - laya 包/模型缺失时入口优雅降级，永不抛异常：
      judge_keep -> 保留原样

正确的启用顺序（先微调再开门）：
    确定性修复 -> 生成 N2 训练数据 -> 微调 -> 温度校准 -> 开「启用laya门控」

安装：
    pip install laya          # 会拉 torch / transformers / safetensors
                              # ComfyUI 环境里 torch 已经有了，不会重复装
"""

from __future__ import annotations

import threading
from typing import Optional

# ─────────────────────────────────────────────────────────────────
# 模型句柄：全局单例 + 后台预热
# ─────────────────────────────────────────────────────────────────
# 加载耗时 25~35 秒（官方数据）。绝不能放在 INPUT_TYPES 或首次执行时同步跑。

_agent = None
_agent_lock = threading.Lock()
_state = {"status": "idle", "error": ""}   # idle / loading / ready / failed

# 默认模型：多语言版（1024 上下文，标签串更塞得下）
DEFAULT_MODEL_ID = "convaiinnovations/laya-multilingual"


def _load_agent(model_id: str, max_len: int = 2048) -> None:
    """真正加载。只在后台线程里跑，绝不能挡住 ComfyUI。任何失败都降级为 failed。"""
    global _agent
    try:
        import laya
    except ImportError as e:
        # laya 包没装 —— 最常见的情况，安静降级
        _state["status"] = "failed"
        _state["error"] = f"laya 未安装: {e}"
        print("[Anima/Laya] laya 包未安装（pip install laya），质量门自动关闭")
        return
    try:
        _state["status"] = "loading"
        agent = laya.load(model_id)
        # 英文版默认 512；标签一多就爆。显式放宽（多语言版支持到 8192）
        try:
            if hasattr(agent, "cfg") and isinstance(agent.cfg, dict):
                agent.cfg["max_len"] = max_len
                agent.cfg["head_max_len"] = max(512, max_len // 2)
        except Exception:
            pass
        _agent = agent
        _state["status"] = "ready"
        print("[Anima/Laya] 模型加载完成，质量门就绪")
    except Exception as e:
        _state["status"] = "failed"
        _state["error"] = str(e)
        print(f"[Anima/Laya] 模型加载失败，质量门自动关闭: {e}")


def warmup(model_id: str = DEFAULT_MODEL_ID, max_len: int = 2048) -> None:
    """
    在后台线程预热（25~35 秒），不阻塞调用方。
    建议在 __init__.py 里启动一次（或首次打开「启用laya门控」时启动）。
    """
    with _agent_lock:
        if _state["status"] != "idle":
            return
        _state["status"] = "loading"

    def _run():
        _load_agent(model_id, max_len)

    threading.Thread(target=_run, name="anima-laya-warmup", daemon=True).start()


def is_ready() -> bool:
    return _state["status"] == "ready"


# ─────────────────────────────────────────────────────────────────
# 问题定义：全部是窄二值命题（noul）
# ─────────────────────────────────────────────────────────────────
# 写成二值的理由：零样本下只有窄二值能打（spam 0.993、phishing 0.980），
# 开放判断接近随机。每条 instructions 都是「这段文本说了什么」，
# 不是「你该怎么办」—— Laya 是编码器做文本蕴含，这样问才准。

def build_questions() -> dict:
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
# 实测（mock 分布 1000 次生成）：加权平均几乎不动（一个维度烂到 0.15，
# 另外三个 ~0.85 一平均就是 0.70，稳稳过 0.5 门槛），否决制 3 次重抽
# 就能把低质量率从 18% 压到 0%。所以：关键维度一票否决，剩下的才用加权。

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
MIN_CONFIDENCE = 0.30            # 低于这个置信度就当没测，直接放行

# ⚠ 上面阈值都是占位值，不是校准过的。
# 官方：默认概率过度自信（ECE 0.466），必须在你自己的数据上重拟合温度。
# 落地步骤：关掉重抽跑 300~500 个种子记录 (score, 人工判定) -> 按题型
# 拟合温度 -> ROC 挑阈值 -> 上线后每周复核。


def _score(tag_prompt: str) -> Optional[dict]:
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
    detail: dict = {}
    confs: list = []

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
# 入口（包/模型缺失时优雅降级，永不抛异常）
# ─────────────────────────────────────────────────────────────────
def judge_keep(tag_prompt: str, threshold: float = SOFT_THRESHOLD) -> str:
    """
    质量门（cascade 的第一级）。
      保留 -> 返回原串；拒绝 -> 返回 ""（调用方决定重抽或保留）。

    降级路径（全部返回原串，节点照常工作）：
      - 未启用 / laya 未装 / 模型未就绪 / predict 失败 -> 原样
      - 模型置信度低于 MIN_CONFIDENCE -> 原样（没把握比拦下更安全）
    """
    if not is_ready() or not tag_prompt.strip():
        return tag_prompt
    r = _score(tag_prompt)
    if r is None:
        return tag_prompt
    if r["confidence"] < MIN_CONFIDENCE:
        return tag_prompt
    return tag_prompt if r["passed"] else ""
