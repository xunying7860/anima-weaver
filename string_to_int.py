"""Convert STRING to INT — takes multiline STRING, outputs first row as INT."""

from __future__ import annotations

from typing import Any


class StringToInt:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "输入": ("STRING", {"multiline": True, "default": "0",
                                    "tooltip": "多行 STRING，取第一行转为 INT"}),
            },
        }

    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("输出",)
    FUNCTION = "convert"
    CATEGORY = "Anima Weaver / Utils"

    def convert(self, 输入: str) -> tuple[int]:
        try:
            line = 输入.strip().split("\n")[0] if 输入.strip() else "0"
            return (int(line),)
        except (ValueError, TypeError, IndexError):
            return (0,)


NODE_CLASS_MAPPINGS = {"StringToInt": StringToInt}
NODE_DISPLAY_NAME_MAPPINGS = {"StringToInt": "STRING转INT"}
