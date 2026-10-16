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
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Optional

import requests

# ── Module-level settings for crash recovery ──
_last_model_parallel: Optional[int] = None
_last_model_ctx: int = 4096
_load_lock = threading.Lock()

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
            os.path.join(home, ".lmstudio", "bin", "lms.exe"),  # 用户目录安装
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

    # 让子进程自成进程组，超时后可以整组杀掉（否则 lms 可能变成僵尸占住端口）。
    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except FileNotFoundError:
        return (1, "", f"lms binary not found at {lms_path}")
    except Exception as exc:
        return (1, "", str(exc))

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return (proc.returncode, stdout or "", stderr or "")
    except subprocess.TimeoutExpired:
        # 超时 → 杀整个进程组，再回收，避免残留子进程
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        return (124, "", f"lms command timed out after {timeout}s")


# ── Model management ───────────────────────────────────────────────

def _query_models_http(base_url: str = _DEFAULT_BASE_URL) -> list[str]:
    """HTTP 查询 OpenAI 兼容端点 GET {base}/models（2026-10-16 用户反馈：
    ComfyUI 进程里 lms CLI 常因 PATH/管理 API 未启用而查不到模型，但 LM
    Studio 的 OpenAI 服务通常一直开着 —— 改 HTTP 优先，3s 超时）。"""
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/models", timeout=3)
        if resp.status_code == 200:
            ids = [m.get("id") for m in resp.json().get("data", [])
                   if isinstance(m, dict) and m.get("id")]
            return sorted(set(ids))
    except Exception:
        pass
    return []


def _query_models() -> list[str]:
    """
    真实查询（会阻塞）：HTTP 优先，失败再退回 ``lms ls``。

    这是 get_models() 的内部实现，**不要直接对外** ——
    外面应统一走非阻塞的 get_models()（03 补丁）。轻量查询 timeout=5s。

    Returns
    -------
    list[str]
        Model identifiers.
    """
    models = _query_models_http()
    if models:
        return models
    rc, stdout, stderr = _run_lms(["ls"], timeout=5)
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


# ── 模型列表缓存（03 补丁）──────────────────────────────────────────
# 背景：ComfyUI 每次刷新页面 / 打开节点菜单都会请求 /object_info，
# anima_weaver.py:79 与 caption.py 的 INPUT_TYPES 都会调 get_models()，
# 也就是每次 fork 一个 lms 子进程。装了 LM Studio 但服务没响应时最坏阻塞 60s。
# 解决：缓存 5 分钟 + 过期后台线程刷新 + 未命中先返回缓存或占位，永不阻塞调用方。
_MODEL_CACHE: Optional[list[str]] = None
_MODEL_TS: float = 0.0
_MODEL_TTL: float = 300.0          # 5 分钟
_MODEL_LOCK = threading.Lock()
_MODEL_REFRESHING: bool = False
_MODEL_PLACEHOLDER = "(检测中…)"


def get_models() -> list[str]:
    """
    非阻塞版模型列表查询（03 补丁）。函数签名与返回类型 ``list[str]`` 保持不变，
    因此 anima_weaver.py:79 / caption.py 无需改动即可受益。

    - 命中缓存（5 分钟内）：直接返回缓存
    - 未命中 / 已过期：立刻返回占位符（或上次的结果），后台线程去刷新
    任何情况下都不会阻塞调用方。
    """
    # 只在此函数里给 _MODEL_REFRESHING 赋值；_MODEL_CACHE/_MODEL_TS 仅读取（写入在 _worker 内）
    global _MODEL_REFRESHING

    now = time.monotonic()
    with _MODEL_LOCK:
        if _MODEL_CACHE is not None and (now - _MODEL_TS) < _MODEL_TTL:
            return list(_MODEL_CACHE)
        # 已有后台线程在刷新 → 不重复起线程，返回现有内容或占位
        if _MODEL_REFRESHING:
            return list(_MODEL_CACHE) if _MODEL_CACHE else [_MODEL_PLACEHOLDER]
        _MODEL_REFRESHING = True

    def _worker():
        global _MODEL_CACHE, _MODEL_TS, _MODEL_REFRESHING
        try:
            models = _query_models()
            with _MODEL_LOCK:
                if models:
                    _MODEL_CACHE = models
                _MODEL_TS = time.monotonic()
        except Exception:
            # 失败也记时间，避免疯狂重试
            with _MODEL_LOCK:
                _MODEL_TS = time.monotonic()
        finally:
            with _MODEL_LOCK:
                _MODEL_REFRESHING = False

    threading.Thread(target=_worker, name="anima-lms-ls", daemon=True).start()

    with _MODEL_LOCK:
        return list(_MODEL_CACHE) if _MODEL_CACHE else [_MODEL_PLACEHOLDER]


