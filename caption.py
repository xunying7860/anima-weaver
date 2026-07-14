"""Anima Weaver — Image Caption Node (single + batch mode)."""

from __future__ import annotations

import random
from typing import Any


def _build_system_prompt(fmt: str = "") -> str:
    """Build system prompt. If fmt is empty, use generic description without prefix."""
    if not fmt.strip():
        return (
            "Based on the given resolution and tags, describe the image content in extremely "
            "detailed English. Include the subject's appearance, physique, clothing, pose, expression, "
            "background elements, lighting, camera angle, composition, color palette, and overall "
            "aesthetic style. Use precise terminology suitable for AI image generation prompts. "
            "Avoid vague or abstract words. Do not describe character names. "
            "Output in English, single line without line breaks. Return only the description itself. "
            "Do NOT include resolution or dimension information."
        )
    if ":" in fmt:
        desc_type, _, content = fmt.partition(":")
        desc_type = desc_type.strip() or "description"
        content = content.strip()
    else:
        content = ""
        desc_type = fmt.strip() or "description"
    return (
        f"「{content}」({desc_type})"
        "Based on the given resolution and tags, describe the image content in extremely "
        "detailed English. Include the subject's appearance, physique, clothing, pose, expression, "
        "background elements, lighting, camera angle, composition, color palette, and overall "
        "aesthetic style. Use precise terminology suitable for AI image generation prompts. "
        "Avoid vague or abstract words. Do not describe character names. "
        f"Output in English, single line without line breaks. Return only the {desc_type} text "
        "prefixed by the format above. Do NOT include resolution or dimension information."
    )


def _build_batch_prompt(fmt: str = "") -> str:
    """Build system prompt for batch/seed-driven mode (no image, pure NL generation)."""
    if fmt.strip():
        return _build_system_prompt(fmt)
    return (
        "Based on the given content and resolution, refine and expand the content into an extremely "
        "detailed, high-quality English natural language description suitable for AI image generation "
        "prompts. Preserve the original tags while adding detailed descriptions of the subject's "
        "appearance, physique, clothing, pose, expression, background environment, lighting, camera "
        "perspective, composition, and overall artistic style. Use precise, specific terminology "
        "appropriate for models such as Stable Diffusion. Avoid vague or abstract words. "
        "Do not describe character names. "
        "Output in English, single line without line breaks. Return only the refined content, "
        "nothing else. Do NOT include resolution or dimension information. "
        "Generate extensive detail and do not stop prematurely."
    )


def _tensor_to_b64(image_tensor) -> str:
    """Convert ComfyUI IMAGE tensor (B,H,W,3) to base64 JPEG string."""
    if image_tensor is None:
        return ""
    try:
        import torch
        from PIL import Image
        import io
        import base64
        img = image_tensor[0]  # first frame
        img = (img * 255).to(torch.uint8)
        img_np = img.cpu().numpy()
        pil_img = Image.fromarray(img_np)
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=95)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


