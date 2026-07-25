"""
Anima Weaver — ComfyUI Custom Node Package
"""

from .anima_weaver import AnimaWeaver
from .resolution import RandomResolution
from .slots_node import PromptSlots
from .bottom_ctrl import BottomControls
from .caption import AnimaImageCaption
from .artist_seed import ArtistSeed
from .batch_seed import BatchSeedNode
from .sync_passthrough import SyncPassthrough
from .passthrough_split import PassthroughSplit
from .load_images import AnimaLoadImages
from .list_to_multiline import AnimaTextListToMultiline

NODE_CLASS_MAPPINGS = {
    "AnimaWeaver": AnimaWeaver,
    "RandomResolution": RandomResolution,
    "PromptSlots": PromptSlots,
    "BottomControls": BottomControls,
    "AnimaImageCaption": AnimaImageCaption,
    "ArtistSeedNode": ArtistSeed,
    "BatchSeedNode": BatchSeedNode,
    "SyncPassthrough": SyncPassthrough,
    "PassthroughSplit": PassthroughSplit,
    "AnimaLoadImages": AnimaLoadImages,
    "AnimaTextListToMultiline": AnimaTextListToMultiline,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaWeaver": "Anima随机提示词",
    "RandomResolution": "随机分辨率选择器",
    "PromptSlots": "提示词槽位",
    "BottomControls": "底部控制",
    "AnimaImageCaption": "Anima反推",
    "ArtistSeedNode": "画师Seed",
    "BatchSeedNode": "批量种子",
    "SyncPassthrough": "同步串行",
    "PassthroughSplit": "串行拆分",
    "AnimaLoadImages": "Anima加载图像",
    "AnimaTextListToMultiline": "Anima列表转多行",
}

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