def get_models_cached() -> list[str]:
    """兼容别名（03 补丁命名）：等价于 get_models()。"""
    return get_models()


def invalidate_model_cache() -> None:
    """用户点「刷新模型列表」时调用：把时间戳清零，下次调用即触发后台刷新。"""
    global _MODEL_TS
    with _MODEL_LOCK:
        _MODEL_TS = 0.0


def load_model(
    model_name: str,
    identifier: Optional[str] = None,
    context_length: int = 4096,
    parallel: Optional[int] = None,
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
    parallel : int or None
        Max concurrent predictions.

    Returns
    -------
    bool
        ``True`` if the model was loaded successfully (returncode 0).
    """
    global _last_model_parallel, _last_model_ctx
    if parallel is not None:
        _last_model_parallel = parallel
    _last_model_ctx = context_length
    args = ["load", model_name, "--context-length", str(context_length)]
    if parallel is not None and parallel > 0:
        args.extend(["--parallel", str(parallel)])
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
    parallel: Optional[int] = None,
    force: bool = False,
) -> bool:
    """
    Ensure a model is loaded in LM Studio memory.

    Uses ``lms ps`` to check current loaded models, and ``lms load``
    to load if necessary.  Thread-safe: a module-level lock prevents
    multiple concurrent ``lms load`` calls from creating duplicate
    model instances (which LM Studio treats as separate copies with
    ``:2``, ``:3`` … identifiers).
    """
    # Fast path — quick check without lock
    loaded = get_loaded_models()
    if model_name in loaded:
        if parallel is not None and parallel > 0:
            cur_p = 0
            try:
                info = _run_lms(["ps", "--json"], timeout=10)
                if info[0] == 0 and info[1]:
                    import json as _jj
                    for m in _jj.loads(info[1]) if isinstance(_jj.loads(info[1]), list) else []:
                        if m.get("id", "") == model_name:
                            cur_p = m.get("parallel", 0)
            except Exception:
                pass
            if cur_p and cur_p != parallel and not force:
                print(f"[LM Studio] Slot mismatch: current={cur_p}, desired={parallel}, force reload...")
            elif cur_p and cur_p == parallel and not force:
                return True
            elif cur_p and cur_p != parallel and force:
                pass  # fall through to reload
        else:
            return True
        if parallel is not None and parallel > 0:
            try:
                info = _run_lms(["ps", "--json"], timeout=10)
                if info[0] == 0 and info[1]:
                    import json as _jj
                    models_info = _jj.loads(info[1])
                    for m in models_info if isinstance(models_info, list) else []:
                        if m.get("instance_ref", "") == model_name or m.get("id", "") == model_name:
                            cur_parallel = m.get("parallel", 0)
                            if cur_parallel and cur_parallel != parallel:
                                print(f"[LM Studio] Slot mismatch: current={cur_parallel}, desired={parallel}, reloading...")
                                break
            except Exception:
                pass
        return True

    # Unload any other loaded model before switching
    if loaded and loaded[0] != model_name:
        unload_all()
        time.sleep(1.0)

    # Serialise the actual load so concurrent callers don't each create
    # a separate model instance.
    with _load_lock:
        # Double-check: another thread may have loaded it while we waited
        if model_name in get_loaded_models():
            return True

        # Try loading with retries
        for attempt in range(_LMS_MAX_RETRIES):
            ok = load_model(model_name, context_length=context_length, parallel=parallel)
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
    aspect_ratio: str = "",
    timeout: int = 180,
    system_prompt: str = "",
    max_tokens_override: int = 0,
    image_b64: str = "",
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
            system_prompt if system_prompt else
            "You are a description generator for image prompts. Your task: given Danbooru-style tags, "
            "write ONE continuous paragraph describing the image. "
            "RULES: "
            "1) Write ONLY the description. "
            "2) No meta-commentary, analysis, thinking, or explanations of any kind. "
            "3) No bullet points, no numbered lists, no line breaks, no prefixes. "
            "4) Do not repeat tags verbatim. "
            "5) Describe the subject, appearance, clothing, pose, expression, lighting, background in that order. "
            "6) Put background/environment at the very end. "
            "7) English only. "
            "8) At least 6 sentences. "
            "9) Do NOT include resolution, aspect ratio, or dimension information in the output. "
            "FAILURE MODE: If you output anything other than the description (explanations, "
            "thinking, analysis, tag comments, etc.), the output will be rejected."
        )
        user_msg = (
            f"{tag_prompt}\n\n"
            "Write an exhaustive, extremely detailed description. "
            "Describe the subject, appearance, clothing, pose, expression, "
            "lighting, background, colors, composition, and aesthetic style. "
            "Use precise descriptive language. DO NOT stop early. "
            "Keep writing until you have described every single visible detail."
        )
        if aspect_ratio:
            user_msg += f" Resolution: {aspect_ratio}."
        max_tokens = 1024
    else:
        system_msg = (
            system_prompt if system_prompt else
            "You are a description generator for image prompts. "
            f"Given these tags: {tag_prompt}\n\n"
            "Write ONLY a concise English description (1-3 sentences). "
            "RULES: No analysis. No commentary. No thinking. No line breaks. "
            "No bullet points. No prefixes. No meta-commentary. "
            "Just the description, as a single paragraph."
        )
        user_msg = "Description only, 1-3 sentences, English:"
        max_tokens = 512

    if max_tokens_override > 0:
        max_tokens = max_tokens_override

    # Build user content: text-only or text + image for VL models
    if image_b64:
        user_content: Any = [
            {"type": "text", "text": user_msg},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]
    else:
        user_content = user_msg

    payload: dict[str, Any] = {
        "model": model_name or "default",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.85,
        "max_tokens": max_tokens,
        "stream": False,
    }
    # enable_thinking only for LM Studio local API (not supported by cloud providers)
    # reasoning_effort=none: LM Studio 0.4.x+ 对思考型模型(如 Qwen3.5)只认这个字段；
    # 不加则 max_tokens 被思维链吃光、content 恒空（实测 reasoning_tokens==max_tokens）。
    # 两个字段并存无害：enable_thinking 服务 vLLM 系，reasoning_effort 服务 LM Studio。
    if not api_key:
        payload["enable_thinking"] = False
        payload["reasoning_effort"] = "none"

    # 修复 BUG-1：原写法 f"{base_url.rstrip("/")}/chat/completions" 在同类型引号内嵌套，
    # 只有 Python 3.12+ (PEP 701) 才允许；3.10/3.11（ComfyUI 主流环境）会 SyntaxError。
    # 改成显式字符串拼接，语义完全一致且全版本可用。
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            err_msg = data.get("error", {}).get("message", str(data)[:200])
            print(f"[LM Studio] API returned no choices. Error: {err_msg}")
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "").strip()
        # 有些推理模型把输出放在 reasoning_content 而非 content
        if not content:
            content = message.get("reasoning_content", "").strip()

        # ── Continuation: if model stopped very early, re-prompt ──
        # Only fires when output is suspiciously short (< max_tokens * 0.15)
        finish_reason = choices[0].get("finish_reason", "")
        if finish_reason == "stop" and content and len(content.split()) < max_tokens * 0.05:
            continuation_msg = (
                f"{content}\n\nContinue from where you left off. "
                "Keep writing in the same style. Do NOT repeat. "
                "Do NOT stop until you've covered every detail."
            )
            cont_payload = dict(payload)
            cont_payload["messages"] = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": continuation_msg},
            ]
            try:
                resp2 = requests.post(url, json=cont_payload, headers=headers, timeout=timeout)
                resp2.raise_for_status()
                data2 = resp2.json()
                choices2 = data2.get("choices", [])
                if choices2:
                    cont = choices2[0].get("message", {}).get("content", "").strip()
                    if cont and cont not in content:
                        content = content + " " + cont
            except Exception:
                pass

        # ═══ Extract description from reasoning preamble (BEFORE cleaning dashes) ═══
        # Some models output analysis steps like:
        # "1. **Identify** — The subject stands..." or "2. **Analyze the Tags:**\n  * tag1: desc"
        lines = content.split("\n")
        desc_parts: list[str] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Skip meta-commentary lines about the task itself
            lower_line = line.lower()
            if any(lower_line.startswith(p) for p in [
                "the prompt", "the user wants", "the user asked", "the task",
                "i need to", "i should", "i must", "this is a", "this sets",
                "sets the tone", "focus on", "introduce the", "core identity",
                "these are key", "weave these", "thinking about",
                "first draft", "first, i", "first, i should",
                "alright", "the tags are", "singular", "the goal is", "let's tackle",
                "reviewing against", "let me draft", "let me start",
                "first, consider", "first, think", "now, think", "now, combine",
                "now, structure", "now consider", "danbooru-style tags",
                "option 2", "option 1", "potential opening",
                "input tags", "english only", "not too long", "the hair",
                "let's think", "let's consider", "let me look at",
                "next, i", "so i need", "so i have",
                "a single female", "check if",
                "looking at the tags", "review against", "check for",
                "clothing:", "pose:", "expression:", "lighting:",
                "maybe ", "perhaps ", "i can keep", "i can tell",
                "could mean", "or maybe", "the lighting", "that sounds",
                "i'm combining", "implies that",
            ]):
                continue
            # Skip lines that start with backtick-quoted tags (echoing input)
            if line.startswith("`") and "`" in line[1:]:
                continue
            # Handle "Let me draft: ..." / "Let me start: ..." → extract after colon
            lower_line = line.lower()
            if any(lower_line.startswith(p) for p in ("let me draft", "let me start", "reviewing against", "next, describe", "so i need", "so i have", "combining")):
                if ":" in line:
                    _, after = line.split(":", 1)
                    after = after.strip().strip(' "\'')
                    if after and len(after) > 10:
                        desc_parts.append(after)
                    continue
                else:
                    continue
            # a) "1. **Title** — description text" (ONLY when line starts with a numbered/bulleted header)
            if " — " in line and any(line.lstrip().startswith(p) for p in ("1.", "2.", "3.", "4.", "5.", "6.", "1,", "2,", "3,", "1**", "2**", "**")):
                _, after = line.split(" — ", 1)
                after = after.strip().lstrip(",:; ")
                if after and len(after) > 10 and not after.startswith(("The goal", "Task:", "Constraint")):
                    # Strip leading "describes" / "description" meta-words
                    for prefix in ("describes ", "description ", "describe "):
                        if after.startswith(prefix):
                            after = after[len(prefix):].strip()
                            break
                    desc_parts.append(after)
                continue
            # b) "* tagged item: description" or "N. Title: description"
            if (": " in line and not line.startswith("http") and
                any(line.lstrip().startswith(p) for p in ("* ", "- ", "1.", "2.", "3.", "4.", "5.", "6.", "1,", "2,", "3,"))):
                _, after = line.split(": ", 1)
                after = after.strip().lstrip(",:; ")
                if after and len(after) > 10 and not after.startswith(("Write", "The goal", "Task:", "Constraint")):
                    desc_parts.append(after)
                continue
            # c) "Subject:" / "Features:" / "Core:" key-value lines
            # These don't start with numbers/* but are analysis headers.
            if re.match(r'^(Subject|Features|Expression|Core Subject|Setting|Pose|Action|Appearance|Clothing|Constraints):', line):
                _, after = line.split(":", 1)
                after = after.strip()
                if after and len(after) > 5 and not after.startswith(("describes",)):
                    # Check if value is comma-separated tags; join them
                    if "," in after:
                        parts = [p.strip() for p in after.split(",") if p.strip()]
                        desc_parts.append(", ".join(parts))
                    else:
                        desc_parts.append(after)
                continue
            # d) regular description line
            stripped = line.lstrip(' \t*"\u2014\u2013')
            lower = stripped.lower()
            # Skip tag-analysis lines with parentheticals and no verbs e.g. "hair (alternate), eyes (on Ada)"
            skip_analysis = ("(" in line and ")" in line
                 and not any(v in line.lower() for v in
                 [" stands", " wears", " holds", " sits", " lies", " walks", " runs",
                  " looks", " has ", " is a", " are ", " was ", " were ",
                  " wearing", " holding", " standing"]))
            if skip_analysis:
                pass
            elif any(lower.startswith(s) for s in ("a ", "an ", "the ", "she ", "he ", "it ", "this ", "her ", "his ", "in ", "with ")):
                desc_parts.append(line)
            elif (len(stripped.split()) >= 5
                  and (stripped[0].isupper() or not stripped[0].isascii())
                  and stripped[-1] in ".!?\u3002"
                  and not any(stripped.startswith(f"{n}.") for n in "0123456789")
                  and not stripped.startswith("*") and not stripped.startswith("-")):
                desc_parts.append(line)

        if desc_parts:
            content = " ".join(desc_parts)
        else:
            non_empty = [l for l in lines if l.strip()]
            if non_empty:
                content = "\n".join(non_empty)

        # Clean: remove dashes and em-dashes (after extraction so em-dash split still works)
        content = content.replace("\u2014", "").replace("\u2013", "").replace("---", "").replace("--", "")
        # Clean up any leading non-alpha chars
        content = content.lstrip(",:; \t\n\r -*\"\u2014\u2013")

        # Smart truncation: if finish_reason was "length", cut at last complete sentence
        if finish_reason == "length":
            last_period = max(content.rfind(". "), content.rfind("! "), content.rfind("? "),
                              content.rfind("\u3002"), content.rfind("\uff01"), content.rfind("\uff1f"))
            # Also check period at end of string (no trailing space)
            if content.endswith(".") and content.rfind(".", 0, -1) > len(content) * 0.3:
                content = content[:content.rfind(".", 0, -1) + 1]
            elif content.endswith("\u3002") and content.rfind("\u3002", 0, -1) > len(content) * 0.3:
                content = content[:content.rfind("\u3002", 0, -1) + 1]
            elif last_period > len(content) * 0.3:
                content = content[:last_period + 1]

        return content
    except requests.RequestException as e:
        try:
            body = e.response.text[:500] if hasattr(e, 'response') and e.response is not None else ""
        except Exception:
            body = ""
        # Model crash/reload: wait and retry once
        if any(kw in body.lower() for kw in ["crashed", "reloaded", "unloaded", "decode image", "attention ubatches"]):
            
            print(f"[LM Studio] Request error (no crash recovery): [{body[:200]}], "
                  f"returning empty")
        # 所有恢复路径失败或错误关键字不匹配，返回空字符串
        return ""
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"[LM Studio] Response parsing error: {e}")
        return ""
