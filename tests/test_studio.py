import pytest

from aisbf.studio import (
    StudioCapabilityResult,
    build_catalog_entry,
    infer_model_capabilities,
    merge_capabilities,
)


def test_infer_model_capabilities_prefers_explicit_capabilities():
    result = infer_model_capabilities(
        model_name="gpt-4o",
        provider_type="openai",
        explicit_capabilities=["chat", "vision"],
        architecture={"input_modalities": ["text", "image"], "output_modalities": ["text"]},
    )

    assert isinstance(result, StudioCapabilityResult)
    assert result.capabilities == ["chat", "vision"]
    assert result.source == "explicit"
    assert result.unknown is False


def test_infer_model_capabilities_uses_name_and_architecture_heuristics_when_explicit_missing():
    result = infer_model_capabilities(
        model_name="whisper-large-v3",
        provider_type="openai",
        explicit_capabilities=None,
        architecture={"input_modalities": ["audio"], "output_modalities": ["text"]},
    )

    assert "audio_input" in result.capabilities
    assert "transcription" in result.capabilities
    assert result.source in {"provider_metadata", "heuristic"}


def test_merge_capabilities_keeps_explicit_values_and_reports_partial_support():
    merged = merge_capabilities(
        base_capabilities=["chat", "vision", "image_generation"],
        override_capabilities=["chat", "vision"],
        support_mode="intersection",
    )

    assert merged.capabilities == ["chat", "vision"]
    assert merged.partial_capabilities == ["image_generation"]


def test_build_catalog_entry_normalizes_provider_model_payload():
    entry = build_catalog_entry(
        scope="user",
        owner_id=5,
        kind="provider_model",
        source_id="openai",
        target_id="gpt-4o",
        label="GPT-4o",
        description="General multimodal model",
        capabilities=["chat", "vision"],
        availability_state="ready",
        availability_reason=None,
        metadata={"context_length": 128000},
    )

    assert entry["id"] == "provider/openai/gpt-4o"
    assert entry["kind"] == "provider_model"
    assert entry["owner_scope"] == "user"
    assert entry["owner_id"] == 5
    assert entry["capabilities"] == ["chat", "vision"]
    assert entry["metadata"]["context_length"] == 128000


def test_infer_model_capabilities_restores_code_model_families():
    result = infer_model_capabilities(
        model_name="deepseek-coder-33b-instruct",
        provider_type="openai",
    )

    assert "code_generation" in result.capabilities
    assert "code_completion" in result.capabilities


def test_infer_model_capabilities_does_not_treat_video_understanding_models_as_generation():
    result = infer_model_capabilities(
        model_name="video-llama-2",
        provider_type="openai",
    )

    assert "video_understanding" in result.capabilities
    assert "video_generation" not in result.capabilities


@pytest.mark.parametrize("model_name", ["dalle-3", "runway-gen3"])
def test_infer_model_capabilities_does_not_fallback_to_chat_for_media_models(model_name):
    result = infer_model_capabilities(
        model_name=model_name,
        provider_type="openai",
    )

    assert "chat" not in result.capabilities
