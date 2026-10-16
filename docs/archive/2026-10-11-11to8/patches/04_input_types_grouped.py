"""
04_input_types_grouped.py —— AnimaWeaver 分组后的 INPUT_TYPES 参考实现
=====================================================================
配合 js/anima_groups.js 使用：把 40 个平铺控件收进 5 个可折叠分组。

三条硬约束（改的时候别违反）：

1. **顺序**：组开关（"▸ xxx"）必须排在它管理的 widget **前面**。
   INPUT_TYPES 的 dict 顺序就是前端 widget 顺序，Python 3.7+ dict 保序。

2. **默认值留空**：为了让旧工作流继续可用。
   compose() 的合并逻辑是
       if k not in kwargs or not str(kwargs.get(k, "")).strip():
           kwargs[k] = v
   即「widget 为空时才用 JSON 注入的值」。
   一旦给槽位 widget 设了非空默认值，「提示词槽位」节点传过来的值就被盖掉了。
   所以：新增的槽位/过滤 widget 默认值一律 "" （BOOLEAN 除外，见下）。

3. **BOOLEAN 组开关不要隐藏任何东西**：它只是前端 JS 读的一个标记，
   后端永远不会读它。值会被序列化（所以展开状态能随工作流保存），无害。

   注意「过滤控制」组里的 通用/争议/敏感/露骨 四个是**真实生效**的开关，
   不是组开关。它们原来的兜底逻辑是：
       if not enabled_files:
           enabled_files = ["taglists-sensitive.txt", "taglists-explicit.txt"]
   所以默认必须保持 敏感=True / 露骨=True，否则开箱行为和现在不一致。

__init__.py 也要加一行：
    WEB_DIRECTORY = "./js"
    __all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
"""

from __future__ import annotations

from typing import Any

# 分组开关的显示名 —— 必须和 js/anima_groups.js 里 GROUPS 的 key 逐字一致
G_SLOT = "▸ 标签槽位"
G_FILTER = "▸ 过滤控制"
G_LLM = "▸ LLM设置"
G_BATCH = "▸ 批量"
G_ADV = "▸ 高级"