class ImageCaption:
    @classmethod
    def INPUT_TYPES(cls) -> dict[str, Any]:
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
                "模型": (model_list,),
                "API地址": (
                    "STRING",
                    {"default": "http://localhost:1234/v1", "multiline": False,
                     "tooltip": "LM Studio API 地址（或兼容 OpenAI 的 API 地址）"},
                ),
                "API密钥": (
                    "STRING",
                    {"default": "", "password": True},
                ),
                "云端模型名": (
                    "STRING",
                    {"default": "deepseek-chat",
                     "tooltip": "云端视觉模型名，填 API 密钥时覆盖本地模型"},
                ),
                "上下文长度": (
                    "INT",
                    {"default": 4096, "min": 512, "max": 32768},
                ),
                "最大截断长度": (
                    "INT",
                    {"default": 1024, "min": 512, "max": 1080, "step": 8},
                ),
                "描述格式": (
                    "STRING",
                    {"default": "", "multiline": False,
                     "tooltip": "可选。输出前缀格式。纯文本=仅类型，格式「类型:内容」。不接时使用通用提示"},
                ),
                "生成后卸载": (
                    "BOOLEAN",
                    {"default": False},
                ),
            },
            "optional": {
                "随机种子": (
                    "INT",
                    {"forceInput": True, "default": 0, "min": 0, "max": 0xFFFF_FFFF_FFFF_FFFF},
                ),
                "图像": (
                    "IMAGE",
                    {"tooltip": "接入图像（可选），不接则仅基于 tag 生成描述"},
                ),
                "WD14标签": (
                    "STRING",
                    {"forceInput": True, "multiline": True, "default": "",
                     "tooltip": "WD14 tagger 输出的标签"},
                ),
                "分辨率": (
                    "STRING",
                    {"forceInput": True, "default": "",
                     "tooltip": "从「随机分辨率选择器」接入分辨率（如 1024x768）"},
                ),
                "自定义提示词": (
                    "STRING",
                    {"forceInput": True, "multiline": True, "default": "",
                     "tooltip": "自定义系统提示词，留空使用默认"},
                ),
                "种子串": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "接入批量种子串（每行一个），批量模式不接图片和WD14"},
                ),
                "提示词串": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "接入提示词串（透传）"},
                ),
                "画师串": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "接入画师串（透传）"},
                ),
                "分辨率串": (
                    "STRING",
                    {"forceInput": True, "multiline": True,
                     "tooltip": "接入分辨率串（透传），每行一个分辨率"},
                ),
                "待润色文本": (
                    "STRING",
                    {"forceInput": True, "multiline": True, "default": "",
                     "tooltip": "接入要润色的文本内容（批量模式下使用）"},
                ),
            },
        }

    CATEGORY = "Anima Weaver"
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("描述文本", "提示词串", "画师串", "分辨率串", "反推串")
    FUNCTION = "describe"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs) -> float:
        return random.random()

    def _generate_one(self, kwargs: dict, user_msg: str, system_prompt: str) -> str:
        from .lm_studio import generate_nl_from_lm_studio
        lm_model = str(kwargs.get("模型", ""))
        base_url = str(kwargs.get("API地址", "http://localhost:1234/v1"))
        api_key = str(kwargs.get("API密钥", "")).strip()
        cloud_model = str(kwargs.get("云端模型名", "deepseek-chat")).strip()
        # Pass image if connected
        image_b64 = _tensor_to_b64(kwargs.get("图像"))
        nl = ""
        if api_key:
            model_for_api = cloud_model or lm_model
            if model_for_api and model_for_api != "(no models found)":
                nl = generate_nl_from_lm_studio(
                    user_msg, base_url,
                    api_key=api_key, model_name=model_for_api,
                    detailed=True, timeout=180,
                    system_prompt=system_prompt,
                    max_tokens_override=int(kwargs.get("最大截断长度", 1024)),
                    image_b64=image_b64,
                )
        else:
            if lm_model and lm_model != "(no models found)":
                ctx = int(kwargs.get("上下文长度", 4096))
                from .lm_studio import ensure_model_loaded
                ensure_model_loaded(lm_model, context_length=ctx)
                nl = generate_nl_from_lm_studio(
                    user_msg, base_url,
                    model_name=lm_model,
                    detailed=True, timeout=180,
                    system_prompt=system_prompt,
                    max_tokens_override=int(kwargs.get("最大截断长度", 1024)),
                    image_b64=image_b64,
                )
        return nl

    def describe(self, **kwargs) -> tuple[str, str, str, str, str]:
        seed_str = kwargs.get("种子串", "").strip()

        # ── Mutual exclusion ────────────────────────────────────────────
        if seed_str:
            kwargs.pop("随机种子", None)
        cap_res_batch = kwargs.get("分辨率串", "")
        if cap_res_batch.strip():
            kwargs.pop("分辨率", None)

        cap_prompt = kwargs.get("提示词串", "")
        cap_artist = kwargs.get("画师串", "")
        cap_res = kwargs.get("分辨率串", "")

        if seed_str:
            # ── Batch mode ──────────────────────────────────────────
            seeds = [s.strip() for s in seed_str.split("\n") if s.strip()]
            aspect_ratio = str(kwargs.get("分辨率", "")).strip()
            desc_fmt = str(kwargs.get("描述格式", "")).strip()
            custom_prompt = str(kwargs.get("自定义提示词", "")).strip()
            refine_text = str(kwargs.get("待润色文本", "")).strip()

            # Determine system prompt: custom > image → system > no-image → batch
            has_image = kwargs.get("图像") is not None
            if custom_prompt:
                system_prompt = custom_prompt
            elif has_image:
                system_prompt = _build_system_prompt(desc_fmt)
            else:
                system_prompt = _build_batch_prompt(desc_fmt)
            should_unload = bool(kwargs.get("生成后卸载", False))
            kwargs["生成后卸载"] = False

            results: list[str] = []
            for i, s in enumerate(seeds):
                try:
                    seed_val = int(s)
                except ValueError:
                    continue
                seed_kwargs = dict(kwargs)
                seed_kwargs["随机种子"] = seed_val
                # Per-seed resolution from 分辨率串
                res_line = ""
                if i < len(cap_res.split("\n")):
                    res_line = cap_res.split("\n")[i].strip()
                user_parts: list[str] = []
                if refine_text:
                    user_parts.append(refine_text)
                if res_line:
                    user_parts.append(f"Resolution: {res_line}")
                elif aspect_ratio:
                    user_parts.append(f"Resolution: {aspect_ratio}")
                if not user_parts:
                    user_parts.append("Describe in detail.")
                if res_line:
                    seed_kwargs["分辨率"] = res_line
                nl = self._generate_one(seed_kwargs, "\n".join(user_parts), system_prompt)
                results.append(nl or "")

            if should_unload and results:
                try:
                    from .lm_studio import unload_all
                    unload_all()
                except Exception:
                    pass

            out_reverse = "\n".join(results)
            return (results[0] if results else "", cap_prompt, cap_artist, cap_res, out_reverse)

        # ── Single mode ──────────────────────────────────────────────
        seed_val = kwargs.get("随机种子", None)
        if seed_val is None or str(seed_val) == "":
            raw_seed = random.randint(0, 0xFFFF_FFFF_FFFF_FFFF)
        else:
            raw_seed = int(seed_val)
        kwargs["随机种子"] = raw_seed

        wd14_tags = str(kwargs.get("WD14标签", "")).strip()
        aspect_ratio = str(kwargs.get("分辨率", "")).strip()
        custom_prompt = str(kwargs.get("自定义提示词", "")).strip()
        desc_fmt = str(kwargs.get("描述格式", "")).strip()

        # Determine system prompt: custom > image → system > no-image → batch
        has_image = kwargs.get("图像") is not None
        if custom_prompt:
            system_prompt = custom_prompt
        elif has_image:
            system_prompt = _build_system_prompt(desc_fmt)
        else:
            system_prompt = _build_batch_prompt(desc_fmt)
        if aspect_ratio:
            system_prompt += f"\nTarget resolution: {aspect_ratio}"
        user_parts = []
        if wd14_tags:
            user_parts.append(f"Tags: {wd14_tags}")
        if aspect_ratio:
            user_parts.append(f"Resolution: {aspect_ratio}")
        user_parts.append(
            "Write a very long, extremely detailed description. "
            "Do NOT stop early. Continue until you have described every detail."
        )
        if not user_parts:
            user_parts.append("Describe the image in detail.")
        user_msg = "\n".join(user_parts)

        nl = ""
        model_was_loaded = False
        try:
            lm_model = str(kwargs.get("模型", ""))
            base_url = str(kwargs.get("API地址", "http://localhost:1234/v1"))
            api_key = str(kwargs.get("API密钥", "")).strip()
            cloud_model = str(kwargs.get("云端模型名", "deepseek-chat")).strip()
            image_b64 = _tensor_to_b64(kwargs.get("图像"))
            from .lm_studio import ensure_model_loaded, generate_nl_from_lm_studio, unload_all
            if api_key:
                model_for_api = cloud_model or lm_model
                if model_for_api and model_for_api != "(no models found)":
                    nl = generate_nl_from_lm_studio(
                        user_msg, base_url,
                        api_key=api_key, model_name=model_for_api,
                        detailed=True, timeout=180,
                        system_prompt=system_prompt,
                        max_tokens_override=int(kwargs.get("最大截断长度", 1024)),
                        image_b64=image_b64,
                    )
            else:
                if lm_model and lm_model != "(no models found)":
                    ctx = int(kwargs.get("上下文长度", 4096))
                    model_was_loaded = ensure_model_loaded(lm_model, context_length=ctx)
                    if model_was_loaded:
                        nl = generate_nl_from_lm_studio(
                            user_msg, base_url,
                            model_name=lm_model,
                            detailed=True, timeout=180,
                            system_prompt=system_prompt,
                            max_tokens_override=int(kwargs.get("最大截断长度", 1024)),
                            image_b64=image_b64,
                        )
        except Exception as e:
            import traceback
            print(f"ImageCaption error: {e}")
            traceback.print_exc()
            nl = f"[API Error: {e}]"

        if kwargs.get("生成后卸载", False) and model_was_loaded:
            try:
                from .lm_studio import unload_all
                unload_all()
            except Exception:
                pass

        return (nl or "", "", "", "", "")


NODE_CLASS_MAPPINGS = {"ImageCaption": ImageCaption}
NODE_DISPLAY_NAME_MAPPINGS = {"ImageCaption": "图片反推描述"}
