"""
Anima Weaver — Text Saver Node.
Saves each line of a multiline string as a .txt file alongside the corresponding image.
"""

from __future__ import annotations
import os


class AnimaTextSaver:
    """Save multiline text to .txt files for each image in a folder."""

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, object]:
        return {
            "required": {
                "文本串": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "多行文本，每行对应一张图片的描述"},
                ),
                "图片路径": (
                    "STRING",
                    {"forceInput": True, "multiline": False,
                     "tooltip": "图片所在文件夹路径，与文本串行数对齐"},
                ),
            },
        }

    CATEGORY = "Anima Weaver / Utils"
    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("保存数量",)
    FUNCTION = "save"
    OUTPUT_NODE = True

    def save(self, 文本串: str, 图片路径: str) -> tuple[int]:
        """Split the text by newlines and save each line to .txt."""
        lines = [l.strip() for l in 文本串.split("\n") if l.strip()]
        folder = 图片路径.strip()
        if not lines or not folder or not os.path.isdir(folder):
            print(f"[TextSaver] No text or invalid path: {folder}")
            return (0,)

        # Scan images in folder
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
        images = sorted(
            [f for f in os.listdir(folder)
             if os.path.splitext(f)[1].lower() in image_exts]
        )

        saved = 0
        for i, fname in enumerate(images):
            if i >= len(lines):
                break
            txt_path = os.path.join(folder, os.path.splitext(fname)[0] + ".txt")
            try:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(lines[i])
                saved += 1
            except Exception as e:
                print(f"[TextSaver] Failed to write {txt_path}: {e}")

        print(f"[TextSaver] Saved {saved}/{min(len(images), len(lines))} txt files")
        return (saved,)


NODE_CLASS_MAPPINGS = {"AnimaTextSaver": AnimaTextSaver}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaTextSaver": "Anima文本保存"}
