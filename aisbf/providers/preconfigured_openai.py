"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Pre-configured provider handlers for OpenAI-compatible APIs.

Each class is a thin subclass of OpenAIProviderHandler that ships with
a known default endpoint so users only need to supply an API key (and
optionally override the endpoint in their provider config).

Endpoint data sourced from the LiteLLM provider registry.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""
from typing import Any, Optional

from .openai import OpenAIProviderHandler


class _OpenAICompatBase(OpenAIProviderHandler):
    """
    Base for pre-configured OpenAI-compatible providers.

    Subclasses set DEFAULT_ENDPOINT and optionally DEFAULT_API_KEY_REQUIRED.
    If the provider config supplies no endpoint (or an empty one), the class
    default is used instead.  This lets users configure e.g. type="groq"
    without knowing or caring about the API base URL.
    """

    DEFAULT_ENDPOINT: str = ""
    DEFAULT_API_KEY_REQUIRED: bool = True

    def __init__(
        self,
        provider_id: str,
        api_key: Optional[str] = None,
        user_id: Optional[int] = None,
        provider_config: Optional[Any] = None,
    ):
        if provider_config is None:
            from ..config import config as _cfg
            provider_config = _cfg.providers.get(provider_id)

        # Inject default endpoint when the config has none
        if isinstance(provider_config, dict):
            if not provider_config.get("endpoint"):
                provider_config = {**provider_config, "endpoint": self.DEFAULT_ENDPOINT}
        elif provider_config is not None:
            ep = getattr(provider_config, "endpoint", None)
            if not ep:
                d = (
                    provider_config.model_dump()
                    if hasattr(provider_config, "model_dump")
                    else provider_config.dict()
                )
                d["endpoint"] = self.DEFAULT_ENDPOINT
                provider_config = d
        else:
            # No config at all — build a minimal dict so the parent can init
            provider_config = {
                "id": provider_id,
                "name": provider_id,
                "endpoint": self.DEFAULT_ENDPOINT,
                "type": provider_id,
                "api_key_required": self.DEFAULT_API_KEY_REQUIRED,
                "rate_limit": 0,
            }

        super().__init__(provider_id, api_key, user_id=user_id, provider_config=provider_config)


# ---------------------------------------------------------------------------
# Major inference API providers
# ---------------------------------------------------------------------------

class GroqProviderHandler(_OpenAICompatBase):
    """Groq — ultra-fast inference on custom LPU hardware."""
    DEFAULT_ENDPOINT = "https://api.groq.com/openai/v1"


class TogetherAIProviderHandler(_OpenAICompatBase):
    """Together AI — open-model inference and fine-tuning platform."""
    DEFAULT_ENDPOINT = "https://api.together.xyz/v1"


class FireworksAIProviderHandler(_OpenAICompatBase):
    """Fireworks AI — fast open-model inference."""
    DEFAULT_ENDPOINT = "https://api.fireworks.ai/inference/v1"


class MistralProviderHandler(_OpenAICompatBase):
    """Mistral AI — proprietary and open models."""
    DEFAULT_ENDPOINT = "https://api.mistral.ai/v1"


class CodestralProviderHandler(_OpenAICompatBase):
    """Codestral — Mistral's code-specialised model endpoint."""
    DEFAULT_ENDPOINT = "https://codestral.mistral.ai/v1"


class DeepSeekProviderHandler(_OpenAICompatBase):
    """DeepSeek — high-performance reasoning and coding models."""
    DEFAULT_ENDPOINT = "https://api.deepseek.com/v1"


class PerplexityProviderHandler(_OpenAICompatBase):
    """Perplexity AI — search-augmented language models."""
    DEFAULT_ENDPOINT = "https://api.perplexity.ai"


class DeepInfraProviderHandler(_OpenAICompatBase):
    """DeepInfra — serverless GPU inference for open models."""
    DEFAULT_ENDPOINT = "https://api.deepinfra.com/v1/openai"


class CerebrasProviderHandler(_OpenAICompatBase):
    """Cerebras — wafer-scale chip inference."""
    DEFAULT_ENDPOINT = "https://api.cerebras.ai/v1"


class SambaNovaProviderHandler(_OpenAICompatBase):
    """SambaNova — RDU-accelerated inference."""
    DEFAULT_ENDPOINT = "https://api.sambanova.ai/v1"


class XAIProviderHandler(_OpenAICompatBase):
    """xAI — Grok models from X (Twitter)."""
    DEFAULT_ENDPOINT = "https://api.x.ai/v1"


class MoonshotProviderHandler(_OpenAICompatBase):
    """Moonshot AI — Kimi long-context models."""
    DEFAULT_ENDPOINT = "https://api.moonshot.ai/v1"


