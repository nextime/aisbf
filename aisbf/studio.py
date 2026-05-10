from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any, Dict, Iterable, List, Optional


STUDIO_CAPABILITY_MAP = {
    "t2t": "chat",
    "vision": "vision",
    "i2t": "vision",
    "t2i": "image_generation",
    "i2i": "image_edit",
    "t2v": "video_generation",
    "i2v": "video_generation",
    "v2v": "video_generation",
    "v2t": "video_understanding",
    "a2t": "audio_input",
    "transcription": "transcription",
    "tts": "speech_generation",
    "t2a": "audio_generation",
    "a2a": "audio_generation",
    "embeddings": "embeddings",
    "function_calling": "tool_use",
    "reasoning": "reasoning",
    "code_generation": "code_generation",
    "code_completion": "code_completion",
    "translation": "translation",
    "summarization": "summarization",
    "classification": "classification",
    "sentiment_analysis": "sentiment_analysis",
    "ner": "ner",
    "question_answering": "question_answering",
    "search": "search",
    "moderation": "moderation",
    "fine_tuning": "fine_tuning",
    "multimodal": "multimodal",
    "ocr": "ocr",
    "image_captioning": "image_captioning",
    "object_detection": "object_detection",
    "segmentation": "segmentation",
    "3d_generation": "3d_generation",
    "animation": "animation",
}

DEFAULT_CHAT_PROVIDER_TYPES = {"openai", "anthropic", "google", "kilo", "claude", "qwen", "codex"}
NON_CHAT_MEDIA_TOKENS = {
    "dall-e",
    "dalle",
    "stable-diffusion",
    "sd-",
    "sdxl",
    "midjourney",
    "imagen",
    "flux",
    "sora",
    "runway",
    "pika",
    "text-to-video",
    "t2v",
    "video-llama",
    "video-chat",
}


@dataclass
class StudioCapabilityResult:
    capabilities: List[str]
    source: str
    unknown: bool
    notes: List[str]


@dataclass
class StudioCapabilityMergeResult:
    capabilities: List[str]
    partial_capabilities: List[str]


def _dedupe(values: Iterable[str]) -> List[str]:
    seen: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def normalize_capabilities(values: Optional[Iterable[str]]) -> List[str]:
    normalized: List[str] = []
    for value in values or []:
        normalized.append(STUDIO_CAPABILITY_MAP.get(value, value))
    return _dedupe(normalized)


def infer_model_capabilities(
    model_name: str,
    provider_type: str,
    explicit_capabilities: Optional[Iterable[str]] = None,
    architecture: Optional[Dict[str, Any]] = None,
    provider_metadata: Optional[Dict[str, Any]] = None,
) -> StudioCapabilityResult:
    explicit = normalize_capabilities(explicit_capabilities)
    if explicit:
        return StudioCapabilityResult(capabilities=explicit, source="explicit", unknown=False, notes=[])

    provider_metadata = provider_metadata or {}
    capabilities = normalize_capabilities(provider_metadata.get("capabilities"))
    source = "provider_metadata" if capabilities else "heuristic"
    notes: List[str] = []

    name = (model_name or "").lower()
    architecture = architecture or {}
    input_modalities = architecture.get("input_modalities") or []
    output_modalities = architecture.get("output_modalities") or []

    if not capabilities:
        if not any(token in name for token in ["embedding", "embed", "whisper", "tts", *NON_CHAT_MEDIA_TOKENS]):
            capabilities.append("chat")
        if any(token in name for token in ["vision", "gpt-4-turbo", "gpt-4o", "claude-3", "gemini-1.5", "gemini-2.0", "gemini-pro-vision", "llava", "blip"]):
            capabilities.append("vision")
        if any(token in name for token in ["dall-e", "dalle", "stable-diffusion", "sd-", "sdxl", "midjourney", "imagen", "flux"]):
            capabilities.append("image_generation")
        if any(token in name for token in ["stable-diffusion", "sd-", "sdxl", "controlnet", "img2img"]):
            capabilities.append("image_edit")
        if any(token in name for token in ["sora", "runway", "pika", "text-to-video", "t2v"]):
            capabilities.append("video_generation")
        if any(token in name for token in ["video-llama", "video-chat", "v2t"]):
            capabilities.append("video_understanding")
        if any(token in name for token in ["whisper", "transcribe", "speech-to-text", "stt"]):
            capabilities.extend(["audio_input", "transcription"])
        if any(token in name for token in ["tts", "text-to-speech", "elevenlabs", "bark", "tortoise", "speech"]):
            capabilities.append("speech_generation")
        if any(token in name for token in ["musicgen", "audiogen", "riffusion", "a2a"]):
            capabilities.append("audio_generation")
        if any(token in name for token in ["embedding", "embed", "ada-002", "bge", "e5", "instructor"]):
            capabilities.append("embeddings")
        if any(token in name for token in ["gpt-4", "gpt-3.5-turbo", "claude-3", "gemini", "function", "tool"]):
            capabilities.append("tool_use")
        if any(token in name for token in ["codex", "code-", "starcoder", "codellama", "deepseek-coder", "phind"]):
            capabilities.extend(["code_generation", "code_completion"])
        if any(token in name for token in ["reasoning", "cot", "o1", "o3"]):
            capabilities.append("reasoning")

    if "image" in input_modalities:
        capabilities.append("vision")
    if "audio" in input_modalities:
        capabilities.append("audio_input")
    if "text" in output_modalities and "audio" in input_modalities:
        capabilities.append("transcription")
    if "audio" in output_modalities:
        capabilities.append("speech_generation")

    capabilities = _dedupe(capabilities)
    unknown = not capabilities
    if unknown and provider_type in DEFAULT_CHAT_PROVIDER_TYPES:
        capabilities = ["chat"]
        source = "fallback"
        unknown = False
        notes.append(f"No confident Studio capabilities inferred for {provider_type}:{model_name}")
    elif unknown:
        notes.append(f"No confident Studio capabilities inferred for {provider_type}:{model_name}")

    return StudioCapabilityResult(
        capabilities=capabilities,
        source=source,
        unknown=unknown,
        notes=notes,
    )


