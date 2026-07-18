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
from .string_to_int import StringToInt

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
    "StringToInt": StringToInt,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaWeaver": "提示词编织器",
    "RandomResolution": "随机分辨率选择器",
    "PromptSlots": "提示词槽位",
    "BottomControls": "底部控制",
    "AnimaImageCaption": "lm studio image to prompt",
    "ArtistSeedNode": "画师Seed",
    "BatchSeedNode": "批量种子",
    "SyncPassthrough": "同步串行",
    "PassthroughSplit": "串行拆分",
    "StringToInt": "STRING转INT",
}

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
