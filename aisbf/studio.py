from __future__ import annotations

from dataclasses import dataclass
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
        if not any(token in name for token in ["embedding", "embed", "whisper", "tts", "dall-e", "stable-diffusion"]):
            capabilities.append("chat")
        if any(token in name for token in ["vision", "gpt-4-turbo", "gpt-4o", "claude-3", "gemini-1.5", "gemini-2.0", "gemini-pro-vision", "llava", "blip"]):
            capabilities.append("vision")
        if any(token in name for token in ["dall-e", "dalle", "stable-diffusion", "sd-", "sdxl", "midjourney", "imagen", "flux"]):
            capabilities.append("image_generation")
        if any(token in name for token in ["stable-diffusion", "sd-", "sdxl", "controlnet", "img2img"]):
            capabilities.append("image_edit")
        if any(token in name for token in ["sora", "runway", "pika", "text-to-video", "t2v", "video"]):
            capabilities.append("video_generation")
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