def merge_capabilities(
    base_capabilities: Optional[Iterable[str]],
    override_capabilities: Optional[Iterable[str]],
    support_mode: str = "union",
) -> StudioCapabilityMergeResult:
    base = normalize_capabilities(base_capabilities)
    override = normalize_capabilities(override_capabilities)

    if support_mode == "intersection" and override:
        capabilities = [capability for capability in override if capability in base]
        partial_capabilities = [capability for capability in base if capability not in capabilities]
        return StudioCapabilityMergeResult(capabilities=capabilities, partial_capabilities=partial_capabilities)

    capabilities = _dedupe([*base, *override])
    return StudioCapabilityMergeResult(capabilities=capabilities, partial_capabilities=[])


def build_catalog_entry(
    scope: str,
    owner_id: Optional[int],
    kind: str,
    source_id: str,
    target_id: str,
    label: str,
    description: Optional[str],
    capabilities: Optional[Iterable[str]],
    availability_state: str,
    availability_reason: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "id": f"provider/{source_id}/{target_id}",
        "kind": kind,
        "owner_scope": scope,
        "owner_id": owner_id,
        "source_id": source_id,
        "target_id": target_id,
        "label": label,
        "description": description,
        "capabilities": normalize_capabilities(capabilities),
        "availability_state": availability_state,
        "availability_reason": availability_reason,
        "metadata": metadata or {},
    }