class DashScopeProviderHandler(_OpenAICompatBase):
    """Alibaba DashScope — Qwen and other Alibaba models."""
    DEFAULT_ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class NvidiaNIMProviderHandler(_OpenAICompatBase):
    """NVIDIA NIM — NVIDIA-hosted inference microservices."""
    DEFAULT_ENDPOINT = "https://integrate.api.nvidia.com/v1"


class NScaleProviderHandler(_OpenAICompatBase):
    """NScale — GPU cloud inference."""
    DEFAULT_ENDPOINT = "https://inference.api.nscale.com/v1"


class FeatherlessAIProviderHandler(_OpenAICompatBase):
    """Featherless AI — serverless open-model inference."""
    DEFAULT_ENDPOINT = "https://api.featherless.ai/v1"


class OpenRouterProviderHandler(_OpenAICompatBase):
    """OpenRouter — unified gateway to 200+ models from all major providers."""
    DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1"


class ScalewayProviderHandler(_OpenAICompatBase):
    """Scaleway Generative APIs — European cloud AI."""
    DEFAULT_ENDPOINT = "https://api.scaleway.ai/v1"


class VolcEngineProviderHandler(_OpenAICompatBase):
    """VolcEngine Ark — ByteDance's model inference platform."""
    DEFAULT_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3"


class FriendliAIProviderHandler(_OpenAICompatBase):
    """FriendliAI — serverless and dedicated inference."""
    DEFAULT_ENDPOINT = "https://api.friendli.ai/serverless/v1"


class HyperbolicProviderHandler(_OpenAICompatBase):
    """Hyperbolic — GPU cloud inference."""
    DEFAULT_ENDPOINT = "https://api.hyperbolic.xyz/v1"


class NebiusProviderHandler(_OpenAICompatBase):
    """Nebius AI Studio — European GPU cloud."""
    DEFAULT_ENDPOINT = "https://api.studio.nebius.ai/v1"


class NovitaProviderHandler(_OpenAICompatBase):
    """Novita AI — open-model inference."""
    DEFAULT_ENDPOINT = "https://api.novita.ai/v3/openai"


class LambdaAIProviderHandler(_OpenAICompatBase):
    """Lambda AI — GPU cloud inference."""
    DEFAULT_ENDPOINT = "https://api.lambda.ai/v1"


class OVHCloudProviderHandler(_OpenAICompatBase):
    """OVHcloud AI Endpoints — European sovereign AI."""
    DEFAULT_ENDPOINT = "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"


class AIMLAPIProviderHandler(_OpenAICompatBase):
    """AI/ML API — multi-provider unified gateway."""
    DEFAULT_ENDPOINT = "https://api.aimlapi.com/v1"


class CometAPIProviderHandler(_OpenAICompatBase):
    """CometAPI — OpenAI-compatible model gateway."""
    DEFAULT_ENDPOINT = "https://api.cometapi.com/v1"


class GaladrielProviderHandler(_OpenAICompatBase):
    """Galadriel — decentralised AI inference."""
    DEFAULT_ENDPOINT = "https://api.galadriel.com/v1"


class MorphProviderHandler(_OpenAICompatBase):
    """Morph — fast code completion inference."""
    DEFAULT_ENDPOINT = "https://api.morphllm.com/v1"


class GitHubModelsProviderHandler(_OpenAICompatBase):
    """GitHub Models — Azure AI Inference endpoint behind a GitHub PAT."""
    DEFAULT_ENDPOINT = "https://models.inference.ai.azure.com"


class AI21ProviderHandler(_OpenAICompatBase):
    """AI21 Labs — Jamba and Jurassic series models."""
    DEFAULT_ENDPOINT = "https://api.ai21.com/studio/v1"


class NLPCloudProviderHandler(_OpenAICompatBase):
    """NLP Cloud — hosted open-source NLP models."""
    DEFAULT_ENDPOINT = "https://api.nlpcloud.io/v1"


class ClarifaiProviderHandler(_OpenAICompatBase):
    """Clarifai — AI platform with OpenAI-compatible inference."""
    DEFAULT_ENDPOINT = "https://api.clarifai.com/v2/ext/openai/v1"


class EmpowerProviderHandler(_OpenAICompatBase):
    """Empower — privacy-focused inference."""
    DEFAULT_ENDPOINT = "https://app.empower.dev/api/v1"


class GradientAIProviderHandler(_OpenAICompatBase):
    """Gradient AI — fine-tuning and inference."""
    DEFAULT_ENDPOINT = "https://inference.do-ai.run/v1"


class CompactifAIProviderHandler(_OpenAICompatBase):
    """CompactifAI — model compression and inference."""
    DEFAULT_ENDPOINT = "https://api.compactif.ai/v1"


