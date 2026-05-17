"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any, Dict, Iterable, List, Optional

from aisbf.app.model_cache import get_provider_models
from aisbf.studio_adapters import effective_studio_adapter, infer_studio_adapter_profile


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
    # CoderAI / HuggingFace pipeline task names (long-form field names from ModelCapabilities)
    "text_generation": "chat",
    "text-generation": "chat",
    "chat_completion": "chat",
    "image_to_text": "vision",
    "image_generation": "image_generation",
    "text_to_image": "image_generation",
    "image_to_image": "image_edit",
    "inpainting": "image_edit",
    "controlnet": "image_generation",
    "video_generation": "video_generation",
    "text_to_video": "video_generation",
    "image_to_video": "video_generation",
    "video_to_video": "video_generation",
    "video_interpolation": "animation",
    "video_upscaling": "video_generation",
    "image_upscaling": "image_edit",
    "face_restoration": "image_edit",
    "depth_estimation": "object_detection",
    "image_segmentation": "segmentation",
    "image_classification": "classification",
    "object_detection": "object_detection",
    "style_transfer": "image_edit",
    "automatic_speech_recognition": "transcription",
    "speech_recognition": "transcription",
    "speech_to_text": "transcription",
    "subtitle_generation": "transcription",
    "text_to_speech": "speech_generation",
    "audio_generation": "audio_generation",
    "lip_sync": "video_generation",
    "video_dubbing": "video_generation",
    "image_to_3d": "3d_generation",
    "video_to_3d": "3d_generation",
    "model_3d_generation": "3d_generation",
    "model_3d_to_image": "3d_generation",
    "feature_extraction": "embeddings",
    "sentence_similarity": "embeddings",
    "fill_mask": "chat",
    "token_classification": "ner",
}

STUDIO_CAPABILITY_CHOICES = [
    "chat",
    "vision",
    "image_generation",
    "image_edit",
    "video_generation",
    "video_understanding",
    "audio_input",
    "transcription",
    "speech_generation",
    "audio_generation",
    "audio_to_audio",
    "embeddings",
    "tool_use",
    "reasoning",
    "code_generation",
    "code_completion",
    "translation",
    "summarization",
    "classification",
    "sentiment_analysis",
    "ner",
    "question_answering",
    "search",
    "moderation",
    "fine_tuning",
    "multimodal",
    "ocr",
    "image_captioning",
    "object_detection",
    "segmentation",
    "3d_generation",
    "animation",
]

DEFAULT_CHAT_PROVIDER_TYPES = {"openai", "anthropic", "google", "kilo", "claude", "qwen", "codex", "coderai"}
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


def serialize_studio_capability_choices() -> List[str]:
    return list(STUDIO_CAPABILITY_CHOICES)


