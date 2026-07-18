"""
Anima Weaver — Load Image Batch node.
Loads all images from a folder into a single batched IMAGE tensor [N, H, W, 3].
"""

from __future__ import annotations

import os
import random
from typing import Any

import torch
from PIL import Image


_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


class LoadImageBatch:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        return {
            "required": {
                "文件夹路径": ("STRING", {"default": "", "multiline": False}),
                "图像上限": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 1,
                                      "tooltip": "0=不限制"}),
            },
        }

    CATEGORY = "Anima Weaver / Batch"
    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("图像", "数量")
    FUNCTION = "load"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs) -> float:
        return random.random()

    def load(self, 文件夹路径: str, 图像上限: int = 0) -> tuple[torch.Tensor, int]:
        folder = str(文件夹路径).strip()
        if not folder or not os.path.isdir(folder):
            print(f"[LoadImageBatch] Invalid folder: {folder}")
            # Return a dummy 1x1 image to avoid ComfyUI errors
            dummy = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (dummy, 0)

        # Collect image files
        files: list[str] = []
        for f in sorted(os.listdir(folder)):
            ext = os.path.splitext(f)[1].lower()
            if ext in _IMAGE_EXTENSIONS:
                files.append(os.path.join(folder, f))

        if not files:
            print(f"[LoadImageBatch] No images found in {folder}")
            dummy = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (dummy, 0)

        # Apply limit
        if 图像上限 > 0:
            files = files[:图像上限]

        print(f"[LoadImageBatch] Loading {len(files)} images from {folder}")

        # Load all images as PIL, pad to max dimensions for batch compatibility
        pil_images: list[Image.Image] = []
        for fp in files:
            try:
                pil = Image.open(fp).convert("RGB")
                pil_images.append(pil)
            except Exception as e:
                print(f"[LoadImageBatch] Failed to load {fp}: {e}")

        if not pil_images:
            dummy = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (dummy, 0)

        # Find max width and height
        max_w = max(p.size[0] for p in pil_images)
        max_h = max(p.size[1] for p in pil_images)

        # Pad each image to (max_w, max_h) center with black borders
        padded: list[torch.Tensor] = []
        for pil in pil_images:
            pw, ph = pil.size
            left = (max_w - pw) // 2
            top = (max_h - ph) // 2
            canvas = Image.new("RGB", (max_w, max_h), (0, 0, 0))
            canvas.paste(pil, (left, top))
            arr = torch.tensor(
                list(canvas.getdata()),
                dtype=torch.float32,
            ).reshape(max_h, max_w, 3) / 255.0
            padded.append(arr)

        batch = torch.stack(padded, dim=0)  # [N, H, W, 3]
        print(f"[LoadImageBatch] Output shape: {list(batch.shape)} (padded to {max_w}x{max_h})")
        return (batch, batch.shape[0])


NODE_CLASS_MAPPINGS = {"LoadImageBatch": LoadImageBatch}
NODE_DISPLAY_NAME_MAPPINGS = {"LoadImageBatch": "加载图像批次"}