def _build_named_catalog_entry(
    *,
    kind: str,
    scope: str,
    owner_id: Optional[int],
    source_id: str,
    target_id: str,
    label: str,
    description: Optional[str],
    capabilities: Optional[Iterable[str]],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    entry = build_catalog_entry(
        scope=scope,
        owner_id=owner_id,
        kind=kind,
        source_id=source_id,
        target_id=target_id,
        label=label,
        description=description,
        capabilities=capabilities,
        availability_state="ready",
        availability_reason=None,
        metadata=metadata,
    )
    entry["id"] = f"{kind}/{target_id}"
    return entry


def _coerce_model_dict(model: Any) -> Dict[str, Any]:
    if isinstance(model, dict):
        return model

    data: Dict[str, Any] = {}
    for key in (
        "name",
        "id",
        "description",
        "capabilities",
        "context_length",
        "architecture",
        "pricing",
        "supported_parameters",
        "default_parameters",
    ):
        if hasattr(model, key):
            data[key] = getattr(model, key)
    return data


def _provider_models_from_config(provider_config: Any) -> List[Dict[str, Any]]:
    models = getattr(provider_config, "models", None)
    if models is None and isinstance(provider_config, dict):
        models = provider_config.get("models")
    return [_coerce_model_dict(model) for model in (models or [])]


def _load_global_providers_from_source() -> Dict[str, Dict[str, Any]]:
    config_path = Path.home() / ".aisbf" / "providers.json"
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / "config" / "providers.json"
        if not config_path.exists():
            return {}

    with open(config_path) as handle:
        payload = json.load(handle)

    providers = payload.get("providers") if isinstance(payload, dict) else None
    if isinstance(providers, dict):
        return providers
    if isinstance(payload, dict):
        return {key: value for key, value in payload.items() if key != "condensation"}
    return {}


def _build_provider_entries(scope: str, owner_id: Optional[int], providers: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for provider_id, provider_config in providers.items():
        provider_type = getattr(provider_config, "type", None)
        if provider_type is None and isinstance(provider_config, dict):
            provider_type = provider_config.get("type", "openai")
        provider_type = provider_type or "openai"

        for model in _provider_models_from_config(provider_config):
            target_id = model.get("name") or model.get("id")
            if not target_id:
                continue

            capability_result = infer_model_capabilities(
                model_name=target_id,
                provider_type=provider_type,
                explicit_capabilities=model.get("capabilities"),
                architecture=model.get("architecture"),
                provider_metadata=model,
            )
            metadata = {
                "provider_type": provider_type,
            }
            if model.get("context_length") is not None:
                metadata["context_length"] = model.get("context_length")
            if model.get("architecture") is not None:
                metadata["architecture"] = model.get("architecture")
            if capability_result.source:
                metadata["capability_source"] = capability_result.source
            if capability_result.notes:
                metadata["capability_notes"] = capability_result.notes

            entries.append(
                build_catalog_entry(
                    scope=scope,
                    owner_id=owner_id,
                    kind="provider_model",
                    source_id=provider_id,
                    target_id=target_id,
                    label=model.get("name") or target_id,
                    description=model.get("description"),
                    capabilities=capability_result.capabilities,
                    availability_state="ready",
                    availability_reason=None,
                    metadata=metadata,
                )
            )
    return entries


def _build_rotation_entries(scope: str, owner_id: Optional[int], rotations: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for rotation_id, rotation_config in rotations.items():
        config_data = rotation_config if isinstance(rotation_config, dict) else rotation_config.model_dump()
        entries.append(
            _build_named_catalog_entry(
                kind="rotation",
                scope=scope,
                owner_id=owner_id,
                source_id=rotation_id,
                target_id=rotation_id,
                label=config_data.get("model_name") or rotation_id,
                description=config_data.get("description"),
                capabilities=config_data.get("capabilities"),
                metadata={
                    "provider_count": len(config_data.get("providers") or []),
                    "context_length": config_data.get("context_length"),
                },
            )
        )
    return entries


def _build_autoselect_entries(scope: str, owner_id: Optional[int], autoselects: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for autoselect_id, autoselect_config in autoselects.items():
        config_data = autoselect_config if isinstance(autoselect_config, dict) else autoselect_config.model_dump()
        available_models = config_data.get("available_models") or []
        entries.append(
            _build_named_catalog_entry(
                kind="autoselect",
                scope=scope,
                owner_id=owner_id,
                source_id=autoselect_id,
                target_id=autoselect_id,
                label=config_data.get("model_name") or autoselect_id,
                description=config_data.get("description"),
                capabilities=config_data.get("capabilities"),
                metadata={
                    "available_model_count": len(available_models),
                    "fallback": config_data.get("fallback"),
                    "selection_model": config_data.get("selection_model"),
                },
            )
        )
    return entries


def build_studio_catalog(
    *,
    scope: str,
    owner_id: Optional[int],
    config: Any = None,
    db: Any = None,
) -> Dict[str, Any]:
    if scope == "user":
        provider_rows = db.get_user_providers(owner_id) if db and owner_id is not None else []
        rotation_rows = db.get_user_rotations(owner_id) if db and owner_id is not None else []
        autoselect_rows = db.get_user_autoselects(owner_id) if db and owner_id is not None else []
        providers = {row["provider_id"]: row.get("config", {}) for row in provider_rows}
        rotations = {row["rotation_id"]: row.get("config", {}) for row in rotation_rows}
        autoselects = {row["autoselect_id"]: row.get("config", {}) for row in autoselect_rows}
    else:
        providers = getattr(config, "providers", None) or _load_global_providers_from_source()
        rotations = getattr(config, "rotations", None) or {}
        autoselects = getattr(config, "autoselect", None) or {}

    entries = [
        *_build_provider_entries(scope, owner_id, providers),
        *_build_rotation_entries(scope, owner_id, rotations),
        *_build_autoselect_entries(scope, owner_id, autoselects),
    ]

    entries.sort(key=lambda entry: (entry["kind"], entry["label"], entry["id"]))
    return {
        "scope": scope,
        "owner_id": owner_id,
        "entries": entries,
    }
