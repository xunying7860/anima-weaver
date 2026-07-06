"""
Anima Weaver — ComfyUI Custom Node Package
"""

from .anima_weaver import AnimaWeaver

NODE_CLASS_MAPPINGS = {
    "AnimaWeaver": AnimaWeaver,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AnimaWeaver": "提示词编织器",
}

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
