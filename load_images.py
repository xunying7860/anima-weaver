"""
Anima Weaver — Load Images Node.
Loads all images from a folder path and outputs as IMAGE batch tensor (sorted by filename).
"""

from __future__ import annotations
import os
import torch
from PIL import Image as PILImage
import numpy as np


class AnimaLoadImages:
    """Load all images from a folder path, output as batched IMAGE tensor."""

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
    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("图像", "总数量")
    FUNCTION = "load"
    OUTPUT_NODE = False

    def load(self, 图片路径: str) -> tuple[torch.Tensor, int]:
        folder = 图片路径.strip()
        if not folder or not os.path.isdir(folder):
            print(f"[AnimaLoadImages] Invalid path: {folder}")
            # Return a minimal 1x1 black image so ComfyUI doesn't crash
            dummy = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (dummy, 0)

        # Scan images (same order as Anima反推)
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
        images = sorted(
            [f for f in os.listdir(folder)
             if os.path.splitext(f)[1].lower() in image_exts]
        )
        if not images:
            print(f"[AnimaLoadImages] No images found in {folder}")
            dummy = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (dummy, 0)

        # Load all images
        tensors: list[torch.Tensor] = []
        for fname in images:
            fp = os.path.join(folder, fname)
            try:
                pil_img = PILImage.open(fp).convert("RGB")
                img_np = np.array(pil_img).astype(np.float32) / 255.0
                tensors.append(torch.from_numpy(img_np)[None, ...])
            except Exception as e:
                print(f"[AnimaLoadImages] Failed to load {fp}: {e}")

        if not tensors:
            dummy = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (dummy, 0)

        # Pad all images to max dimensions for batch consistency
        max_h = max(t.shape[1] for t in tensors)
        max_w = max(t.shape[2] for t in tensors)
        padded = []
        for t in tensors:
            h, w = t.shape[1], t.shape[2]
            if h == max_h and w == max_w:
                padded.append(t)
            else:
                pad = torch.zeros((1, max_h, max_w, 3), dtype=torch.float32)
                pad[:, :h, :w, :] = t
                padded.append(pad)

        out = torch.cat(padded, dim=0)
        print(f"[AnimaLoadImages] Loaded {len(padded)} images, size={max_h}x{max_w}")
        return (out, len(padded))


NODE_CLASS_MAPPINGS = {"AnimaLoadImages": AnimaLoadImages}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaLoadImages": "Anima加载图像"}
