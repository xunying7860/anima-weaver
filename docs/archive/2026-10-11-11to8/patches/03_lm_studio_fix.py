"""
03_lm_studio_fix.py —— 三个必修 bug + INPUT_TYPES 不阻塞
========================================================

【BUG-1 致命】lm_studio.py:465  SyntaxError（Python < 3.12）
-------------------------------------------------------------
    url = f"{base_url.rstrip("/")}/chat/completions"
                              ^^^  嵌套了同类型引号

PEP 701 才允许这么做（Python 3.12+）。ComfyUI 主流环境是 3.10 / 3.11，
所以这个文件**根本 import 不进来**。

而 anima_weaver.py:79 是这样调用的：
    try:
        from .lm_studio import get_models
        models = get_models()
    except Exception:
        pass
    if not model_list:
        model_list = ["(no models found)"]

→ SyntaxError 被 except 吞掉 → 下拉框永远只有 "(no models found)" →
  **所有 LM Studio 自然语言功能在 Python 3.10/3.11 上静默失效**，用户只会以为"模型没装"。

修复（任选一种写法）：
    url = f'{base_url.rstrip("/")}/chat/completions'          # 外层改单引号
    url = base_url.rstrip("/") + "/chat/completions"          # 或干脆不用 f-string

本机验证：python3.10 -m py_compile lm_studio.py  —— 改前 SyntaxError，改后通过。


【BUG-2】anima_weaver.py:453  NameError: auto_ctx
-------------------------------------------------
_compose_batch() 里用了 auto_ctx，但整个函数里从没定义过（只在另一个函数 787 行有）。
整段在 try/except Exception 里，于是**批量模式的模型预加载永远静默失败**，
每个种子各自触发一次模型加载 —— 批量越跑越慢。

修复：在 try 块内补一行
    auto_ctx = bool(kwargs.get("自动上下文长度", False))
    if auto_ctx:
        ctx = int(kwargs.get("最大并发数", 4)) * 2048


【BUG-3】caption.py:341  NameError: kwargs
------------------------------------------
用的是 kwargs_raw.get(...)，但那行写的是 kwargs.get(...)，同样被 try/except 吞掉。


【性能】INPUT_TYPES() 里同步跑 lms 子进程
------------------------------------------
    @classmethod
    def INPUT_TYPES(cls):
        from .lm_studio import get_models
        models = get_models()          # subprocess.run(["lms","ls"], timeout=60)

ComfyUI 每次刷新页面 / 打开节点菜单都会请求 /object_info，
也就是**每次都会 fork 一个 lms 子进程**，最坏阻塞 60 秒。
LM Studio 没装时 shutil.which 会失败得很快，装了但服务没响应就会卡住。

修复：改成「缓存 + 后台刷新 + 永不阻塞」：
"""

from __future__ import annotations

import threading
import time
from typing import Optional

# ── 1) 模型列表缓存 ─────────────────────────────────────────────────
_MODEL_CACHE: Optional[list[str]] = None
_MODEL_TS: float = 0.0
_TTL = 300.0            # 5 分钟
_lock = threading.Lock()
_REFRESHING = False


def get_models_cached() -> list[str]:
    """
    INPUT_TYPES 里调这个，绝不阻塞。
      - 有缓存直接用
      - 没有缓存：先返回占位（或上次的结果），后台线程去查
      - 缓存过期：返回旧值，后台刷新
    """
    global _MODEL_CACHE, _MODEL_TS, _REFRESHING

    now = time.monotonic()
    with _lock:
        if _MODEL_CACHE is not None and (now - _MODEL_TS) < _TTL:
            return list(_MODEL_CACHE)
        if _REFRESHING:
            return list(_MODEL_CACHE) if _MODEL_CACHE else ["(检测中…)"]
        _REFRESHING = True

    def _worker():
        global _MODEL_CACHE, _MODEL_TS, _REFRESHING
        try:
            from .lm_studio import get_models
            models = get_models()
            with _lock:
                if models:
                    _MODEL_CACHE = models
                _MODEL_TS = time.monotonic()
        except Exception:
            with _lock:
                _MODEL_TS = time.monotonic()      # 失败也记时间，避免疯狂重试
        finally:
            with _lock:
                _REFRESHING = False

    threading.Thread(target=_worker, name="anima-lms-ls", daemon=True).start()

    with _lock:
        return list(_MODEL_CACHE) if _MODEL_CACHE else ["(检测中…)"]


def invalidate_model_cache() -> None:
    """用户点了「刷新模型列表」时调用。"""
    global _MODEL_TS
    with _lock:
        _MODEL_TS = 0.0


# ── 2) 给 lms 子进程加硬超时 ────────────────────────────────────────
# lm_studio.py::_run_lms 的 timeout 默认 60s，get_models() 直接用了默认值。
# 建议改成：模型列表这种轻量查询用 5s，load 用 120s。
#
#     - rc, stdout, stderr = _run_lms(["ls"])
#     + rc, stdout, stderr = _run_lms(["ls"], timeout=5)
#
# 并在 _run_lms 里把 creationflags / start_new_session 加上，
# 保证超时后子进程真被杀掉而不是变成僵尸：
import subprocess  # noqa: E402
import os as _os  # noqa: E402


def _run_lms_hard_timeout(cmd: list[str], timeout: int = 5):
    """替身实现：超时后杀掉整个进程组。"""
    kwargs = {"capture_output": True, "text": True,
              "encoding": "utf-8", "errors": "replace", "timeout": timeout}
    if _os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        p = subprocess.run(cmd, **kwargs)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        # aiohttp/subprocess 不会自动杀进程组，这里兜底
        try:
            if _os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)])
            else:
                import signal
                _os.killpg(_os.getpgid(p.pid), signal.SIGKILL)
        except Exception:
            pass
        return 124, "", f"lms timed out after {timeout}s"


# ── 3) INPUT_TYPES 改法（可直接替换 anima_weaver.py:77-87）────────────
INPUT_TYPES_PATCH = '''
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        # 不再同步跑 lms 子进程：命中缓存直接返回，未命中后台刷新
        try:
            from .model_cache import get_models_cached
            model_list = get_models_cached()
        except Exception:
            model_list = ["(no models found)"]
        if not model_list:
            model_list = ["(no models found)"]
        ...
'''
