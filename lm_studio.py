"""
Anima Weaver — LM Studio CLI & API Wrapper

Handles locating the ``lms`` binary, loading/unloading models via the
CLI, and generating natural-language descriptions from a tag prompt
via the LM Studio OpenAI-compatible HTTP API.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Any, Optional

import requests

# ── Constants ──────────────────────────────────────────────────────

_DEFAULT_BASE_URL = "http://localhost:1234/v1"
_LMS_MAX_RETRIES = 2
_LMS_RETRY_DELAY_S = 2.0

# ── lms.exe path resolution ───────────────────────────────────────

def _get_lms_path() -> Optional[str]:
    """
    Locate the ``lms`` (or ``lms.exe``) binary on the system.

    Search order:
    1. ``LMS_PATH`` environment variable
    2. ``PATH`` (via ``shutil.which``)
    3. Common install locations on Windows / macOS / Linux

    Returns
    -------
    str or None
        Absolute path to the binary, or ``None`` if not found.
    """
    # 1. Explicit env override
    env_path = os.environ.get("LMS_PATH")
    if env_path:
        if os.path.isfile(env_path):
            return os.path.abspath(env_path)
        # Maybe it's a directory — look for lms inside
        cand = os.path.join(env_path, "lms" + (".exe" if platform.system() == "Windows" else ""))
        if os.path.isfile(cand):
            return os.path.abspath(cand)

    # 2. PATH
    exe = shutil.which("lms")
    if exe:
        return os.path.abspath(exe)

    # 3. Common locations
    system = platform.system()
    home = os.path.expanduser("~")
    candidates: list[str] = []

    if system == "Windows":
        candidates = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "LM Studio", "lms.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", ""), "LM Studio", "lms.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "LM Studio", "lms.exe"),
            os.path.join(home, "AppData", "Local", "LM Studio", "lms.exe"),
        ]
    elif system == "Darwin":
        candidates = [
            "/Applications/LM Studio.app/Contents/Resources/lms",
            os.path.join(home, "Applications", "LM Studio.app", "Contents", "Resources", "lms"),
        ]
    else:  # Linux
        candidates = [
            "/usr/local/bin/lms",
            "/usr/bin/lms",
            os.path.join(home, ".local", "bin", "lms"),
            os.path.join(home, "snap", "lm-studio", "current", "lms"),
        ]

    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)

    return None


# ── CLI runner ─────────────────────────────────────────────────────

def _run_lms(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """
    Run ``lms`` with the given arguments and return (returncode, stdout, stderr).

    Parameters
    ----------
    args : list[str]
        Arguments to pass to the lms CLI (excluding the binary path itself).
    timeout : int
        Timeout in seconds.

    Returns
    -------
    (returncode, stdout, stderr)
    """
    lms_path = _get_lms_path()
    if lms_path is None:
        return (1, "", "lms binary not found")

    cmd = [lms_path] + args

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (proc.returncode, proc.stdout, proc.stderr)
    except FileNotFoundError:
        return (1, "", f"lms binary not found at {lms_path}")
    except subprocess.TimeoutExpired:
        return (124, "", f"lms command timed out after {timeout}s")
    except Exception as exc:
        return (1, "", str(exc))


# ── Model management ───────────────────────────────────────────────

def get_models() -> list[str]:
    """
    Query LM Studio for a list of available models via ``lms ls``.

    Returns
    -------
    list[str]
        Model identifiers (e.g. ``["local-model-name", ...]``).
        Empty list if not found or on error.
    """
    rc, stdout, stderr = _run_lms(["ls"])
    if rc != 0:
        return []

    models: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        # Skip headers and metadata
        if name in ("You", "LLM", "EMBEDDING", "NAME"):
            continue
        if name.startswith("-"):
            continue
        if name.isupper():
            continue
        # Skip status markers
        if name.startswith("("):
            continue
        models.append(name)

    return models


def get_loaded_models() -> list[str]:
    """
    Query LM Studio for currently loaded models via ``lms ps``.
    """
    rc, stdout, stderr = _run_lms(["ps"])
    if rc != 0:
        return []

    loaded = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("-") or "IDENTIFIER" in line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            name = parts[1]  # parts[0]=identifier, parts[1]=model name
            if not name.startswith("("):
                loaded.append(name)
    return loaded


def load_model(
    model_name: str,
    identifier: Optional[str] = None,
    context_length: int = 4096,
) -> bool:
    """
    Load a model via ``lms load``.

    Does **not** pass ``--gpu max``; LM Studio uses its own
    ``priorityOrder`` strategy instead.

    Parameters
    ----------
    model_name : str
        The model name known to ``lms`` (as shown by ``lms ls``).
    identifier : str or None
        Optional specific identifier (e.g. the full path or huggingface id).
    context_length : int
        Context length in tokens.

    Returns
    -------
    bool
        ``True`` if the model was loaded successfully (returncode 0).
    """
    args = ["load", model_name, "--context-length", str(context_length)]
    if identifier:
        args.extend(["--identifier", identifier])

    rc, stdout, stderr = _run_lms(args, timeout=120)
    return rc == 0


def unload_all() -> bool:
    """
    Unload all models via ``lms unload --all``.

    Returns
    -------
    bool
        ``True`` on success.
    """
    rc, stdout, stderr = _run_lms(["unload", "--all"], timeout=30)
    return rc == 0


def get_loaded_models() -> list[str]:
    """查询当前已加载的模型列表（lms ps）"""
    rc, stdout, stderr = _run_lms(["ps"])
    if rc != 0:
        return []
    loaded = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("IDENTIFIER") or line.startswith("---"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            name = parts[1]
            # 去掉 LM Studio 可能追加的 :N 后缀（如 modelname:2）
            if ":" in name:
                name = name.split(":")[0]
            loaded.append(name)
    return loaded


def ensure_model_loaded(
    model_name: str,
    context_length: int = 4096,
) -> bool:
    """
    Ensure a model is loaded in LM Studio memory.

    Uses ``lms ps`` to check current loaded models, and ``lms load``
    to load if necessary.

    Parameters
    ----------
    model_name : str
        Name of the model to check / load.
    context_length : int
        Context length (used only if loading is needed).

    Returns
    -------
    bool
        ``True`` if the model is now available in memory.
    """
    # Check currently loaded models via lms ps
    loaded = get_loaded_models()
    if model_name in loaded:
        return True

    # Unload any other loaded model before switching
    if loaded and loaded[0] != model_name:
        unload_all()
        time.sleep(1.0)

    # Try loading with retries
    for attempt in range(_LMS_MAX_RETRIES):
        ok = load_model(model_name, context_length=context_length)
        if ok:
            time.sleep(2.0)
            # Verify it actually loaded
            if model_name in get_loaded_models():
                return True
        if attempt < _LMS_MAX_RETRIES - 1:
            time.sleep(_LMS_RETRY_DELAY_S)

    return False


# ── HTTP API helpers ───────────────────────────────────────────────

def check_available(base_url: str = _DEFAULT_BASE_URL) -> bool:
    """
    Ping the LM Studio API to see if it's running.

    Parameters
    ----------
    base_url : str
        Base URL of the LM Studio HTTP server.

    Returns
    -------
    bool
    """
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/models", timeout=5)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def generate_nl_from_lm_studio(
    tag_prompt: str,
    base_url: str = _DEFAULT_BASE_URL,
    api_key: str = "",
    model_name: str = "",
    detailed: bool = False,
    timeout: int = 60,
) -> str:
    """
    Use the LM Studio (or compatible OpenAI) chat completions endpoint
    to turn a tag prompt into a fluent natural-language description.

    Parameters
    ----------
    tag_prompt : str
        Comma-separated tags to describe.
    base_url : str
        API base URL (local LM Studio or cloud endpoint).
    api_key : str
        API key for cloud endpoints (leave empty for local LM Studio).
    model_name : str
        Model name to use in the request body (required for cloud APIs;
        LM Studio local server ignores this).
    timeout : int
        HTTP request timeout.

    Returns
    -------
    str
        Generated natural-language text, or empty string on failure.
    """
    if not tag_prompt.strip():
        return ""

    if detailed:
        system_msg = (
            "You are an AI assistant that writes highly detailed, cinematic "
            "natural-language descriptions for image generation prompts. Given a list "
            "of Danbooru-style tags, write a vivid and immersive English description "
            "(about 6 sentences) that paints a complete picture of the scene. "
            "Describe the subject first (appearance, clothing, pose, expression), "
            "then describe the background and environment at the very end. "
            "Do not repeat tags verbatim. "
            "IMPORTANT: You MUST write in English only. Do NOT use Chinese or any other language."
        )
        user_msg = (
            "Write a detailed English description (about 6 sentences) "
            "for these tags. Put background/environment description at the end:\n\n"
            f"{tag_prompt}\n\n"
            "English only, about 6 sentences, background at the end:"
        )
        max_tokens = 1024
    else:
        system_msg = (
            "You are an AI assistant that writes natural-language descriptions "
            "for image generation prompts. Given a list of Danbooru-style tags, "
            "write a concise, fluent English description (1-3 sentences) that "
            "captures the scene. Do not repeat tags verbatim. Be coherent and vivid. "
            "IMPORTANT: You MUST write in English only. Do NOT use Chinese or any other language."
        )
        user_msg = (
            "Write an English natural language description for these tags:\n\n"
            f"{tag_prompt}\n\n"
            "English only, 1-3 sentences:"
        )
        max_tokens = 256

    payload: dict[str, Any] = {
        "model": model_name or "default",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
        "stream": False,
    }

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "").strip()
        # Clean: remove dashes and em-dashes
        content = content.replace("—", "").replace("–", "").replace("---", "").replace("--", "")
        # Truncate detailed mode to 800 chars at sentence boundary
        if detailed and len(content) > 800:
            # Find the last sentence end within 800 chars
            truncated = content[:800]
            last_end = max(truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))
            if last_end > 300:  # only truncate at a reasonable sentence boundary
                content = content[:last_end + 1]
            else:
                content = truncated.rstrip(",; ") + "."
        return content
    except requests.RequestException:
        return ""
    except (json.JSONDecodeError, KeyError, IndexError):
        return ""