class MariTalkProviderHandler(_OpenAICompatBase):
    """MariTalk (Maritaca AI) — Brazilian Portuguese language models."""
    DEFAULT_ENDPOINT = "https://api.maritalk.com/v1"


class MetaLlamaProviderHandler(_OpenAICompatBase):
    """Meta Llama API — official Meta inference endpoint."""
    DEFAULT_ENDPOINT = "https://api.llama.com/compat/v1"


class PredibaseProviderHandler(_OpenAICompatBase):
    """Predibase — fine-tuned LoRA adapter serving."""
    DEFAULT_ENDPOINT = "https://serving.app.predibase.com/v1"


class ZAIProviderHandler(_OpenAICompatBase):
    """ZAI / 01.AI — Yi series models."""
    DEFAULT_ENDPOINT = "https://api.z.ai/api/paas/v4"


class VoyageAIProviderHandler(_OpenAICompatBase):
    """VoyageAI — embedding and reranking models."""
    DEFAULT_ENDPOINT = "https://api.voyageai.com/v1"


class WandBInferenceProviderHandler(_OpenAICompatBase):
    """Weights & Biases Inference — W&B hosted model serving."""
    DEFAULT_ENDPOINT = "https://api.inference.wandb.ai/v1"


class CohereProviderHandler(_OpenAICompatBase):
    """Cohere — Command and Embed models via OpenAI compatibility layer."""
    DEFAULT_ENDPOINT = "https://api.cohere.ai/compatibility/v1"


class MiniMaxProviderHandler(_OpenAICompatBase):
    """MiniMax — long-context Chinese and multilingual models."""
    DEFAULT_ENDPOINT = "https://api.minimax.io/v1"


class PublicAIProviderHandler(_OpenAICompatBase):
    """PublicAI — public model inference."""
    DEFAULT_ENDPOINT = "https://api.publicai.co/v1"


class HeliconeProviderHandler(_OpenAICompatBase):
    """Helicone AI Gateway — observability proxy in front of OpenAI-compatible APIs."""
    DEFAULT_ENDPOINT = "https://ai-gateway.helicone.ai"


class VeniceAIProviderHandler(_OpenAICompatBase):
    """Venice AI — privacy-preserving inference."""
    DEFAULT_ENDPOINT = "https://api.venice.ai/api/v1"


class AIHubMixProviderHandler(_OpenAICompatBase):
    """AIHubMix — model aggregation gateway."""
    DEFAULT_ENDPOINT = "https://aihubmix.com/v1"


class CharityEngineProviderHandler(_OpenAICompatBase):
    """Charity Engine — distributed volunteer compute."""
    DEFAULT_ENDPOINT = "https://api.charityengine.services/remotejobs/v2/inference"


class PoeProviderHandler(_OpenAICompatBase):
    """Poe API — Quora's multi-model platform."""
    DEFAULT_ENDPOINT = "https://api.poe.com/v1"


class ChutesProviderHandler(_OpenAICompatBase):
    """Chutes AI — decentralised GPU inference."""
    DEFAULT_ENDPOINT = "https://llm.chutes.ai/v1"


class SyntheticProviderHandler(_OpenAICompatBase):
    """Synthetic AI — open-model inference."""
    DEFAULT_ENDPOINT = "https://api.synthetic.new/openai/v1"


class AssemblyAILLMProviderHandler(_OpenAICompatBase):
    """AssemblyAI LLM Gateway — AI speech and language platform."""
    DEFAULT_ENDPOINT = "https://llm-gateway.assemblyai.com/v1"


class GMIProviderHandler(_OpenAICompatBase):
    """GMI Serving — GPU model inference."""
    DEFAULT_ENDPOINT = "https://api.gmi-serving.com/v1"


class SarvamProviderHandler(_OpenAICompatBase):
    """Sarvam AI — Indian language models."""
    DEFAULT_ENDPOINT = "https://api.sarvam.ai/v1"


class NanoGPTProviderHandler(_OpenAICompatBase):
    """Nano-GPT — pay-per-token inference."""
    DEFAULT_ENDPOINT = "https://nano-gpt.com/api/v1"


class LlamaGateProviderHandler(_OpenAICompatBase):
    """LlamaGate — open-model inference gateway."""
    DEFAULT_ENDPOINT = "https://api.llamagate.dev/v1"


class AbliterationProviderHandler(_OpenAICompatBase):
    """Abliteration AI — uncensored model inference."""
    DEFAULT_ENDPOINT = "https://api.abliteration.ai/v1"


class CrusoeProviderHandler(_OpenAICompatBase):
    """Crusoe Cloud — sustainable GPU inference."""
    DEFAULT_ENDPOINT = "https://managed-inference-api-proxy.crusoecloud.com/v1"


