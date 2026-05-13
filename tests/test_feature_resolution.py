from types import SimpleNamespace

from aisbf.config import Config


def test_resolve_feature_enabled_prefers_model_provider_and_global_defaults():
    config = Config.__new__(Config)
    config.aisbf = SimpleNamespace(
        feature_controls=SimpleNamespace(
            response_cache=SimpleNamespace(mode="enabled"),
            context_condensation=SimpleNamespace(mode="disabled"),
            prompt_batching=SimpleNamespace(mode="disabled"),
        ),
        response_cache=SimpleNamespace(enabled=False),
        batching=SimpleNamespace(enabled=False),
    )
    config.condensation = SimpleNamespace(enabled=False)

    provider_config = SimpleNamespace(enable_response_cache=False)
    model_config = {"enable_response_cache": True}

    assert config.resolve_feature_enabled(
        "response_cache",
        model_config=model_config,
        provider_config=provider_config,
    ) is True


def test_resolve_feature_enabled_uses_global_feature_controls_for_condensation_and_batching():
    config = Config.__new__(Config)
    config.aisbf = SimpleNamespace(
        feature_controls=SimpleNamespace(
            nsfw_classification=SimpleNamespace(mode="disabled"),
            privacy_classification=SimpleNamespace(mode="disabled"),
            prompt_security=SimpleNamespace(
                security_scan=SimpleNamespace(mode="enabled"),
                context_lens=SimpleNamespace(mode="disabled"),
                block_high_risk_prompts=SimpleNamespace(mode="enabled"),
            ),
            response_cache=SimpleNamespace(mode="inherit"),
            context_condensation=SimpleNamespace(mode="enabled"),
            prompt_batching=SimpleNamespace(mode="enabled"),
        ),
        response_cache=SimpleNamespace(enabled=False),
        batching=SimpleNamespace(enabled=False),
    )
    config.condensation = SimpleNamespace(enabled=False)

    assert config.resolve_feature_enabled("context_condensation") is True
    assert config.resolve_feature_enabled("prompt_batching") is True


def test_resolve_feature_enabled_falls_back_to_legacy_top_level_when_feature_control_inherits():
    config = Config.__new__(Config)
    config.aisbf = SimpleNamespace(
        feature_controls=SimpleNamespace(
            nsfw_classification=SimpleNamespace(mode="inherit"),
            privacy_classification=SimpleNamespace(mode="inherit"),
            prompt_security=SimpleNamespace(
                security_scan=SimpleNamespace(mode="inherit"),
                context_lens=SimpleNamespace(mode="inherit"),
                block_high_risk_prompts=SimpleNamespace(mode="inherit"),
            ),
            response_cache=SimpleNamespace(mode="inherit"),
            context_condensation=SimpleNamespace(mode="inherit"),
            prompt_batching=SimpleNamespace(mode="inherit"),
        ),
        response_cache=SimpleNamespace(enabled=True),
        batching=SimpleNamespace(enabled=True),
    )
    config.condensation = SimpleNamespace(enabled=True)

    assert config.resolve_feature_enabled("response_cache") is True
    assert config.resolve_feature_enabled("context_condensation") is True
    assert config.resolve_feature_enabled("prompt_batching") is True


def test_resolve_feature_enabled_supports_nsfw_and_privacy_classification_overrides():
    config = Config.__new__(Config)
    config.aisbf = SimpleNamespace(
        feature_controls=SimpleNamespace(
            nsfw_classification=SimpleNamespace(mode="enabled"),
            privacy_classification=SimpleNamespace(mode="disabled"),
            prompt_security=SimpleNamespace(
                security_scan=SimpleNamespace(mode="enabled"),
                context_lens=SimpleNamespace(mode="enabled"),
                block_high_risk_prompts=SimpleNamespace(mode="disabled"),
            ),
            response_cache=SimpleNamespace(mode="inherit"),
            context_condensation=SimpleNamespace(mode="inherit"),
            prompt_batching=SimpleNamespace(mode="inherit"),
        ),
        response_cache=SimpleNamespace(enabled=False),
        batching=SimpleNamespace(enabled=False),
    )
    config.condensation = SimpleNamespace(enabled=False)

    provider_config = SimpleNamespace(enable_nsfw_classification=False)
    model_config = {"enable_privacy_classification": True}

    assert config.resolve_feature_enabled(
        "nsfw_classification",
        provider_config=provider_config,
    ) is False
    assert config.resolve_feature_enabled(
        "privacy_classification",
        model_config=model_config,
    ) is True


def test_resolve_feature_enabled_reads_nested_prompt_security_defaults():
    config = Config.__new__(Config)
    config.aisbf = SimpleNamespace(
        feature_controls=SimpleNamespace(
            nsfw_classification=SimpleNamespace(mode="disabled"),
            privacy_classification=SimpleNamespace(mode="disabled"),
            prompt_security=SimpleNamespace(
                security_scan=SimpleNamespace(mode="enabled"),
                context_lens=SimpleNamespace(mode="enabled"),
                block_high_risk_prompts=SimpleNamespace(mode="disabled"),
            ),
            response_cache=SimpleNamespace(mode="inherit"),
            context_condensation=SimpleNamespace(mode="inherit"),
            prompt_batching=SimpleNamespace(mode="inherit"),
        ),
        response_cache=SimpleNamespace(enabled=False),
        batching=SimpleNamespace(enabled=False),
    )
    config.condensation = SimpleNamespace(enabled=False)

    assert config.resolve_feature_enabled("prompt_security") is True
    assert config.resolve_feature_enabled("context_lens") is True
    assert config.resolve_feature_enabled("block_high_risk_prompts") is False
