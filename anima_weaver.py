"""
Anima Weaver — Main ComfyUI Node

Provides the ``AnimaWeaver`` custom node that:
  - Accepts up to 8 tag slots
  - Optionally pulls random tags from Raffle taglist files
  - Merges manual + random tags (hybrid mode)
  - Runs conflict detection
  - Assembles a final prompt via ``assembly.assemble_prompt``
  - Optionally generates natural-language descriptions via LM Studio
"""

from __future__ import annotations

import json
import os
import random
import re
from typing import Any, Optional

try:
    from .rules import check_conflicts, CONFLICT_PAIRS
    from .assembly import assemble_prompt, mix_by_ratio, SLOT_ORDER, SLOT_LIMITS
except ImportError:
    from rules import check_conflicts, CONFLICT_PAIRS
    from assembly import assemble_prompt, mix_by_ratio, SLOT_ORDER, SLOT_LIMITS

# ── Artist index (lazy loaded) ────────────────────────────────────────

import os as _os

_ARTIST_LIST: list[str] | None = None
_ARTIST_FILE = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "tags", "Anima2B_Artist_Index_59k.txt",
)

def _load_artists() -> list[str]:
    global _ARTIST_LIST
    if _ARTIST_LIST is not None:
        return _ARTIST_LIST
    artists: list[str] = []
    try:
        with open(_ARTIST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("This"):
                    continue
                if line.startswith("@"):
                    artists.append(line)
        _ARTIST_LIST = artists
        print(f"Anima Weaver: loaded {len(artists)} artists")
    except Exception as e:
        print(f"Anima Weaver: failed to load artist index: {e}")
        _ARTIST_LIST = artists
    return _ARTIST_LIST


# ── ComfyUI Node ────────────────────────────────────────────────────

class AnimaWeaver:
    """
    Anima Prompt Weaver — ComfyUI custom node.

    Combines manual tags, Raffle random tags, and optional LM Studio
    natural-language description into a single weighted prompt.
    """

    # 类级别缓存
    _raffle_tag_data = None  # 缓存已加载的 taglist

    # ── Input schema ──────────────────────────────────────────────

    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
        """Define the ComfyUI input widget schema."""
        # Try to get available LM Studio models
        model_list: list[str] = []
        try:
            from .lm_studio import get_models
            models = get_models()
            if models:
                model_list = models
        except Exception:
            pass
        if not model_list:
            model_list = ["(no models found)"]

        return {
            "required": {
                # ── Mode ──────────────────────────────────────────
                "模式": (
                    ["manual", "random", "hybrid"],
                    {"default": "hybrid"},
                ),
                "标签比例": (
                    "FLOAT",
                    {"default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05},
                ),
                "场景类型": (
                    [
                        "solo_display",
                        "couple_foreplay",
                        "couple_sex",
                        "group",
                        "yuri",
                        "special_theme",
                    ],
                ),

                # ── 8 tag slots ───────────────────────────────────
                "人数/身份": (
                    "STRING",
                    {"multiline": True, "default": "1girl, solo"},
                ),
                "外貌": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),
                "服装": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),
                "姿势/动作": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),
                "表情": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),
                "镜头": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),
                "场景/环境": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),
                "细节/氛围": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),

                # ── Natural Language ──────────────────────────────
                "自然语言来源": (
                    ["manual", "lm_studio"],
                    {"default": "manual"},
                ),
                "模型": (model_list,),
                "生成后卸载": (
                    "BOOLEAN",
                    {"default": False},
                ),
                "API密钥": (
                    "STRING",
                    {"default": "", "password": True},
                ),
                "云端模型名": (
                    "STRING",
                    {"default": "", "tooltip": "云端模型名（如 deepseek-chat），填 API 密钥时此值会覆盖下拉框的模型选择"},
                ),
                "上下文长度": (
                    "INT",
                    {"default": 4096, "min": 512, "max": 32768},
                ),
                "API地址": (
                    "STRING",
                    {"default": "http://localhost:1234/v1"},
                ),
                "自然语言描述": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),
                "强制详细自然语言": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "开启后 NL 描述至少 10 句，非常详细（使用 1024 tokens）"},
                ),

                # ── Artist ──────────────────────────────────────────
                "随机抽取画师": (
                    "BOOLEAN",
                    {"default": False, "tooltip": "从 Anima2B 画师索引中随机抽取 1 个画师标签，放在提示词最末尾"},
                ),
                "画师种子": (
                    "INT",
                    {"default": 0, "min": 0, "max": 0x7FFFFFFF},
                ),

                # ── Raffle random parameters ──────────────────────
                "随机种子": (
                    "INT",
                    {"default": 0, "min": 0, "max": 0xFFFF_FFFF_FFFF_FFFF},
                ),
                "生成后控制": (
                    ["randomize", "fixed", "increment", "decrement"],
                    {"default": "randomize"},
                ),
                "通用标签": (
                    "BOOLEAN",
                    {"default": False},
                ),
                "争议标签": (
                    "BOOLEAN",
                    {"default": False},
                ),
                "敏感标签": (
                    "BOOLEAN",
                    {"default": True},
                ),
                "露骨标签": (
                    "BOOLEAN",
                    {"default": True},
                ),
                "标签列表必含": (
                    "STRING",
                    {"multiline": True, "default": "1girl"},
                ),
                "过滤标签": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),
                "排除含标签列表": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),
                "排除标签分类": (
                    "STRING",
                    {"multiline": True, "default": ""},
                ),
                "冲突检查": (
                    "BOOLEAN",
                    {"default": True},
                ),
            },
            "optional": {
                "画幅比例": (
                    "STRING",
                    {"default": "", "tooltip": "从「随机分辨率选择器」节点接入画幅比例，用于 NL 生成时描述构图"},
                ),
            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("生成的提示词", "调试信息")
    FUNCTION = "compose"
    OUTPUT_NODE = True

    # ── Cache control ─────────────────────────────────────────────
    #
    # NOTE(seed-randomize): ComfyUI 新版 web UI 对 IS_CHANGED 的支持因版本而异。
    # 如果 randomize 模式下种子仍不更新，可能是前端未正确传递变更信号。
    # 临时方案：在 compose() 中通过 kwargs["随机种子"] = random.randint(...)
    # 内部随机化，但 ComfyUI 缓存机制可能绕过 compose() 直接返回缓存结果。
    # 终极解决：等待 ComfyUI 新版修复前端 seed control 行为。

    @classmethod
    def IS_CHANGED(cls, **kwargs) -> float:
        """
        Control ComfyUI caching behaviour.

        - ``randomize``: return a random value → always re-execute.
        - ``increment``/``decrement``: mutate the cached seed → re-execute.
        - ``fixed`` (or any other value): use the raw seed as-is.
        """
        control = kwargs.get("生成后控制", "fixed")
        if control == "randomize":
            # Force a fresh execution every time
            return random.random()
        if control in ("increment", "decrement"):
            # Always re-execute so the node can mutate the seed
            return random.random()
        return float(kwargs.get("随机种子", 0))

    # ── Main composition entry point ──────────────────────────────

    def compose(self, **kwargs) -> tuple[str, str]:
        """
        Main node workflow.

        Parameters
        ----------
        **kwargs
            All widget values as keyword arguments.

        Returns
        -------
        (final_prompt, debug_info)
        """
        mode = kwargs.get("模式", "hybrid")
        tag_ratio = float(kwargs.get("标签比例", 0.6))
        nl_source = kwargs.get("自然语言来源", "manual")
        enable_conflict = bool(kwargs.get("冲突检查", True))

        # ── Seed control ────────────────────────────────────────────
        raw_seed = int(kwargs.get("随机种子", 0))
        seed_control = kwargs.get("生成后控制", "randomize")
        if seed_control == "randomize":
            raw_seed = random.randint(0, 0xFFFF_FFFF_FFFF_FFFF)
        elif seed_control == "increment":
            raw_seed = (raw_seed + 1) % (0xFFFF_FFFF_FFFF_FFFF + 1)
        elif seed_control == "decrement":
            raw_seed = (raw_seed - 1) % (0xFFFF_FFFF_FFFF_FFFF + 1)
        # Inject the controlled seed back so _run_raffle picks it up
        kwargs["随机种子"] = raw_seed

        debug_lines: list[str] = [f"Mode: {mode}", f"Seed: {raw_seed} ({seed_control})"]

        # ── 1. Collect manual slot tags ──────────────────────────
        manual_slots: dict[str, str] = {}
        slot_keys = [
            ("人数/身份", "count_identity"),
            ("外貌", "appearance"),
            ("服装", "clothing"),
            ("姿势/动作", "pose_action"),
            ("表情", "expression"),
            ("镜头", "camera"),          # note mapping
            ("场景/环境", "scene"),
            ("细节/氛围", "detail_mood"),
        ]
        for kw_key, slot_name in slot_keys:
            val = kwargs.get(kw_key, "").strip()
            manual_slots[slot_name] = val

        # ── 2. Random / Hybrid: run Raffle extraction ────────────
        raffle_slots: dict[str, list[str]] = {}
        if mode in ("random", "hybrid"):
            debug_lines.append("→ Running Raffle extraction …")
            raffle_slots = self._run_raffle(kwargs)
            debug_lines.append(
                f"  Raffle slots filled: "
                f"{sum(1 for v in raffle_slots.values() if v)}"
            )

        # ── 3. Merge slots ───────────────────────────────────────
        merged = self._merge_slots(mode, manual_slots, raffle_slots)
        debug_lines.append("Merged slots:")
        for slot in SLOT_ORDER:
            v = merged.get(slot, "")
            n = len([x for x in v.split(",") if x.strip()]) if v else 0
            debug_lines.append(f"  {slot}: {n} tags")

        # ── 4. Build the tag-only prompt ─────────────────────────
        tag_prompt = self._slots_to_string(merged)

        # ── 5. Conflict check & removal ──────────────────────────
        if enable_conflict and tag_prompt.strip():
            all_tags = [t.strip() for t in tag_prompt.split(",") if t.strip()]
            conflicts = check_conflicts(all_tags)
            if conflicts:
                debug_lines.append("⚠ Conflicts detected: " + "; ".join(conflicts))
                # Remove Raffle-sourced conflicting tags, keeping manual
                tag_prompt = self._remove_conflicts(tag_prompt, conflicts, manual_slots)
                debug_lines.append("  → Conflicting Raffle tags removed")

            # ── 5b. Deduplicate exact duplicate tags ──────────────
            seen: set[str] = set()
            deduped: list[str] = []
            dupes_found = 0
            for t in tag_prompt.split(","):
                t_clean = t.strip().lower().replace(" ", "_")
                if not t_clean:
                    continue
                if t_clean in seen:
                    dupes_found += 1
                    continue
                seen.add(t_clean)
                deduped.append(t.strip())
            if dupes_found:
                tag_prompt = ", ".join(deduped)
                debug_lines.append(f"⚠ Removed {dupes_found} duplicate tag(s)")

            if not conflicts and not dupes_found:
                debug_lines.append("✓ No conflicts")

        # ── 6. Generate NL part ──────────────────────────────────
        nl_prompt = self._get_nl(kwargs, tag_prompt, nl_source)

        # ── 6b. Reorder ALL background content to absolute end ──
        bg_tag_keywords = ["background", "outdoors", "outdoor"]
        bg_nl_keywords = [
            "background", "against a", "against the", "set in", "set against",
            "in the background", "in front of", "behind", "surrounded by",
            "scene is set", "environment",
        ]

        # Split tags into bg / non-bg
        tag_items = [t.strip() for t in tag_prompt.split(",") if t.strip()]
        bg_tags = [t for t in tag_items
                   if any(kw in t.lower().replace("_", " ") for kw in bg_tag_keywords)]
        non_bg_tags = [t for t in tag_items if t not in bg_tags]

        # Split NL into bg / non-bg
        import re
        nl_sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', nl_prompt) if s.strip()]
        bg_nl = [s for s in nl_sentences
                 if any(kw in s.lower() for kw in bg_nl_keywords)]
        non_bg_nl = [s for s in nl_sentences if s not in bg_nl]

        # ── 7. Assemble: non-bg mixed first, then all bg at end ──
        main_part = mix_by_ratio(
            ", ".join(non_bg_tags),
            " ".join(non_bg_nl),
            tag_ratio,
        )
        # Build bg_part respecting tag_ratio:
        #   ratio=1.0 → only bg tags
        #   ratio=0.0 → only bg NL
        #   otherwise → both
        bg_tag_str = ", ".join(bg_tags)
        bg_nl_str = " ".join(bg_nl)

        bg_parts = []
        if bg_tag_str:
            bg_parts.append(bg_tag_str)
        if bg_nl_str and tag_ratio < 1.0:
            bg_parts.append(bg_nl_str)

        bg_part = ", ".join(bg_parts) if bg_parts else ""

        if bg_part:
            final = (main_part + ", " + bg_part) if main_part else bg_part
        else:
            final = main_part

        # ── 8. Random artist pick (placed at absolute end) ──────
        pick_artist = kwargs.get("随机抽取画师", False)
        if pick_artist:
            artists = _load_artists()
            if artists:
                artist_seed = int(kwargs.get("画师种子", 0))
                rng_artist = random.Random(artist_seed)
                chosen = rng_artist.choice(artists)
                if final:
                    final = final.rstrip(", ") + ", " + chosen
                else:
                    final = chosen
                debug_lines.append(f"Artist: {chosen}")

        debug_lines.append(
            f"Tag ratio: {tag_ratio}\n"
            f"Tags: {len(tag_prompt)} chars\n"
            f"NL:   {len(nl_prompt)} chars"
        )

        return (final, "\n".join(debug_lines))

    # ── Slot merging ───────────────────────────────────────────────

    @staticmethod
    def _merge_slots(
        mode: str,
        manual: dict[str, str],
        raffle: dict[str, list[str]],
    ) -> dict[str, str]:
        """
        Merge manual and Raffle tags per slot.

        Strategy:
          manual   → pure manual
          random   → pure Raffle
          hybrid   → Raffle (up to 8) + manual appended (higher weight)
        """
        merged: dict[str, str] = {}
        for slot in SLOT_ORDER:
            manual_tags = manual.get(slot, "").strip()
            raffle_tags = raffle.get(slot, [])

            if mode == "manual":
                merged[slot] = manual_tags

            elif mode == "random":
                merged[slot] = ", ".join(raffle_tags)

            elif mode == "hybrid":
                combined = list(raffle_tags[:8])  # cap Raffle at 8
                if manual_tags:
                    manual_list = [
                        t.strip()
                        for t in manual_tags.split(",")
                        if t.strip()
                    ]
                    combined.extend(manual_list)
                merged[slot] = ", ".join(combined)

        return merged

    # ── Raffle extraction ──────────────────────────────────────────

    @staticmethod
    def _run_raffle(kwargs: dict[str, Any]) -> dict[str, list[str]]:
        """
        Pick a random taglist line from the configured Raffle files,
        classify each tag via ``categorized_tags.txt``, and map
        categories to slots via ``category_to_slot.json``.

        Returns a dict ``{slot_name: [tag_str, ...]}``.
        """
        extension_path = os.path.dirname(os.path.abspath(__file__))
        tags_dir = os.path.join(extension_path, "tags")

        # ── Determine which files to use ─────────────────────────
        file_flags = [
            ("通用标签", "taglists-general.txt"),
            ("争议标签", "taglists-questionable.txt"),
            ("敏感标签",  "taglists-sensitive.txt"),
            ("露骨标签",   "taglists-explicit.txt"),
        ]
        enabled_files: list[str] = []
        for flag, fname in file_flags:
            if kwargs.get(flag, False):
                enabled_files.append(fname)
        if not enabled_files:
            # Fallback default
            enabled_files = ["taglists-sensitive.txt", "taglists-explicit.txt"]

        # ── Load category → slot mapping ─────────────────────────
        cat_map_path = os.path.join(tags_dir, "category_to_slot.json")
        try:
            with open(cat_map_path, "r", encoding="utf-8") as f:
                cat_to_slot: dict[str, str] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

        # ── Load category tags index ─────────────────────────────
        #   Format: "[category] tag_name"
        tag_to_category: dict[str, str] = {}
        cat_tags_path = os.path.join(tags_dir, "categorized_tags.txt")
        try:
            with open(cat_tags_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Expected: "[category] tag"
                    if line.startswith("[") and "] " in line:
                        parts = line.split("] ", 1)
                        category = parts[0][1:]  # strip leading '['
                        tag = parts[1].strip().lower().replace(" ", "_")
                        tag_to_category[tag] = category
        except FileNotFoundError:
            return {}

        # ── Filter parameters ────────────────────────────────────
        exclude_containing = _parse_comma_field(
            kwargs.get("排除含标签列表", "")
        )
        must_include = _parse_comma_field(
            kwargs.get("标签列表必含", "")
        )
        excluded_cats = _parse_comma_field(
            kwargs.get("排除标签分类", "")
        )
        filter_out = _parse_comma_field(
            kwargs.get("过滤标签", "")
        )

        # ── Seed random ──────────────────────────────────────────
        seed = int(kwargs.get("随机种子", 0))
        rng = random.Random(seed)

        # ── Pick a random file (weighted by seed) ────────────────
        rng.shuffle(enabled_files)
        selected_file = enabled_files[seed % len(enabled_files)]
        filepath = os.path.join(tags_dir, selected_file)

        # ── Scan for valid tag lists ─────────────────────────────
        valid_taglists: list[list[str]] = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    # Format: post_id, resolution, tag1, tag2, ...
                    parts = line.strip().split(", ", 2)
                    if len(parts) >= 3:
                        tags_str = parts[2]
                    else:
                        continue

                    tag_set: list[str] = [
                        t.strip().lower().replace(" ", "_")
                        for t in tags_str.split(", ")
                        if t.strip()
                    ]

                    # Filter: exclude lists containing certain tags
                    if exclude_containing:
                        if not set(tag_set).isdisjoint(exclude_containing):
                            continue

                    # Filter: must include certain tags
                    if must_include:
                        if not must_include.issubset(set(tag_set)):
                            continue

                    valid_taglists.append(tag_set)
                    if len(valid_taglists) >= 5000:
                        break
        except FileNotFoundError:
            return {}

        if not valid_taglists:
            return {}

        # ── Pick one line ────────────────────────────────────────
        selected_tags = valid_taglists[seed % len(valid_taglists)]

        # ── Classify into slots ─────────────────────────────────
        slot_tags: dict[str, list[str]] = {slot: [] for slot in SLOT_ORDER}

        for tag in selected_tags:
            tag_clean = tag.strip().lower().replace(" ", "_")

            if not tag_clean:
                continue
            if tag_clean in filter_out:
                continue

            category = tag_to_category.get(tag_clean, "")
            if not category:
                continue
            if category in excluded_cats:
                continue

            target_slot = cat_to_slot.get(category, "")
            if target_slot in slot_tags:
                slot_tags[target_slot].append(tag_clean)

        return slot_tags

    # ── Tag-string utility ────────────────────────────────────────

    @staticmethod
    def _slots_to_string(merged_slots: dict[str, str]) -> str:
        """Flatten slot dict into a single comma-separated tag string."""
        parts: list[str] = []
        for slot in SLOT_ORDER:
            val = merged_slots.get(slot, "").strip()
            if val:
                parts.append(val)
        return ", ".join(parts)

    # ── NL generation ─────────────────────────────────────────────

    @staticmethod
    def _get_nl(
        kwargs: dict[str, Any],
        tag_prompt: str,
        nl_source: str,
    ) -> str:
        """
        Obtain the natural-language portion of the prompt.

        If ``nl_source == "lm_studio"`` and a model is configured, try
        to generate text via the LM Studio HTTP API (local or cloud).
        Otherwise return the manual NL text.
        """
        if nl_source == "lm_studio" and tag_prompt.strip():
            lm_model = kwargs.get("模型", "")
            if lm_model and lm_model != "(no models found)":
                model_was_loaded = False
                nl = ""
                try:
                    from .lm_studio import (
                        ensure_model_loaded,
                        generate_nl_from_lm_studio,
                        get_loaded_models,
                        unload_all,
                    )
                    ctx = int(kwargs.get("上下文长度", 4096))
                    base_url = str(
                        kwargs.get("API地址", "http://localhost:1234/v1")
                    )
                    api_key = kwargs.get("API密钥", "")
                    cloud_model = kwargs.get("云端模型名", "").strip()
                    detailed_nl = bool(kwargs.get("强制详细自然语言", False))
                    aspect_ratio = str(kwargs.get("画幅比例", "") or "")

                    if api_key:
                        # 云端 API：跳过 lms load，直接发请求
                        model_for_api = cloud_model or lm_model
                        nl = generate_nl_from_lm_studio(
                            tag_prompt, base_url,
                            api_key=api_key, model_name=model_for_api,
                            detailed=detailed_nl,
                            aspect_ratio=aspect_ratio,
                        )
                    else:
                        # 本地 LM Studio：先加载模型再调用 API
                        model_was_loaded = ensure_model_loaded(lm_model, context_length=ctx)
                        if model_was_loaded:
                            nl = generate_nl_from_lm_studio(
                                tag_prompt, base_url,
                                model_name=lm_model,
                                detailed=detailed_nl,
                                aspect_ratio=aspect_ratio,
                            )

                    if nl:
                        return nl
                except Exception:
                    pass
                finally:
                    # 无论成功失败，只要要求卸载且模型被加载过就卸载
                    if kwargs.get("生成后卸载", False) and model_was_loaded:
                        try:
                            from .lm_studio import unload_all
                            unload_all()
                        except Exception:
                            pass
        return kwargs.get("自然语言描述", "")

    # ── Conflict removal ──────────────────────────────────────────

    @staticmethod
    def _remove_conflicts(
        tag_prompt: str,
        conflicts: list[str],
        manual_slots: dict[str, str],
    ) -> str:
        """
        Remove Raffle-sourced conflicting tags from *tag_prompt*,
        preserving any tags that came from the manual slots.

        Parameters
        ----------
        tag_prompt : str
            The full comma-separated tag prompt.
        conflicts : list[str]
            Conflict descriptions from ``check_conflicts``.
        manual_slots : dict[str, str]
            Manual slot dictionary to identify protected tags.

        Returns
        -------
        str
            Cleaned tag prompt.
        """
        # Collect all manual tags (normalised)
        manual_tags: set[str] = set()
        for slot in SLOT_ORDER:
            val = manual_slots.get(slot, "").strip()
            if val:
                for t in val.split(","):
                    mt = t.strip().lower().replace(" ", "_")
                    if mt:
                        manual_tags.add(mt)

        all_tags = [t.strip() for t in tag_prompt.split(",") if t.strip()]
        to_remove: set[str] = set()

        for tag_a, tag_b in CONFLICT_PAIRS:
            norm_a = tag_a.lower().replace(" ", "_")
            norm_b = tag_b.lower().replace(" ", "_")

            has_a = False
            has_b = False
            for t in all_tags:
                tn = t.lower().replace(" ", "_")
                if norm_a in tn:
                    has_a = True
                if norm_b in tn:
                    has_b = True

            if has_a and has_b:
                for t in all_tags:
                    tn = t.lower().replace(" ", "_")
                    if norm_a in tn and t not in manual_tags:
                        to_remove.add(t)
                    if norm_b in tn and t not in manual_tags:
                        to_remove.add(t)

        result = [t for t in all_tags if t not in to_remove]
        return ", ".join(result)

    # ── Background reordering ─────────────────────────────────────

    @staticmethod
    def _reorder_background_to_end(text: str, is_tags: bool) -> str:
        """Move background-related content to the very end."""
        if not text.strip():
            return text
        bg_keywords = [
            "background", "wall", "window", "door", "curtain", "floor",
            "ceiling", "indoors", "outdoors", "indoor", "outdoor",
            "behind", "scenery", "environment", "setting", "surrounding",
        ]
        if is_tags:
            items = [t.strip() for t in text.split(",") if t.strip()]
            bg = [i for i in items if any(kw in i.lower().replace(" ", "_") for kw in bg_keywords)]
            other = [i for i in items if i not in bg]
            return ", ".join(other + bg) if bg else text
        else:
            import re
            ss = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
            bg = [s for s in ss if any(kw in s.lower() for kw in bg_keywords)]
            other = [s for s in ss if s not in bg]
            return " ".join(other + bg) if bg else text


# ── Helpers ────────────────────────────────────────────────────────

def _parse_comma_field(text: str) -> set[str]:
    """
    Parse a multiline or comma-separated text field into a set of
    normalised strings.

    Examples
    --------
    >>> _parse_comma_field("1girl, solo\\nblush")
    {'1girl', 'solo', 'blush'}
    """
    if not text or not text.strip():
        return set()
    return set(
        t.strip().lower().replace(" ", "_")
        for t in text.replace("\n", ",").split(",")
        if t.strip()
    )
