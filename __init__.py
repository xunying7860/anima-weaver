"""
Anima Weaver — ComfyUI Custom Node Package
"""

from .anima_weaver import AnimaWeaver
from .resolution import RandomResolution
from .caption import AnimaImageCaption
from .artist_seed import ArtistSeed
from .batch_seed import BatchSeedNode
from .batch_bus import AnimaBatchBus
from .load_images import AnimaLoadImages
from .list_to_multiline import AnimaTextListToMultiline

# P2 节点整合：「提示词槽位」「底部控制」已并入 AnimaWeaver 自身控件
# （INPUT_TYPES 分组折叠），不再注册；「同步串行」「串行拆分」并入 AnimaBatchBus。
# 「批量种子」「列表转多行」保留：它们是跨节点共享的种子源/胶水节点
# （批量种子的种子串被画师/分辨率/总线等多个节点共用；列表转多行的 LIST
#  来自 WD14Tagger 等外部节点），主节点自身的批量/反推已吸收其等价逻辑。
NODE_CLASS_MAPPINGS = {
    "AnimaWeaver": AnimaWeaver,
    "RandomResolution": RandomResolution,
    "AnimaImageCaption": AnimaImageCaption,
    "ArtistSeedNode": ArtistSeed,
    "BatchSeedNode": BatchSeedNode,
    "AnimaBatchBus": AnimaBatchBus,
    "AnimaLoadImages": AnimaLoadImages,
    "AnimaTextListToMultiline": AnimaTextListToMultiline,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaWeaver": "Anima随机提示词",
    "RandomResolution": "随机分辨率选择器",
    "AnimaImageCaption": "Anima反推",
    "ArtistSeedNode": "画师Seed",
    "BatchSeedNode": "批量种子",
    "AnimaBatchBus": "Anima批量总线",
    "AnimaLoadImages": "Anima加载图像",
    "AnimaTextListToMultiline": "Anima列表转多行",
}

# 前端扩展目录：js/anima_groups.js（AnimaWeaver 参数分组折叠）
WEB_DIRECTORY = "./js"

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
]