def stamp_inferred_capabilities(model: Dict[str, Any], provider_type: str) -> Dict[str, Any]:
    stamped = dict(model)
    capability_result = infer_model_capabilities(
        model_name=stamped.get("name") or stamped.get("id") or "",
        provider_type=provider_type,
        explicit_capabilities=stamped.get("studio_capabilities") or stamped.get("capabilities"),
        architecture=stamped.get("architecture"),
        provider_metadata=stamped,
    )

    stamped["studio_capabilities"] = capability_result.capabilities
    stamped["studio_capability_source"] = capability_result.source
    stamped["studio_capability_unknown"] = capability_result.unknown
    if capability_result.notes:
        stamped["studio_capability_notes"] = capability_result.notes
    elif "studio_capability_notes" in stamped:
        stamped.pop("studio_capability_notes", None)
    return stamped


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
    if not capabilities and provider_metadata.get("type"):
        _type_cap_map = {
            "text": ["chat"],
            "image": ["image_generation"],
            "video": ["video_generation"],
            "audio": ["audio_generation"],
            "embedding": ["embeddings"],
            "multimodal": ["multimodal", "chat"],
        }
        capabilities = _type_cap_map.get((provider_metadata["type"] or "").lower(), [])
    source = "provider_metadata" if capabilities else "heuristic"
    notes: List[str] = []

    name = (model_name or "").lower()
    architecture = architecture or {}
    input_modalities = architecture.get("input_modalities") or []
    output_modalities = architecture.get("output_modalities") or []

    if not capabilities:
        metadata_text = json.dumps(provider_metadata, sort_keys=True).lower() if provider_metadata else ""
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
        if any(token in name for token in ["voice", "audio-to-audio", "voice conversion", "rvc", "a2a"]):
            capabilities.append("audio_to_audio")
        if any(token in name for token in ["embedding", "embed", "ada-002", "bge", "e5", "instructor"]):
            capabilities.append("embeddings")
        if any(token in name for token in ["gpt-4", "gpt-3.5-turbo", "claude-3", "gemini", "function", "tool"]):
            capabilities.append("tool_use")
        if any(token in name for token in ["codex", "code-", "starcoder", "codellama", "deepseek-coder", "phind"]):
            capabilities.extend(["code_generation", "code_completion"])
        if any(token in name for token in ["reasoning", "cot", "o1", "o3"]):
            capabilities.append("reasoning")
        if any(token in name for token in ["ocr"]):
            capabilities.extend(["ocr", "image_captioning"])
        if any(token in name for token in ["detect", "detection", "yolo"]):
            capabilities.append("object_detection")
        if any(token in name for token in ["segment", "segmentation", "sam"]):
            capabilities.append("segmentation")
        if any(token in name for token in ["3d", "mesh", "gaussian splat", "nerf"]):
            capabilities.append("3d_generation")
        if any(token in name for token in ["animate", "animation"]):
            capabilities.append("animation")

        if metadata_text:
            if 'image' in metadata_text and 'input_modalit' in metadata_text:
                capabilities.append("vision")
            if 'audio' in metadata_text and 'input_modalit' in metadata_text:
                capabilities.append("audio_input")
            if 'transcrib' in metadata_text or 'speech_to_text' in metadata_text:
                capabilities.extend(["audio_input", "transcription"])
            if 'text_to_speech' in metadata_text or 'speech_generation' in metadata_text:
                capabilities.append("speech_generation")
            if 'audio_generation' in metadata_text or 'text-to-audio' in metadata_text:
                capabilities.append("audio_generation")
            if 'audio_to_audio' in metadata_text or 'voice conversion' in metadata_text:
                capabilities.append("audio_to_audio")
            if 'embedding' in metadata_text:
                capabilities.append("embeddings")
            if 'tool' in metadata_text or 'function_call' in metadata_text:
                capabilities.append("tool_use")
            if 'moderat' in metadata_text:
                capabilities.append("moderation")

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


def derive_aggregate_capabilities(capability_sets: Iterable[Optional[Iterable[str]]]) -> StudioCapabilityMergeResult:
    capability_sets = list(capability_sets)
    normalized_sets = [normalize_capabilities(capabilities) for capabilities in capability_sets if capabilities]
    if not normalized_sets:
        return StudioCapabilityMergeResult(capabilities=[], partial_capabilities=[])

    has_unknown_member = any(not normalize_capabilities(capabilities) for capabilities in capability_sets)

    aggregate = list(normalized_sets[0])
    partial: List[str] = []
    for capability_set in normalized_sets[1:]:
        merged = merge_capabilities(aggregate, capability_set, support_mode="intersection")
        aggregate = merged.capabilities
        partial = _dedupe([*partial, *merged.partial_capabilities, *[capability for capability in capability_set if capability not in aggregate]])

    if has_unknown_member:
        partial = _dedupe([*partial, *aggregate])
        aggregate = []

    partial = [capability for capability in partial if capability not in aggregate]
    return StudioCapabilityMergeResult(capabilities=aggregate, partial_capabilities=partial)


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
    metadata = metadata or {}
    explicit_capabilities = metadata.get("studio_capabilities") or capabilities
    aggregate_capabilities = metadata.get("aggregate_capabilities")
    effective_capabilities = aggregate_capabilities if not explicit_capabilities else explicit_capabilities
    partial_capabilities = []
    if explicit_capabilities:
        partial_capabilities = []
    elif aggregate_capabilities:
        partial_capabilities = normalize_capabilities(metadata.get("aggregate_partial_capabilities"))
    return {
        "id": f"provider/{source_id}/{target_id}",
        "kind": kind,
        "owner_scope": scope,
        "owner_id": owner_id,
        "source_id": source_id,
        "target_id": target_id,
        "label": label,
        "description": description,
        "capabilities": normalize_capabilities(effective_capabilities),
        "partial_capabilities": partial_capabilities,
        "availability_state": availability_state,
        "availability_reason": availability_reason,
        "metadata": metadata,
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

            persisted_studio_capabilities = model.get("studio_capabilities")
            persisted_source = model.get("studio_capability_source")
            persisted_unknown = model.get("studio_capability_unknown")
            persisted_notes = model.get("studio_capability_notes")

            if persisted_studio_capabilities is not None:
                capability_result = StudioCapabilityResult(
                    capabilities=normalize_capabilities(persisted_studio_capabilities),
                    source=persisted_source or "persisted",
                    unknown=bool(persisted_unknown),
                    notes=list(persisted_notes or []),
                )
            else:
                capability_result = infer_model_capabilities(
                    model_name=target_id,
                    provider_type=provider_type,
                    explicit_capabilities=None,
                    architecture=model.get("architecture"),
                    provider_metadata=model,
                )
            metadata = {
                "provider_type": provider_type,
                "provider_endpoint": model.get("endpoint") or provider_config.get("endpoint") if isinstance(provider_config, dict) else getattr(provider_config, "endpoint", None),
            }
            if model.get("context_length") is not None:
                metadata["context_length"] = model.get("context_length")
            if model.get("architecture") is not None:
                metadata["architecture"] = model.get("architecture")
            if model.get("studio_capabilities") is not None:
                metadata["studio_capabilities"] = normalize_capabilities(model.get("studio_capabilities"))
            if model.get("studio_capability_source") is not None:
                metadata["studio_capability_source"] = model.get("studio_capability_source")
            if model.get("studio_capability_unknown") is not None:
                metadata["studio_capability_unknown"] = model.get("studio_capability_unknown")
            if model.get("studio_capability_notes"):
                metadata["studio_capability_notes"] = model.get("studio_capability_notes")
            if capability_result.source:
                metadata["capability_source"] = capability_result.source
            if capability_result.notes:
                metadata["capability_notes"] = capability_result.notes
            metadata["studio_adapter"] = effective_studio_adapter(provider_type, model)
            metadata["studio_adapter_profile"] = infer_studio_adapter_profile(provider_id, provider_type, {**model, **metadata})
            if model.get("studio_adapter_override") is not None:
                metadata["studio_adapter_override"] = model.get("studio_adapter_override")
            if model.get("studio_adapter_profile_override") is not None:
                metadata["studio_adapter_profile_override"] = model.get("studio_adapter_profile_override")

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
        aggregate_capabilities = derive_aggregate_capabilities(
            provider.get("capabilities") for provider in (config_data.get("providers") or [])
        )
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
                    "aggregate_capabilities": aggregate_capabilities.capabilities,
                    "aggregate_partial_capabilities": aggregate_capabilities.partial_capabilities,
                    "aggregate_capability_source": "derived",
                },
            )
        )
    return entries


