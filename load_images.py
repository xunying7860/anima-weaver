"""
Anima Weaver — Load Images Node.
Loads all images from a folder path, outputs as IMAGE list (not batch).
No cropping, no resizing. Traversal order matches Anima反推 (sorted by filename).
"""

from __future__ import annotations
import os
import torch
from PIL import Image as PILImage, ImageOps
import numpy as np


class AnimaLoadImages:
    """Load all images from a folder, output as list of IMAGE tensors."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        return {
            "required": {
                "图片路径": (
                    "STRING",
                    {"default": "", "multiline": False,
                     "tooltip": "图片文件夹路径，自动遍历所有图片并按文件名排序"},
                ),
            },
        }

    CATEGORY = "Anima Weaver / Utils"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("图像", "遮罩", "文件路径")
    OUTPUT_IS_LIST = (True, True, False)
    FUNCTION = "load"
    OUTPUT_NODE = False

    def load(self, 图片路径: str) -> tuple[list[torch.Tensor], list[torch.Tensor], str]:
        folder = 图片路径.strip()
        if not folder or not os.path.isdir(folder):
            dummy = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return ([dummy], [torch.zeros((1, 64, 64), dtype=torch.float32)], "")

        # Scan images (same order as Anima反推 folder batch)
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
        images = sorted(
            [f for f in os.listdir(folder)
             if os.path.splitext(f)[1].lower() in image_exts]
        )
        if not images:
            dummy = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return ([dummy], [torch.zeros((1, 64, 64), dtype=torch.float32)], "")

        # Load each image as individual tensor (no stacking)
        tensors: list[torch.Tensor] = []
        masks: list[torch.Tensor] = []
        paths: list[str] = []
        for fname in images:
            fp = os.path.join(folder, fname)
            try:
                pil_img = PILImage.open(fp)
                pil_img = ImageOps.exif_transpose(pil_img)
                img_rgb = pil_img.convert("RGB")
                img_np = np.array(img_rgb).astype(np.float32) / 255.0
                tensors.append(torch.from_numpy(img_np)[None, ...])

                # Alpha channel → mask
                if pil_img.mode == "RGBA":
                    alpha = np.array(pil_img.split()[-1]).astype(np.float32) / 255.0
                    masks.append(torch.from_numpy(alpha)[None, ...])
                else:
                    h, w = img_np.shape[:2]
                    masks.append(torch.ones((1, h, w), dtype=torch.float32))

                paths.append(fp)
            except Exception as e:
                print(f"[AnimaLoadImages] Failed to load {fp}: {e}")

        if not tensors:
            dummy = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return ([dummy], [torch.zeros((1, 64, 64), dtype=torch.float32)], "")

        out_paths = "\n".join(paths)
        print(f"[AnimaLoadImages] Loaded {len(tensors)} images from {folder}")
        return (tensors, masks, out_paths)


NODE_CLASS_MAPPINGS = {"AnimaLoadImages": AnimaLoadImages}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaLoadImages": "Anima加载图像"}
