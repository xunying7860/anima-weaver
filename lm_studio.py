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
import random
import re
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

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return (proc.returncode, proc.stdout or "", proc.stderr or "")
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

    Returns
    -------
    bool
        ``True`` if the model was loaded successfully (returncode 0).
    """
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
    if not api_key:
        payload["enable_thinking"] = False

    url = f"{base_url.rstrip("/")}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if "choices" in data:
            if data['choices']:
                msg = data['choices'][0].get('message', {})
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
        if finish_reason == "stop" and content and len(content.split()) < max_tokens * 0.15:
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
        print(f"[LM Studio] API request error: {e} | Body: {body}")
        return ""
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"[LM Studio] Response parsing error: {e}")
        return ""
