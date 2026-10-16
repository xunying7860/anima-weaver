"""
download_tags.py —— 标签库一键补齐（222 MB taglists 已移出 git）
================================================================
git clone 后 tags/ 下缺 4 个 taglists-*.txt（共约 215 MB）时，
本脚本从 GitHub Release 拉取最新的 anima-weaver 标签库 zip，
只补齐缺失的文件（已存在且够大的跳过），完成后校验每个
taglists 文件 > 40 MB，否则报错退出（非 0）。

用法：
    python download_tags.py                  # 自动找最新 Release 的 zip 并补齐
    python download_tags.py --url <zip-url>  # 直接指定 zip 下载地址（跳过 GitHub API）
    python download_tags.py --check          # 只校验本地文件，不下载

只依赖标准库（urllib / zipfile）。网络失败会打印清晰错误并以非 0 退出。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TAGS_DIR = os.path.join(HERE, "tags")

REPO_API = "https://api.github.com/repos/xunying7860/anima-weaver/releases/latest"
REPO_NAME = "anima-weaver"

# git clone 后必须补齐的 4 个 taglist（各约 50~60 MB）
REQUIRED_TAGLISTS = [
    "taglists-general.txt",
    "taglists-questionable.txt",
    "taglists-sensitive.txt",
    "taglists-explicit.txt",
]
# 任何 taglist 小于 40 MB 一律视为下载不完整
MIN_TAGLIST_BYTES = 40 * 1024 * 1024


def _size_ok(name: str) -> bool:
    p = os.path.join(TAGS_DIR, name)
    return os.path.isfile(p) and os.path.getsize(p) > MIN_TAGLIST_BYTES


def _missing_taglists() -> list:
    return [n for n in REQUIRED_TAGLISTS if not _size_ok(n)]


def _fetch_latest_zip_url() -> str:
    """GitHub API：最新 Release 里名字含 anima-weaver 且以 .zip 结尾的资产。"""
    req = urllib.request.Request(
        REPO_API,
        headers={
            "User-Agent": "anima-weaver-download-tags",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    assets = data.get("assets") or []
    for a in assets:
        name = a.get("name", "")
        if REPO_NAME in name and name.endswith(".zip"):
            url = a.get("browser_download_url") or a.get("url") or ""
            if url:
                return url
    raise RuntimeError(
        "最新 Release 里找不到名字含 '%s' 且以 .zip 结尾的资产（实际资产: %s）"
        % (REPO_NAME, [a.get("name") for a in assets])
    )


def _download(url: str, dst: str) -> None:
    """下载到 dst，带 MB 进度打印。"""
    print("[下载] %s" % url)
    tmp = dst + ".part"
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    print("  … %d / %d MB（%d%%）" % (done >> 20, total >> 20, done * 100 // total), end="\r")
                else:
                    print("  … %d MB" % (done >> 20), end="\r")
        print()
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _extract_missing(zip_path: str) -> list:
    """
    从 zip 里补齐 tags/ 下缺失的 .txt/.json 文件：
    4 个 taglists（已存在但不足 40 MB 的会覆盖重抽）+ 其他缺失的小文件。
    """
    extracted = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/")
            if "tags" not in parts[:-1]:
                continue
            base = parts[-1]
            if not (base.endswith(".txt") or base.endswith(".json")):
                continue
            dst = os.path.join(TAGS_DIR, base)
            if os.path.isfile(dst):
                too_small = base in REQUIRED_TAGLISTS and os.path.getsize(dst) <= MIN_TAGLIST_BYTES
                if not too_small:
                    continue
            with zf.open(info) as src, open(dst, "wb") as out:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            extracted.append(base)
            print("  [解压] tags/%s（%d MB）" % (base, os.path.getsize(dst) >> 20))
    return extracted


def main() -> int:
    ap = argparse.ArgumentParser(description="补齐 tags/ 标签库（下载最新 Release zip 并解压）")
    ap.add_argument("--url", default=None,
                    help="直接指定标签库 zip 下载地址（跳过 GitHub API）")
    ap.add_argument("--check", action="store_true", help="只校验本地文件，不下载")
    args = ap.parse_args()

    os.makedirs(TAGS_DIR, exist_ok=True)

    missing = _missing_taglists()
    if missing:
        print("[缺失] %s" % ", ".join(missing))
    else:
        print("[校验] 4 个 taglists 齐全且各 > 40 MB，无需下载")

    if args.check:
        return 1 if missing else 0

    if missing:
        try:
            url = args.url or _fetch_latest_zip_url()
        except Exception as e:  # noqa: BLE001 —— 工具脚本，打印即可
            print("[错误] 获取 zip 下载地址失败: %s" % e)
            print("       可手动下载最新 Release 的标签库 zip，再用 --url 传入")
            return 1
        zip_path = os.path.join(tempfile.gettempdir(), "anima-weaver-tags.zip")
        try:
            _download(url, zip_path)
            _extract_missing(zip_path)
        except (urllib.error.URLError, urllib.error.HTTPError,
                OSError, zipfile.BadZipFile, RuntimeError) as e:
            print("[错误] 下载/解压失败: %s" % e)
            return 1
        finally:
            try:
                os.remove(zip_path)
            except OSError:
                pass

    # 最终校验：每个 taglists 必须存在且 > 40 MB
    bad = [n for n in REQUIRED_TAGLISTS if not _size_ok(n)]
    if bad:
        print("[失败] 以下 taglists 仍缺失或不足 40 MB: %s" % ", ".join(bad))
        return 1
    print("[完成] 标签库齐全，可直接使用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
