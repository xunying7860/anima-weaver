"""
Anima Weaver — ComfyUI Custom Node Package

四节点精简版（2026-10）：8 → 4。
已删除：Anima反推(caption)、画师Seed(artist_seed)、Anima加载图像(load_images)、
Anima列表转多行(list_to_multiline)。画师能力由主节点「画师种子」控件承担
（画师名直接拼进提示词末尾，不再单独成串）；反推透传交给 Anima批量总线。
回滚锚点：git tag pre-4node-20261016。
"""

from .anima_weaver import AnimaWeaver
from .resolution import RandomResolution
from .batch_seed import BatchSeedNode
from .batch_bus import AnimaBatchMerge, AnimaBatchSplit

NODE_CLASS_MAPPINGS = {
    "AnimaWeaver": AnimaWeaver,
    "RandomResolution": RandomResolution,
    "BatchSeedNode": BatchSeedNode,
    "AnimaBatchMerge": AnimaBatchMerge,
    "AnimaBatchSplit": AnimaBatchSplit,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaWeaver": "Anima随机提示词",
    "RandomResolution": "随机分辨率选择器",
    "BatchSeedNode": "批量种子",
    "AnimaBatchMerge": "Anima批量合并",
    "AnimaBatchSplit": "Anima批量拆分",
}

# 前端扩展目录：js/anima_groups.js（AnimaWeaver 两级分组折叠）
WEB_DIRECTORY = "./js"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