class XiaomiMimoProviderHandler(_OpenAICompatBase):
    """Xiaomi MiMo — Xiaomi's reasoning model API."""
    DEFAULT_ENDPOINT = "https://api.xiaomimimo.com/v1"


class ApertisProviderHandler(_OpenAICompatBase):
    """Apertis / Stima — OpenAI-compatible inference."""
    DEFAULT_ENDPOINT = "https://api.stima.tech/v1"


class VercelAIGatewayProviderHandler(_OpenAICompatBase):
    """Vercel AI Gateway — edge-deployed model routing."""
    DEFAULT_ENDPOINT = "https://ai-gateway.vercel.sh/v1"


class BasetenProviderHandler(_OpenAICompatBase):
    """Baseten — custom model deployment and inference."""
    DEFAULT_ENDPOINT = "https://inference.baseten.co/v1"


class JinaAIProviderHandler(_OpenAICompatBase):
    """Jina AI — embedding, reranking, and reader models."""
    DEFAULT_ENDPOINT = "https://api.jina.ai/v1"


class HuggingFaceProviderHandler(_OpenAICompatBase):
    """HuggingFace Inference API — hosted open-source models."""
    DEFAULT_ENDPOINT = "https://api-inference.huggingface.co/v1"


# ---------------------------------------------------------------------------
# Local / self-hosted runtimes  (no API key required by default)
# ---------------------------------------------------------------------------

class LMStudioProviderHandler(_OpenAICompatBase):
    """LM Studio — local model inference server."""
    DEFAULT_ENDPOINT = "http://localhost:1234/v1"
    DEFAULT_API_KEY_REQUIRED = False


class LlamafileProviderHandler(_OpenAICompatBase):
    """Llamafile — single-file local model server."""
    DEFAULT_ENDPOINT = "http://localhost:8080/v1"
    DEFAULT_API_KEY_REQUIRED = False


class VLLMProviderHandler(_OpenAICompatBase):
    """vLLM — high-throughput local/self-hosted inference engine."""
    DEFAULT_ENDPOINT = "http://localhost:8000/v1"
    DEFAULT_API_KEY_REQUIRED = False


class XinferenceProviderHandler(_OpenAICompatBase):
    """Xorbits Inference — local model serving framework."""
    DEFAULT_ENDPOINT = "http://localhost:9997/v1"
    DEFAULT_API_KEY_REQUIRED = False


class InfinityProviderHandler(_OpenAICompatBase):
    """Infinity — local embedding and reranking server."""
    DEFAULT_ENDPOINT = "http://localhost:8000/v1"
    DEFAULT_API_KEY_REQUIRED = False


class OobaboogaProviderHandler(_OpenAICompatBase):
    """Text Generation WebUI (oobabooga) — local model server with OpenAI extension."""
    DEFAULT_ENDPOINT = "http://localhost:5000/v1"
    DEFAULT_API_KEY_REQUIRED = False


class DockerModelRunnerProviderHandler(_OpenAICompatBase):
    """Docker Model Runner — Docker Desktop built-in model serving."""
    DEFAULT_ENDPOINT = "http://localhost:12434/engines/llama.cpp/v1"
    DEFAULT_API_KEY_REQUIRED = False


class TabbyAPIProviderHandler(_OpenAICompatBase):
    """TabbyAPI — exllamav2-based local inference server."""
    DEFAULT_ENDPOINT = "http://localhost:5000/v1"
    DEFAULT_API_KEY_REQUIRED = False


# ---------------------------------------------------------------------------
# Cloud providers with user-configured endpoints
# (endpoint MUST be set in config — no sensible universal default exists)
# ---------------------------------------------------------------------------

class AzureOpenAIProviderHandler(_OpenAICompatBase):
    """
    Azure OpenAI Service.
    Set endpoint to your deployment URL:
    https://<resource>.openai.azure.com/openai/deployments/<deployment>
    """
    DEFAULT_ENDPOINT = ""


class DatabricksProviderHandler(_OpenAICompatBase):
    """
    Databricks Model Serving.
    Set endpoint to your workspace serving endpoint:
    https://<workspace>.databricks.com/serving-endpoints
    """
    DEFAULT_ENDPOINT = ""


class SnowflakeProviderHandler(_OpenAICompatBase):
    """
    Snowflake Cortex.
    Set endpoint to your account URL:
    https://<account>.snowflakecomputing.com/api/v2
    """
    DEFAULT_ENDPOINT = ""


class HerokuProviderHandler(_OpenAICompatBase):
    """
    Heroku AI (Managed Inference).
    Set endpoint to your Heroku app inference URL.
    """
    DEFAULT_ENDPOINT = ""
