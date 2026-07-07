"""
Anima Weaver — ComfyUI Custom Node Package
"""

from .anima_weaver import AnimaWeaver
from .resolution import RandomResolution

NODE_CLASS_MAPPINGS = {
    "AnimaWeaver": AnimaWeaver,
    "RandomResolution": RandomResolution,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaWeaver": "提示词编织器",
    "RandomResolution": "随机分辨率选择器",
}

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
