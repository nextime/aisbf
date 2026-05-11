"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

RunPod provider handler.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx

from ..config import config
from ..database import DatabaseRegistry
from ..models import Model
from .base import BaseProviderHandler
from .coderai import CoderAIProviderHandler
from .ollama import OllamaProviderHandler
from .openai import OpenAIProviderHandler


logger = logging.getLogger(__name__)

RUNPOD_MANAGEMENT_BASE = "https://rest.runpod.io/v1"
RUNPOD_PUBLIC_BASE = "https://api.runpod.ai/v2"
RUNPOD_PUBLIC_PROTOCOLS = {"runpod_public", "openai", "ollama", "coderai"}
RUNPOD_WRAPPER_MODES = {"openai", "ollama", "coderai"}
RUNPOD_RUNTIME_RUNNING = {"running", "ready", "completed", "healthy", "active"}
RUNPOD_RUNTIME_STOPPED = {"stopped", "exited", "terminated", "idle"}


class RunpodProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: Optional[str] = None, user_id: Optional[int] = None, provider_config: Optional[Any] = None):
        self.provider_config = provider_config if provider_config is not None else config.get_provider(provider_id)
        super().__init__(provider_id, api_key, user_id=user_id)
        self.user_provider_config = provider_config if isinstance(provider_config, dict) else self.user_provider_config
        self._runpod_config = self._resolve_runpod_config()
        self._mode = str(self._runpod_config.get("mode") or "pod").strip().lower()
        self._wrapper_mode = str(self._runpod_config.get("wrapper_mode") or "openai").strip().lower()
        self._management_api = str(self._runpod_config.get("management_api") or "auto").strip().lower()
        self._startup_poll_interval_ms = int(self._runpod_config.get("startup_poll_interval_ms") or 3000)
        self._startup_timeout_ms = int(self._runpod_config.get("startup_timeout_ms") or 300000)
        self._idle_shutdown_ms = int(self._runpod_config.get("idle_shutdown_ms") or 900000)
        self._public_endpoint_protocol_default = str(self._runpod_config.get("public_endpoint_protocol_default") or "auto").strip().lower()
        self._management_base = (self._get_provider_value("endpoint") or RUNPOD_MANAGEMENT_BASE).rstrip("/")

    def _get_provider_value(self, key: str, default: Any = None) -> Any:
        if isinstance(self.provider_config, dict):
            return self.provider_config.get(key, default)
        return getattr(self.provider_config, key, default)

    def _resolve_runpod_config(self) -> Dict[str, Any]:
        if isinstance(self.provider_config, dict):
            raw = self.provider_config.get("runpod_config") or {}
        else:
            raw = getattr(self.provider_config, "runpod_config", None) or {}
        return raw if isinstance(raw, dict) else {}

    def validate_credentials(self) -> bool:
        key = self.api_key or self._get_provider_value("api_key")
        if not isinstance(key, str) or not key.strip() or key.strip().startswith("YOUR_"):
            logger.error("[%s] RunPod API key required but not configured", self.provider_id)
            return False
        if self._mode not in {"pod", "serverless_template", "public"}:
            logger.error("[%s] Unsupported RunPod mode: %s", self.provider_id, self._mode)
            return False
        if self._mode != "public" and self._wrapper_mode not in RUNPOD_WRAPPER_MODES:
            logger.error("[%s] Unsupported RunPod wrapper mode: %s", self.provider_id, self._wrapper_mode)
            return False
        return True

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None, temperature: Optional[float] = 1.0, stream: Optional[bool] = False, tools: Optional[List[Dict]] = None, tool_choice: Optional[Any] = None):
        await self.apply_rate_limit()
        if self._mode == "public":
            response = await self._handle_public_request(model, messages, max_tokens=max_tokens, temperature=temperature)
            self.record_success()
            return response

        await self._ensure_non_public_resource_ready()
        delegate = self._build_delegate_handler(self._wrapper_mode)
        response = await delegate.handle_request(model, messages, max_tokens=max_tokens, temperature=temperature, stream=stream, tools=tools, tool_choice=tool_choice)
        self.record_success()
        return response

    async def get_models(self) -> List[Model]:
        await self.apply_rate_limit()
        if self._mode == "public":
            catalog = await self._get_public_catalog()
            return [self._catalog_entry_to_model(entry) for entry in catalog]

        await self._ensure_non_public_resource_ready()
        delegate = self._build_delegate_handler(self._wrapper_mode)
        return await delegate.get_models()

    async def refresh_public_catalog(self) -> List[Dict[str, Any]]:
        state = self._db().get_runpod_provider_state(self._provider_scope(), self.user_id, self.provider_id)
        metadata = dict((state or {}).get("metadata") or {})
        try:
            catalog = self._apply_public_model_overrides(
                self._normalize_public_catalog(await self._fetch_live_public_catalog_entries())
            )
        except Exception as exc:
            metadata["catalog_refresh_error"] = str(exc)
            if state:
                self._db().save_runpod_provider_state(
                    provider_scope=self._provider_scope(),
                    owner_user_id=self.user_id,
                    provider_id=self.provider_id,
                    mode=state.get("mode") or "public",
                    wrapper_mode=state.get("wrapper_mode"),
                    resource_id=state.get("resource_id") or "public-catalog",
                    resource_kind=state.get("resource_kind") or "public",
                    status=state.get("status") or "ready",
                    endpoint_url=state.get("endpoint_url"),
                    public_catalog_json=state.get("public_catalog_json") or [],
                    metadata=metadata,
                    last_used_at=state.get("last_used_at"),
                    last_status_sync_at=state.get("last_status_sync_at"),
                )
            raise
        metadata["catalog_refreshed_at"] = int(time.time())
        metadata["catalog_item_count"] = len(catalog)
        metadata["catalog_source"] = "live"
        metadata.pop("catalog_refresh_error", None)
        self._db().save_runpod_provider_state(
            provider_scope=self._provider_scope(),
            owner_user_id=self.user_id,
            provider_id=self.provider_id,
            mode="public",
            wrapper_mode=None,
            resource_id="public-catalog",
            resource_kind="public",
            status="ready",
            endpoint_url=RUNPOD_PUBLIC_BASE,
            public_catalog_json=catalog,
            metadata=metadata,
        )
        return catalog

    async def _fetch_live_public_catalog_entries(self) -> List[Dict[str, Any]]:
        seed_entries = self._runpod_config.get("public_catalog_seed") or []
        return [entry for entry in seed_entries if isinstance(entry, dict)]

    def _apply_public_model_overrides(self, catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        overrides = self._runpod_config.get("public_models") or {}
        if not isinstance(overrides, dict):
            return catalog

        normalized = []
        for entry in catalog:
            patched = dict(entry)
            override = overrides.get(entry.get("id")) or {}
            if not isinstance(override, dict):
                normalized.append(patched)
                continue

            protocol = override.get("protocol")
            if protocol:
                patched["protocol"] = str(protocol).strip().lower()
            if override.get("capabilities"):
                patched["capabilities"] = list(override.get("capabilities") or [])
            normalized.append(patched)
        return normalized

    async def poll_idle_shutdown(self) -> bool:
        if self._mode != "pod" or self._idle_shutdown_ms <= 0:
            return False
        state = self._db().get_runpod_provider_state(self._provider_scope(), self.user_id, self.provider_id)
        if not state or state.get("last_used_at") is None:
            return False
        now = time.time()
        last_used_at = self._to_timestamp(state.get("last_used_at"))
        if last_used_at is None or (now - last_used_at) * 1000 < self._idle_shutdown_ms:
            return False
        if not self._is_running_status(state.get("status")):
            return False
        pod_id = self._runpod_config.get("pod_id") or state.get("resource_id")
        if not pod_id:
            return False
        await self._management_request("POST", f"/pods/{pod_id}/stop")
        self._db().save_runpod_provider_state(
            provider_scope=self._provider_scope(),
            owner_user_id=self.user_id,
            provider_id=self.provider_id,
            mode=self._mode,
            wrapper_mode=self._wrapper_mode,
            resource_id=pod_id,
            resource_kind="pod",
            status="stopped",
            endpoint_url=state.get("endpoint_url"),
            public_catalog_json=state.get("public_catalog_json"),
            metadata=state.get("metadata") or {},
            last_used_at=state.get("last_used_at"),
        )
        return True

    def current_runtime_state(self) -> Optional[Dict[str, Any]]:
        return self._db().get_runpod_provider_state(self._provider_scope(), self.user_id, self.provider_id)

    def build_runtime_status(self) -> Dict[str, Any]:
        state = self.current_runtime_state() or {}
        metadata = dict(state.get("metadata") or {})
        catalog = self._normalize_public_catalog(state.get("public_catalog_json"))
        return {
            "provider_id": self.provider_id,
            "provider_scope": self._provider_scope(),
            "mode": state.get("mode") or self._mode,
            "wrapper_mode": state.get("wrapper_mode") or (None if (state.get("mode") or self._mode) == "public" else self._wrapper_mode),
            "resource_id": state.get("resource_id"),
            "resource_kind": state.get("resource_kind"),
            "status": state.get("status") or "unknown",
            "endpoint_url": state.get("endpoint_url"),
            "last_used_at": state.get("last_used_at"),
            "last_status_sync_at": state.get("last_status_sync_at"),
            "updated_at": state.get("updated_at"),
            "catalog": {
                "item_count": metadata.get("catalog_item_count", len(catalog)),
                "refreshed_at": metadata.get("catalog_refreshed_at"),
                "source": metadata.get("catalog_source"),
                "refresh_error": metadata.get("catalog_refresh_error"),
                "models": catalog,
            },
            "metadata": metadata,
        }

    async def _handle_public_request(self, model: str, messages: List[Dict], max_tokens: Optional[int], temperature: Optional[float]) -> Dict[str, Any]:
        entry = await self._resolve_public_model(model)
        protocol = self._resolve_public_protocol(entry)
        if protocol == "openai":
            delegate = self._build_delegate_handler("openai", endpoint_override=entry.get("route_base"), api_key_override=self.api_key)
            return await delegate.handle_request(model, messages, max_tokens=max_tokens, temperature=temperature, stream=False)
        if protocol == "ollama":
            delegate = self._build_delegate_handler("ollama", endpoint_override=entry.get("route_base"), api_key_override=self.api_key)
            return await delegate.handle_request(model, messages, max_tokens=max_tokens, temperature=temperature, stream=False)
        payload = {
            "input": {
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        }
        route_base = (entry.get("route_base") or f"{RUNPOD_PUBLIC_BASE}/{entry.get('id')}").rstrip("/")
        request_mode = str(entry.get("request_mode") or "runsync").strip().lower()
        if request_mode not in {"run", "runsync"}:
            request_mode = "runsync"
        response = await self._public_request("POST", f"{route_base}/{request_mode}", json_body=payload)
        return self._wrap_public_response(model, entry, response)

    async def _ensure_non_public_resource_ready(self) -> Dict[str, Any]:
        if self._mode == "serverless_template":
            return await self._ensure_serverless_endpoint_ready()
        return await self._ensure_pod_ready()

    async def _ensure_pod_ready(self) -> Dict[str, Any]:
        pod_id = self._runpod_config.get("pod_id")
        if not pod_id:
            raise ValueError(f"RunPod provider '{self.provider_id}' requires runpod_config.pod_id")

        state = self._db().get_runpod_provider_state(self._provider_scope(), self.user_id, self.provider_id)
        pod = await self._management_request("GET", f"/pods/{pod_id}", params={"includeTemplate": True})
        status = self._extract_pod_status(pod)
        if self._is_stopped_status(status):
            await self._management_request("POST", f"/pods/{pod_id}/start")
            pod = await self._wait_for_pod_ready(pod_id)
            status = self._extract_pod_status(pod)
        elif not self._is_running_status(status):
            pod = await self._wait_for_pod_ready(pod_id)
            status = self._extract_pod_status(pod)

        endpoint_url = self._derive_pod_endpoint_url(pod)
        metadata = dict((state or {}).get("metadata") or {})
        metadata["pod"] = pod
        now = time.time()
        self._db().save_runpod_provider_state(
            provider_scope=self._provider_scope(),
            owner_user_id=self.user_id,
            provider_id=self.provider_id,
            mode="pod",
            wrapper_mode=self._wrapper_mode,
            resource_id=pod_id,
            resource_kind="pod",
            status=status,
            endpoint_url=endpoint_url,
            public_catalog_json=(state or {}).get("public_catalog_json"),
            metadata=metadata,
            last_used_at=now,
        )
        return {"status": status, "endpoint_url": endpoint_url, "pod": pod}

    async def _wait_for_pod_ready(self, pod_id: str) -> Dict[str, Any]:
        deadline = time.time() + (self._startup_timeout_ms / 1000.0)
        interval = max(self._startup_poll_interval_ms / 1000.0, 0.1)
        last_pod = None
        while time.time() < deadline:
            last_pod = await self._management_request("GET", f"/pods/{pod_id}", params={"includeTemplate": True})
            if self._pod_is_ready(last_pod):
                return last_pod
            await asyncio.sleep(interval)
        raise TimeoutError(f"RunPod pod '{pod_id}' did not become ready within {self._startup_timeout_ms}ms")

    async def _ensure_serverless_endpoint_ready(self) -> Dict[str, Any]:
        endpoint_id = self._runpod_config.get("endpoint_id")
        if not endpoint_id:
            endpoint_id = await self._resolve_endpoint_from_serverless_template()
        endpoint = await self._management_request("GET", f"/endpoints/{endpoint_id}", params={"includeTemplate": True, "includeWorkers": True})
        endpoint_url = self._derive_serverless_endpoint_url(endpoint)
        state = self._db().get_runpod_provider_state(self._provider_scope(), self.user_id, self.provider_id)
        metadata = dict((state or {}).get("metadata") or {})
        metadata["endpoint"] = endpoint
        self._db().save_runpod_provider_state(
            provider_scope=self._provider_scope(),
            owner_user_id=self.user_id,
            provider_id=self.provider_id,
            mode="serverless_template",
            wrapper_mode=self._wrapper_mode,
            resource_id=endpoint_id,
            resource_kind="endpoint",
            status="ready",
            endpoint_url=endpoint_url,
            public_catalog_json=(state or {}).get("public_catalog_json"),
            metadata=metadata,
            last_used_at=time.time(),
        )
        return {"status": "ready", "endpoint_url": endpoint_url, "endpoint": endpoint}

    async def _resolve_endpoint_from_serverless_template(self) -> str:
        configured_endpoint = self._runpod_config.get("endpoint_id")
        if configured_endpoint:
            return configured_endpoint
        template_id = self._runpod_config.get("serverless_template_id") or self._runpod_config.get("template_id")
        if not template_id:
            raise ValueError(f"RunPod provider '{self.provider_id}' requires endpoint_id or serverless_template_id in serverless_template mode")

        endpoints = await self._management_request("GET", "/endpoints", params={"includeTemplate": True})
        items = self._extract_items(endpoints)
        for endpoint in items:
            if str(endpoint.get("templateId") or "") == str(template_id):
                return endpoint.get("id")

        payload = {
            "name": f"AISBF {self.provider_id}",
            "templateId": template_id,
        }
        created = await self._management_request("POST", "/endpoints", json_body=payload)
        endpoint_id = created.get("id")
        if not endpoint_id:
            raise ValueError(f"RunPod endpoint creation for provider '{self.provider_id}' did not return an endpoint id")
        return endpoint_id

    async def _get_public_catalog(self) -> List[Dict[str, Any]]:
        state = self._db().get_runpod_provider_state(self._provider_scope(), self.user_id, self.provider_id)
        cached = self._normalize_public_catalog((state or {}).get("public_catalog_json"))
        if cached:
            return cached
        return await self.refresh_public_catalog()

    async def _resolve_public_model(self, model: str) -> Dict[str, Any]:
        requested = model.split("/", 1)[-1]
        catalog = await self._get_public_catalog()
        for entry in catalog:
            if entry.get("id") == requested or entry.get("name") == requested:
                self._touch_runtime_state()
                return entry
        raise ValueError(f"RunPod public model '{requested}' not found for provider '{self.provider_id}'")

    def _resolve_public_protocol(self, entry: Dict[str, Any]) -> str:
        manual = ((self._runpod_config.get("public_models") or {}).get(entry.get("id") or "") or {}).get("protocol")
        candidate = str(manual or entry.get("protocol") or self._public_endpoint_protocol_default or "runpod_public").strip().lower()
        if candidate == "auto":
            candidate = self._infer_public_protocol(entry)
        if candidate not in RUNPOD_PUBLIC_PROTOCOLS:
            candidate = "runpod_public"
        return candidate

    def _infer_public_protocol(self, entry: Dict[str, Any]) -> str:
        route_base = str(entry.get("route_base") or "").lower()
        schema = entry.get("schema") or {}
        if any(token in route_base for token in ("/v1", "openai")):
            return "openai"
        if str(schema).lower().find("messages") >= 0:
            return "openai"
        return "runpod_public"

    def _catalog_entry_to_model(self, entry: Dict[str, Any]) -> Model:
        identifier = str(entry.get("id") or entry.get("name") or "unknown")
        return Model(
            id=identifier,
            name=entry.get("name") or identifier,
            provider_id=self.provider_id,
            description=entry.get("description"),
            architecture=entry.get("architecture"),
            pricing=entry.get("pricing"),
            context_length=entry.get("context_length"),
            context_size=entry.get("context_length"),
            supported_parameters=entry.get("supported_parameters"),
        )

    def _wrap_public_response(self, model: str, entry: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
        output = response.get("output")
        if isinstance(output, dict) and "choices" in output:
            return output
        text = None
        if isinstance(output, dict):
            text = output.get("text") or output.get("response") or output.get("content")
        elif isinstance(output, str):
            text = output
        payload = {
            "id": response.get("id") or f"runpod-{entry.get('id')}-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"{self.provider_id}/{model.split('/', 1)[-1]}",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text or json.dumps(output or response)}, "finish_reason": "stop"}],
            "usage": response.get("usage") or {},
            "runpod": response,
        }
        return payload

    def _build_delegate_handler(self, wrapper_mode: str, endpoint_override: Optional[str] = None, api_key_override: Optional[str] = None):
        provider_dict = self._provider_dict_with_endpoint(endpoint_override)
        api_key = api_key_override or self.api_key or self._get_provider_value("api_key")
        if wrapper_mode == "openai":
            return OpenAIProviderHandler(self.provider_id, api_key, provider_config=provider_dict)
        if wrapper_mode == "ollama":
            return OllamaProviderHandler(self.provider_id, api_key, provider_config=provider_dict)
        if wrapper_mode == "coderai":
            return CoderAIProviderHandler(self.provider_id, api_key, user_id=self.user_id, provider_config=provider_dict)
        raise ValueError(f"Unsupported RunPod wrapper mode '{wrapper_mode}'")

    def _provider_dict_with_endpoint(self, endpoint_override: Optional[str]) -> Dict[str, Any]:
        if isinstance(self.provider_config, dict):
            data = dict(self.provider_config)
        else:
            data = self.provider_config.model_dump() if hasattr(self.provider_config, "model_dump") else dict(self.provider_config.dict())
        runtime_state = self.current_runtime_state() or {}
        data["endpoint"] = endpoint_override or runtime_state.get("endpoint_url") or data.get("endpoint")
        return data

    def _provider_scope(self) -> str:
        return "user" if self.user_id is not None else "global"

    def _db(self):
        return DatabaseRegistry.get_config_database()

    def _touch_runtime_state(self) -> None:
        self._db().touch_runpod_provider_state(self._provider_scope(), self.user_id, self.provider_id)

    async def _management_request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key or self._get_provider_value('api_key')}", "Content-Type": "application/json"}
        url = f"{self._management_base}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method.upper(), url, headers=headers, params=params, json=json_body)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()

    async def _public_request(self, method: str, url: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key or self._get_provider_value('api_key')}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(method.upper(), url, headers=headers, json=json_body)
            response.raise_for_status()
            return response.json()

    def _extract_pod_status(self, pod: Dict[str, Any]) -> str:
        return str(pod.get("desiredStatus") or pod.get("status") or "unknown").strip().lower()

    def _extract_items(self, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("data", "items", "pods", "endpoints", "templates"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def _derive_pod_endpoint_url(self, pod: Dict[str, Any]) -> str:
        port_mappings = pod.get("portMappings") or []
        public_ip = pod.get("publicIp")
        if public_ip and isinstance(port_mappings, list) and port_mappings:
            first_mapping = port_mappings[0]
            if isinstance(first_mapping, dict):
                public_port = first_mapping.get("publicPort") or first_mapping.get("port") or first_mapping.get("containerPort")
            else:
                public_port = None
            if public_port:
                scheme = "http"
                if self._wrapper_mode == "openai":
                    return f"{scheme}://{public_ip}:{public_port}/v1"
                if self._wrapper_mode == "ollama":
                    return f"{scheme}://{public_ip}:{public_port}"
                return f"{scheme}://{public_ip}:{public_port}"
        return ""

    def _derive_serverless_endpoint_url(self, endpoint: Dict[str, Any]) -> str:
        endpoint_id = endpoint.get("id") or self._runpod_config.get("endpoint_id")
        if not endpoint_id:
            raise ValueError(f"RunPod provider '{self.provider_id}' serverless endpoint is missing an id")
        if self._wrapper_mode == "openai":
            return f"{RUNPOD_PUBLIC_BASE}/{endpoint_id}/openai/v1"
        if self._wrapper_mode == "ollama":
            return f"{RUNPOD_PUBLIC_BASE}/{endpoint_id}"
        return f"{RUNPOD_PUBLIC_BASE}/{endpoint_id}"

    def _pod_is_ready(self, pod: Dict[str, Any]) -> bool:
        status = self._extract_pod_status(pod)
        if status not in RUNPOD_RUNTIME_RUNNING:
            return False
        return bool(self._derive_pod_endpoint_url(pod))

    def _is_running_status(self, status: Optional[str]) -> bool:
        return str(status or "").strip().lower() in RUNPOD_RUNTIME_RUNNING

    def _is_stopped_status(self, status: Optional[str]) -> bool:
        return str(status or "").strip().lower() in RUNPOD_RUNTIME_STOPPED

    def _normalize_public_catalog(self, entries: Any) -> List[Dict[str, Any]]:
        normalized = []
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            identifier = str(entry.get("id") or entry.get("name") or "").strip()
            if not identifier:
                continue
            route_base = str(entry.get("route_base") or f"{RUNPOD_PUBLIC_BASE}/{identifier}").rstrip("/")
            protocol = str(entry.get("protocol") or "auto").lower()
            if protocol == "auto":
                protocol = self._infer_public_protocol({**entry, "id": identifier, "route_base": route_base})
            normalized.append({
                "id": identifier,
                "name": entry.get("name") or identifier,
                "protocol": protocol,
                "capabilities": list(entry.get("capabilities") or []),
                "route_base": route_base,
                "request_mode": str(entry.get("request_mode") or "runsync").lower(),
                "description": entry.get("description"),
                "pricing": entry.get("pricing"),
                "architecture": entry.get("architecture"),
                "context_length": entry.get("context_length"),
                "supported_parameters": entry.get("supported_parameters"),
                "schema": entry.get("schema"),
            })
        return normalized

    @staticmethod
    def _to_timestamp(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None


async def runpod_idle_shutdown_loop(poll_interval_seconds: float = 30.0) -> None:
    while True:
        try:
            db = DatabaseRegistry.get_config_database()
            for state in db.list_runpod_provider_states():
                if (state or {}).get("mode") != "pod":
                    continue
                provider_id = state.get("provider_id")
                owner_user_id = state.get("owner_user_id")
                api_key = None
                provider_config = None
                if owner_user_id is None:
                    provider_config = config.providers.get(provider_id)
                    api_key = getattr(provider_config, "api_key", None) if provider_config else None
                else:
                    provider = db.get_user_provider(owner_user_id, provider_id)
                    if provider:
                        provider_config = provider.get("config")
                        api_key = (provider_config or {}).get("api_key")
                if not provider_config:
                    continue
                handler = RunpodProviderHandler(provider_id, api_key, user_id=owner_user_id, provider_config=provider_config)
                await handler.poll_idle_shutdown()
        except Exception:
            logger.exception("RunPod idle shutdown loop iteration failed")
        await asyncio.sleep(max(poll_interval_seconds, 1.0))
