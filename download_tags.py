"""
download_tags.py —— 标签库下载/校验工具（方案 §4 的轻量实现）

现状：tags/ 下 4 个 taglists-*.txt（共 ~216 MB）仍随仓库分发（保留旧功能：
克隆即用）。当仓库日后把大文件迁到 GitHub Release / HuggingFace 时，
本脚本负责首启下载 + sha256 校验，节点在缺文件时会明确报错并提示运行本脚本。

用法：
    python download_tags.py            # 只缺哪个下哪个（已存在且校验通过则跳过）
    python download_tags.py --check    # 只校验本地文件，不下载
    python download_tags.py --force    # 全部重下

taglists 目前仍在 git 仓库内，URL 为占位（迁移 Release 时改 BASE 即可）。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TAGS_DIR = os.path.join(HERE, "tags")

# 迁移到 Release 后改这里；文件名 -> sha256（发布时用 sha256sum 生成）
BASE = "https://github.com/xunying7860/anima-weaver/releases/download/tags-v1/"
FILES: dict[str, str] = {
    "taglists-general.txt": "",       # 空 = 不校验（仓库内版本）
    "taglists-questionable.txt": "",
    "taglists-sensitive.txt": "",
    "taglists-explicit.txt": "",
}


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description="下载/校验 tags/ 标签库")
    ap.add_argument("--check", action="store_true", help="只校验不下载")
    ap.add_argument("--force", action="store_true", help="全部重下")
    args = ap.parse_args()

    import urllib.request

    rc = 0
    for name, want in FILES.items():
        dst = os.path.join(TAGS_DIR, name)
        exists = os.path.isfile(dst)
        if exists and not args.force:
            if want:
                got = sha256_of(dst)
                if got == want:
                    print(f"[跳过] {name} 校验通过")
                    continue
                print(f"[重下] {name} sha256 不符: {got[:12]}… != {want[:12]}…")
            else:
                print(f"[跳过] {name} 已存在（无 sha256 清单，不校验）")
                continue
        if args.check:
            print(f"[缺失] {name}" if not exists else f"[待校验] {name}")
            rc = 1
            continue
        url = BASE + name
        os.makedirs(TAGS_DIR, exist_ok=True)
        tmp = dst + ".download"
        print(f"[下载] {url}")
        try:
            with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    print(f"  … {os.path.getsize(tmp) >> 20} MB", end="\r")
            print()
            if want:
                got = sha256_of(tmp)
                if got != want:
                    print(f"[失败] sha256 不符: {got[:12]}… != {want[:12]}…，保留 .download 供排查")
                    rc = 1
                    continue
            os.replace(tmp, dst)
            print(f"[完成] {name} ({os.path.getsize(dst) >> 20} MB)")
        except Exception as e:  # noqa: BLE001 —— 工具脚本，打印即可
            print(f"[失败] {name}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