def build_input_types(model_list: list[str]) -> dict[str, Any]:
    """
    返回 AnimaWeaver 的 INPUT_TYPES。
    原 anima_weaver.py:74 的 INPUT_TYPES 整体替换成：

        @classmethod
        def INPUT_TYPES(cls) -> dict[str, Any]:
            from .model_cache import get_models_cached      # 见 03_lm_studio_fix.py
            try:
                model_list = get_models_cached()
            except Exception:
                model_list = ["(no models found)"]
            if not model_list:
                model_list = ["(no models found)"]
            return build_input_types(model_list)
    """
    return {
        # ══════════════════════════════════════════════════════════
        # 一级：常驻，永远可见
        # ══════════════════════════════════════════════════════════
        "required": {
            "模式": (["manual", "random", "hybrid"], {"default": "hybrid"}),
            "标签比例": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05}),
            "场景类型": (
                ["solo_display", "couple_foreplay", "couple_sex",
                 "group", "yuri", "special_theme"],
            ),
        },

        # ══════════════════════════════════════════════════════════
        # 二级：分组，默认收起
        # ══════════════════════════════════════════════════════════
        "optional": {
            # ── 随机种子：用得太频繁，放一级区底部不折叠 ──
            "随机种子": ("INT", {"forceInput": True, "default": 0, "min": 0,
                              "max": 0xFFFF_FFFF_FFFF_FFFF}),

            # ━━ 组 1：标签槽位（吸收 提示词槽位 节点）─────────────
            G_SLOT: ("BOOLEAN", {"default": False}),
            "人数/身份":  ("STRING", {"multiline": True, "default": ""}),
            "外貌":      ("STRING", {"multiline": True, "default": ""}),
            "服装":      ("STRING", {"multiline": True, "default": ""}),
            "姿势/动作":  ("STRING", {"multiline": True, "default": ""}),
            "表情":      ("STRING", {"multiline": True, "default": ""}),
            "镜头":      ("STRING", {"multiline": True, "default": ""}),
            "场景/环境":  ("STRING", {"multiline": True, "default": ""}),
            "细节/氛围":  ("STRING", {"multiline": True, "default": ""}),
            "自然语言描述": ("STRING", {"multiline": True, "default": ""}),

            # ━━ 组 2：过滤控制（吸收 底部控制 节点）───────────────
            G_FILTER: ("BOOLEAN", {"default": False}),
            "标签列表必含":  ("STRING", {"multiline": True, "default": ""}),
            "过滤标签":     ("STRING", {"multiline": True, "default": ""}),
            "排除含标签列表": ("STRING", {"multiline": True, "default": ""}),
            "排除标签分类":  ("STRING", {"multiline": True, "default": ""}),
            # 这四个是真实开关，默认值必须复刻原「底部控制」节点
            "通用标签": ("BOOLEAN", {"default": False}),
            "争议标签": ("BOOLEAN", {"default": False}),
            "敏感标签": ("BOOLEAN", {"default": True}),
            "露骨标签": ("BOOLEAN", {"default": True}),

            # ━━ 组 3：LLM 设置 ──────────────────────────────────
            G_LLM: ("BOOLEAN", {"default": False}),
            "自然语言来源": (["manual", "lm_studio"], {"default": "manual"}),
            "强制详细自然语言": ("BOOLEAN", {"default": False}),
            "模型": (model_list,),
            "API地址": ("STRING", {"default": "http://localhost:1234/v1",
                                 "multiline": False,
                                 "tooltip": "LM Studio API 地址（或兼容 OpenAI 的 API 地址）"}),
            "API密钥": ("STRING", {"default": ""}),
            "云端模型名": ("STRING", {"default": ""}),
            "上下文长度": ("INT", {"default": 8192, "min": 0, "max": 262144}),
            "自动上下文长度": ("BOOLEAN", {"default": False}),
            "最大截断长度": ("INT", {"default": 0, "min": 0, "max": 1080, "step": 8}),
            "生成后卸载": ("BOOLEAN", {"default": False}),

            # ━━ 组 4：批量（吸收 批量种子 节点）───────────────────
            G_BATCH: ("BOOLEAN", {"default": False}),
            "批量数量": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 1,
                              "tooltip": ">0 时内部生成 N 个随机种子，等价于接入种子串"}),
            "种子串": ("STRING", {"forceInput": True, "multiline": True}),
            "画师串": ("STRING", {"forceInput": True, "multiline": True}),
            "反推串": ("STRING", {"forceInput": True, "multiline": True}),
            "请求数": ("INT", {"default": 4, "min": 1, "max": 128, "step": 1}),
            "最大并发数": ("INT", {"default": 4, "min": 1, "max": 128, "step": 1}),

            # ━━ 组 5：高级 ──────────────────────────────────────
            G_ADV: ("BOOLEAN", {"default": False}),
            "画师种子": ("INT", {"default": 0, "min": -1, "max": 0x7FFFFFFF,
                              "tooltip": "-1=随机画师，0=无画师，1~=固定画师序号"}),
            "冲突检查": ("BOOLEAN", {"default": True}),
            "系统提示词": ("STRING", {"forceInput": True, "multiline": True}),
            # 兼容旧工作流：保留这两个 JSON 入口，但折叠进「高级」
            "槽位数据": ("STRING", {"forceInput": True,
                                 "tooltip": "旧工作流兼容：「提示词槽位」节点的输出"}),
            "底部数据": ("STRING", {"forceInput": True,
                                 "tooltip": "旧工作流兼容：「底部控制」节点的输出"}),
        },
    }


# ── compose() 里要补的一段（吸收 BatchSeedNode）─────────────────────
BATCH_COUNT_SNIPPET = '''
# 放在 compose() 开头，原来读 batch_seeds_str 的地方之前
batch_seeds_str = kwargs.get("种子串", "")
if not batch_seeds_str.strip():
    n = int(kwargs.get("批量数量", 0) or 0)
    if n > 0:
        batch_seeds_str = "\\n".join(
            str(random.randint(1, 0x7FFFFFFFFFFFFFFF)) for _ in range(n))
is_batch = bool(batch_seeds_str.strip())
if is_batch:
    kwargs.pop("随机种子", None)
'''

# ── __init__.py 要加的一行 ─────────────────────────────────────────
INIT_SNIPPET = '''
WEB_DIRECTORY = "./js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
'''

# ── 节点数变化 ─────────────────────────────────────────────────────
NODE_COUNT_AFTER = '''
整合后 __init__.py 的 NODE_CLASS_MAPPINGS 只剩 6 项：

    "AnimaWeaver":          AnimaWeaver,          # 含槽位/过滤/批量数量（分组折叠）
    "AnimaImageCaption":    AnimaImageCaption,    # 反推
    "RandomResolution":     RandomResolution,     # 分辨率
    "ArtistSeed":           ArtistSeed,           # 画师
    "AnimaLoadImages":      AnimaLoadImages,      # 加载图像
    "AnimaBatchBus":        AnimaBatchBus,        # 批量总线（合并/拆分 二合一）

删掉的 5 个：PromptSlots / BottomControls / BatchSeedNode
             SyncPassthrough / PassthroughSplit(并入 BatchBus)
'''