def _build_autoselect_entries(scope: str, owner_id: Optional[int], autoselects: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    for autoselect_id, autoselect_config in autoselects.items():
        config_data = autoselect_config if isinstance(autoselect_config, dict) else autoselect_config.model_dump()
        available_models = config_data.get("available_models") or []
        aggregate_capabilities = derive_aggregate_capabilities(
            model.get("capabilities") if isinstance(model, dict) else None for model in available_models
        )
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
                    "aggregate_capabilities": aggregate_capabilities.capabilities,
                    "aggregate_partial_capabilities": aggregate_capabilities.partial_capabilities,
                    "aggregate_capability_source": "derived",
                },
            )
        )
    return entries


async def build_studio_catalog(
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

    provider_entries = _build_provider_entries(scope, owner_id, providers)

    missing_provider_ids = {
        provider_id
        for provider_id, provider_config in (providers or {}).items()
        if not _provider_models_from_config(provider_config)
    }
    if missing_provider_ids and config is not None:
        for provider_id in missing_provider_ids:
            provider_config = providers.get(provider_id)
            if provider_config is None:
                continue
            try:
                live_models = await get_provider_models(provider_id, provider_config, config, user_id=owner_id if scope == "user" else None)
            except Exception:
                live_models = []
            if not live_models:
                continue
            live_model_names = {
                (model.get("name") or model.get("model_name") or model.get("id") or "").split("/", 1)[-1]
                for model in live_models if isinstance(model, dict)
            }
            provider_entries = [
                entry for entry in provider_entries
                if not (entry.get("kind") == "provider_model" and entry.get("source_id") == provider_id and entry.get("target_id") in live_model_names)
            ]
            hydrated_provider = provider_config if isinstance(provider_config, dict) else provider_config.model_dump()
            hydrated_provider = dict(hydrated_provider)
            hydrated_provider["models"] = live_models
            provider_entries.extend(_build_provider_entries(scope, owner_id, {provider_id: hydrated_provider}))

    entries = [
        *provider_entries,
        *_build_rotation_entries(scope, owner_id, rotations),
        *_build_autoselect_entries(scope, owner_id, autoselects),
    ]

    entries.sort(key=lambda entry: (entry["kind"], entry["label"], entry["id"]))
    return {
        "scope": scope,
        "owner_id": owner_id,
        "entries": entries,
    }
