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
                "统一尺寸": ("BOOLEAN", {"default": True,
                                          "tooltip": "开启后将所有图缩放到统一尺寸（取第一张图的尺寸），否则每个 frame 独立尺寸"}),
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

    def load(self, 文件夹路径: str, 图像上限: int = 0, 统一尺寸: bool = True) -> tuple[torch.Tensor, int]:
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

        # Load all images as PIL
        pil_images: list[Image.Image] = []
        target_size = None
        for fp in files:
            try:
                pil = Image.open(fp).convert("RGB")
                if target_size is None and 统一尺寸:
                    target_size = pil.size  # (width, height) of first image
                if 统一尺寸 and target_size:
                    pil = pil.resize(target_size, Image.LANCZOS)
                pil_images.append(pil)
            except Exception as e:
                print(f"[LoadImageBatch] Failed to load {fp}: {e}")

        if not pil_images:
            dummy = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
            return (dummy, 0)

        # Convert to batched tensor [N, H, W, 3]
        tensors: list[torch.Tensor] = []
        for pil in pil_images:
            arr = torch.tensor(
                list(pil.getdata()),
                dtype=torch.float32,
            ).reshape(pil.size[1], pil.size[0], 3) / 255.0
            tensors.append(arr)

        batch = torch.stack(tensors, dim=0)  # [N, H, W, 3]
        print(f"[LoadImageBatch] Output shape: {list(batch.shape)}")
        return (batch, batch.shape[0])


NODE_CLASS_MAPPINGS = {"LoadImageBatch": LoadImageBatch}
NODE_DISPLAY_NAME_MAPPINGS = {"LoadImageBatch": "加载图像批次"}
