"""
Studio workflow adapter helpers.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _join_non_empty(parts: list[str], fallback: str) -> str:
    cleaned = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
    return ". ".join(cleaned) if cleaned else fallback


def _provider_signature(provider_id: str, endpoint: str) -> str:
    provider_id = (provider_id or "").strip().lower()
    endpoint = (endpoint or "").strip().lower()
    return f"{provider_id} {endpoint}".strip()


def _is_openrouter_like(signature: str) -> bool:
    return any(token in signature for token in ["openrouter", "api.kilo.ai", "kilo"])


def _is_github_models_like(signature: str) -> bool:
    return any(token in signature for token in ["github", "models.inference.ai.azure.com", "githubusercontent"])


def _is_azure_openai_like(signature: str) -> bool:
    return any(token in signature for token in [".openai.azure.com", "azure openai", "azure-"])


def _is_qwen_like(signature: str, provider_type: str) -> bool:
    return provider_type == "qwen" or any(token in signature for token in ["dashscope", "qwen", "aliyuncs.com"])


def _is_claude_oauth_like(signature: str, provider_type: str) -> bool:
    return provider_type == "claude" or any(token in signature for token in ["claude.ai", "anthropic", "claude"])


def _is_codex_like(signature: str, provider_type: str) -> bool:
    return provider_type == "codex" or any(token in signature for token in ["chatgpt.com/backend-api", "auth.openai.com", "codex"])


def _is_kiro_like(signature: str, provider_type: str) -> bool:
    return provider_type == "kiro" or any(token in signature for token in ["kiro", "amazon q", "amazonaws.com"])


def _is_coderai_like(signature: str, provider_type: str) -> bool:
    return provider_type == "coderai" or "coderai" in signature


def _media_hint(body: Dict[str, Any], *keys: str) -> str:
    bits: list[str] = []
    for key in keys:
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            bits.append(value.strip())
    return _join_non_empty(bits, "") if bits else ""


def _response_url_hint(signature: str) -> bool:
    return _is_openrouter_like(signature) or _is_azure_openai_like(signature)


STUDIO_ADAPTER_CHOICES = [
    "auto",
    "openai_chat_media",
    "openai_native_media",
    "anthropic_multimodal",
    "google_gemini_media",
    "ollama_openai_compat",
    "passthrough",
]

STUDIO_ADAPTER_PROFILE_CHOICES = [
    "auto",
    "openai_default",
    "openai_responses_style",
    "openrouter_media",
    "kilo_openrouter",
    "github_models",
    "azure_openai_media",
    "anthropic_default",
    "claude_oauth",
    "gemini_default",
    "qwen_dashscope",
    "ollama_default",
    "passthrough",
]


def serialize_studio_adapter_choices() -> list[str]:
    return list(STUDIO_ADAPTER_CHOICES)


def serialize_studio_adapter_profile_choices() -> list[str]:
    return list(STUDIO_ADAPTER_PROFILE_CHOICES)


def infer_studio_adapter(provider_type: str, model: Optional[Dict[str, Any]] = None) -> str:
    provider_type = (provider_type or "openai").strip().lower()
    model = model or {}
    explicit = (model.get("studio_adapter") or "").strip()
    if explicit and explicit != "auto":
        return explicit

    caps = set(model.get("studio_capabilities") or model.get("capabilities") or [])
    if provider_type == "anthropic":
        return "anthropic_multimodal"
    if provider_type == "google":
        return "google_gemini_media"
    if provider_type == "ollama":
        return "ollama_openai_compat"
    if provider_type in {"openai", "qwen", "codex", "kilocode", "kilo", "claude", "kiro", "coderai"}:
        media_caps = {
            "image_generation", "image_edit", "video_generation", "audio_generation",
            "audio_to_audio", "speech_generation", "transcription", "3d_generation",
        }
        return "openai_native_media" if caps & media_caps else "openai_chat_media"
    return "passthrough"


def effective_studio_adapter(provider_type: str, model_metadata: Optional[Dict[str, Any]] = None) -> str:
    model_metadata = model_metadata or {}
    override = (model_metadata.get("studio_adapter_override") or model_metadata.get("studio_adapter") or "").strip()
    if override and override != "auto":
        return override
    return infer_studio_adapter(provider_type, model_metadata)


def infer_studio_adapter_profile(provider_id: str, provider_type: str, model_metadata: Optional[Dict[str, Any]] = None) -> str:
    model_metadata = model_metadata or {}
    override = (model_metadata.get("studio_adapter_profile_override") or model_metadata.get("studio_adapter_profile") or "").strip()
    if override and override != "auto":
        return override

    provider_id = (provider_id or "").strip().lower()
    provider_type = (provider_type or "").strip().lower()
    endpoint = str(model_metadata.get("provider_endpoint") or model_metadata.get("endpoint") or "").lower()
    signature = _provider_signature(provider_id, endpoint)

    if provider_type == "google":
        return "gemini_default"
    if provider_type == "anthropic":
        return "anthropic_default"
    if provider_type == "claude" or _is_claude_oauth_like(signature, provider_type):
        return "claude_oauth"
    if provider_type == "ollama":
        return "ollama_default"
    if _is_qwen_like(signature, provider_type):
        return "qwen_dashscope"
    if provider_id == "kilo" or _is_openrouter_like(signature):
        return "kilo_openrouter"
    if _is_github_models_like(signature):
        return "github_models"
    if _is_azure_openai_like(signature):
        return "azure_openai_media"
    if _is_codex_like(signature, provider_type):
        return "openai_responses_style"
    if _is_kiro_like(signature, provider_type):
        return "openai_default"
    if _is_coderai_like(signature, provider_type):
        return "openai_default"
    if "openrouter" in signature:
        return "openrouter_media"
    if provider_type in {"openai", "codex", "qwen", "kilocode", "kilo", "claude", "coderai"}:
        return "openai_responses_style" if any(token in provider_id for token in ["responses", "azure", "github"]) else "openai_default"
    return "passthrough"


def adapt_studio_payload(adapter: str, endpoint_path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    body = dict(payload or {})

    if adapter in {"openai_chat_media", "ollama_openai_compat"}:
        if endpoint_path == "v1/video/dub":
            prompt_bits = ["Dub this video"]
            if body.get("source_lang"):
                prompt_bits.append(f"from {body['source_lang']}")
            if body.get("target_lang"):
                prompt_bits.append(f"to {body['target_lang']}")
            if body.get("burn_subtitles"):
                prompt_bits.append("and burn subtitles")
            body.setdefault("input", " ".join(prompt_bits))
        elif endpoint_path == "v1/audio/clone":
            if "text" in body and "input" not in body:
                body["input"] = body.pop("text")
            if "ref_text" in body and "transcript" not in body:
                body["transcript"] = body["ref_text"]
        elif endpoint_path == "v1/audio/convert":
            if "target_voice" in body and "voice_reference" not in body:
                body["voice_reference"] = body["target_voice"]
        elif endpoint_path == "v1/images/faceswap":
            if "target" in body and body.get("target_type") == "video" and "video" not in body:
                body["video"] = body.pop("target")
            elif "target" in body and "image" not in body:
                body["image"] = body.pop("target")
            if "source_face" in body and "reference_image" not in body:
                body["reference_image"] = body["source_face"]
    elif adapter == "anthropic_multimodal":
        if endpoint_path == "v1/audio/clone":
            text = body.get("text") or body.get("input") or ""
            transcript = body.get("ref_text") or body.get("transcript") or ""
            body["input"] = f"Clone the reference voice and say: {text}\nReference transcript: {transcript}".strip()
        elif endpoint_path == "v1/audio/convert":
            body["input"] = "Convert the source audio into the target voice while preserving timing and prosody."
        elif endpoint_path == "v1/video/dub":
            source_lang = body.get("source_lang") or "source language"
            target_lang = body.get("target_lang") or "target language"
            body["input"] = f"Dub this video from {source_lang} to {target_lang}."
    elif adapter == "google_gemini_media":
        if endpoint_path in {"v1/audio/clone", "v1/audio/convert", "v1/video/dub"} and "input" not in body:
            body["input"] = body.get("text") or body.get("prompt") or body.get("notes") or "Process the provided media."
    return body


def adapt_studio_payload_with_profile(adapter: str, profile: str, endpoint_path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    body = adapt_studio_payload(adapter, endpoint_path, payload)
    signature = _provider_signature(
        str(body.get("_studio_provider_id") or body.get("provider_id") or ""),
        str(body.get("_studio_provider_endpoint") or body.get("provider_endpoint") or body.get("endpoint") or ""),
    )

    if _response_url_hint(signature):
        body.setdefault("response_format", "url")

    if profile == "openai_responses_style":
        if endpoint_path == "v1/audio/clone":
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("text"),
                f"Use voice profile {body.get('voice_name')}" if body.get("voice_name") else "",
                f"Reference transcript: {body.get('transcript') or body.get('ref_text')}" if (body.get("transcript") or body.get("ref_text")) else "",
            ], "Process the provided media.")
            if _is_openrouter_like(signature):
                body["modalities"] = ["text", "audio"]
        elif endpoint_path == "v1/audio/convert":
            body["input"] = _join_non_empty([
                body.get("input"),
                "Convert the provided source audio into the target voice.",
                f"Voice profile: {body.get('voice_name')}" if body.get("voice_name") else "",
                f"Pitch shift: {body.get('pitch_shift')}" if body.get("pitch_shift") not in (None, "") else "",
            ], "Process the provided media.")
            if _is_openrouter_like(signature):
                body["modalities"] = ["text", "audio"]
        elif endpoint_path == "v1/video/dub":
            body["input"] = _join_non_empty([
                body.get("input"),
                f"Dub the provided video from {body.get('source_lang') or 'source language'} to {body.get('target_lang') or 'target language'}.",
                "Burn subtitles into the output." if body.get("burn_subtitles") else "",
            ], "Process the provided media.")
        elif endpoint_path in {"v1/images/faceswap", "v1/images/outfit", "v1/images/to3d", "v1/images/from3d"}:
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                "Process the provided image transformation.",
            ], "Process the provided media.")
    elif profile == "openrouter_media":
        if endpoint_path == "v1/video/dub":
            body.setdefault("response_format", "url")
            body["prompt"] = _join_non_empty([
                body.get("prompt"),
                body.get("input"),
                f"Dub the provided video from {body.get('source_lang') or 'source language'} to {body.get('target_lang') or 'target language'}.",
            ], "Dub the provided video")
        elif endpoint_path in {"v1/audio/clone", "v1/audio/convert"}:
            body["prompt"] = _join_non_empty([
                body.get("prompt"),
                body.get("input"),
                body.get("text"),
                f"Use voice profile {body.get('voice_name')}" if body.get("voice_name") else "",
            ], "Process the provided audio")
            body.setdefault("modalities", ["text", "audio"])
        elif endpoint_path in {"v1/images/faceswap", "v1/images/outfit"}:
            body.setdefault("response_format", "url")
            body["prompt"] = _join_non_empty([
                body.get("prompt"),
                "Perform the requested image or video transformation.",
                body.get("input"),
            ], "Process the provided media")
        elif endpoint_path in {"v1/images/to3d", "v1/images/from3d", "v1/video/to3d", "v1/video/from3d", "v1/3d/generate"}:
            body.setdefault("response_format", "url")
            body["prompt"] = _join_non_empty([
                body.get("prompt"),
                body.get("input"),
                body.get("notes"),
                "Generate or transform 3D media from the provided source.",
            ], "Process the provided 3D media")
    elif profile == "kilo_openrouter":
        body.setdefault("response_format", "url")
        if endpoint_path == "v1/video/dub":
            body["prompt"] = _join_non_empty([
                body.get("prompt"),
                body.get("input"),
                f"Dub this media from {body.get('source_lang') or 'source language'} to {body.get('target_lang') or 'target language'}.",
                "Prefer provider-side multimodel orchestration when supported.",
            ], "Dub the provided media")
        elif endpoint_path in {"v1/audio/clone", "v1/audio/convert"}:
            body["prompt"] = _join_non_empty([
                body.get("prompt"),
                body.get("input"),
                body.get("text"),
                f"Reference transcript: {body.get('transcript') or body.get('ref_text')}" if (body.get("transcript") or body.get("ref_text")) else "",
                "Prefer provider-side voice workflow support.",
            ], "Process the provided audio")
            body.setdefault("modalities", ["text", "audio"])
        elif endpoint_path in {"v1/images/faceswap", "v1/images/outfit", "v1/images/to3d", "v1/images/from3d", "v1/video/to3d", "v1/video/from3d", "v1/3d/generate"}:
            body["prompt"] = _join_non_empty([
                body.get("prompt"),
                body.get("input"),
                body.get("notes"),
                "Prefer provider-side multimodel orchestration when supported.",
            ], "Process the provided media")
    elif profile == "github_models":
        if endpoint_path in {"v1/audio/clone", "v1/audio/convert", "v1/video/dub"}:
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                body.get("text"),
                body.get("notes"),
            ], "Process the provided media.")
            body.pop("prompt", None)
        elif endpoint_path in {"v1/images/faceswap", "v1/images/outfit", "v1/images/to3d", "v1/images/from3d", "v1/video/to3d", "v1/video/from3d", "v1/3d/generate"}:
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                body.get("notes"),
                _media_hint(body, "source_lang", "target_lang"),
            ], "Process the provided media.")
            body.pop("prompt", None)
    elif profile == "azure_openai_media":
        if endpoint_path in {"v1/audio/clone", "v1/audio/convert", "v1/video/dub"}:
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                body.get("text"),
                f"Target language: {body.get('target_lang')}" if body.get("target_lang") else "",
            ], "Process the provided media.")
            body.setdefault("response_format", "url")
        elif endpoint_path in {"v1/images/faceswap", "v1/images/outfit", "v1/images/to3d", "v1/images/from3d", "v1/video/to3d", "v1/video/from3d", "v1/3d/generate"}:
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                body.get("notes"),
                "Return a provider-hosted media result when supported.",
            ], "Process the provided media.")
            body.setdefault("response_format", "url")
    elif profile == "anthropic_default":
        if endpoint_path.startswith("v1/images/") and "input" not in body:
            body["input"] = body.get("prompt") or "Process the provided image task."
    elif profile == "claude_oauth":
        if endpoint_path in {"v1/audio/clone", "v1/audio/convert", "v1/video/dub"}:
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                body.get("text"),
                body.get("notes"),
                "Return structured textual guidance if native media transformation is unavailable.",
            ], "Process the provided media.")
            body.pop("prompt", None)
        elif endpoint_path.startswith("v1/images/") or endpoint_path.startswith("v1/video/") or endpoint_path.startswith("v1/3d/"):
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                body.get("notes"),
                "Use uploaded media context when supported and otherwise respond with the closest textual workflow guidance.",
            ], "Process the provided media task.")
            body.pop("prompt", None)
    elif profile == "gemini_default":
        if endpoint_path.startswith("v1/video/"):
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                body.get("notes"),
                f"Source language: {body.get('source_lang')}" if body.get("source_lang") else "",
                f"Target language: {body.get('target_lang')}" if body.get("target_lang") else "",
            ], "Process the provided video.")
        elif endpoint_path in {"v1/audio/clone", "v1/audio/convert"}:
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("text"),
                body.get("notes"),
                f"Transcript: {body.get('transcript') or body.get('ref_text')}" if (body.get("transcript") or body.get("ref_text")) else "",
            ], "Process the provided audio.")
        elif endpoint_path.startswith("v1/images/") or endpoint_path.startswith("v1/3d/"):
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                body.get("notes"),
                "Use the provided image or media context for this transformation.",
            ], "Process the provided image task.")
    elif profile == "qwen_dashscope":
        if endpoint_path in {"v1/audio/clone", "v1/audio/convert", "v1/video/dub"}:
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                body.get("text"),
                body.get("notes"),
                "Use DashScope-compatible multimodal processing when available.",
            ], "Process the provided media.")
            body.pop("prompt", None)
        elif endpoint_path.startswith("v1/images/") or endpoint_path.startswith("v1/video/") or endpoint_path.startswith("v1/3d/"):
            body["input"] = _join_non_empty([
                body.get("input"),
                body.get("prompt"),
                body.get("notes"),
                "Adapt this request to Qwen/DashScope-compatible media instructions.",
            ], "Process the provided media task.")
            body.pop("prompt", None)
    elif profile == "ollama_default":
        if endpoint_path in {"v1/audio/clone", "v1/audio/convert", "v1/video/dub"} and "prompt" not in body:
            body["prompt"] = body.get("input") or body.get("text") or body.get("notes") or "Process the provided media."
        elif endpoint_path.startswith("v1/images/") or endpoint_path.startswith("v1/video/") or endpoint_path.startswith("v1/3d/"):
            body["prompt"] = _join_non_empty([
                body.get("prompt"),
                body.get("input"),
                body.get("notes"),
                "If native media execution is unavailable, describe the expected transformation result.",
            ], "Process the provided media.")

    return body
