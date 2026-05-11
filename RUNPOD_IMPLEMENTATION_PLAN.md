RunPod implementation recovery plan for next session.

Goal
- Add a new provider type `runpod`
- Support multiple RunPod accounts by allowing multiple AISBF providers of type `runpod`
- Support two modes:
  - pod-backed/serverless-backed wrapper provider with one wrapper mode per provider: `openai`, `coderai`, or `ollama`
  - `runpod_public` provider represented as one AISBF provider with many discovered models/endpoints
- Auto-start stopped pods on request and wait until ready
- Cache pod/endpoint status in DB/cache so behavior is consistent across multiple AISBF instances
- Stop idle pods after configurable inactivity
- Allow serverless endpoint template usage as an alternative to pod-backed mode

Product decisions already made
- Scope: full lifecycle now
- Wrapper mode:
  - pod-backed `runpod` providers store one wrapper mode per provider
  - `runpod_public` auto-detects protocol per discovered model, with optional manual override per model
- Cold start behavior: auto start + wait
- `runpod_public` shape: one provider, many discovered models
- Management API preference: use the most recent/current supported RunPod management API surface between GraphQL and REST/OpenAPI
- Do not hardcode GraphQL if REST/OpenAPI is newer

Critical first step next session
- Verify which RunPod management API is the current supported one:
  - inspect current REST/OpenAPI docs/spec
  - inspect current GraphQL docs/spec
  - use whichever is the newer/current supported API surface
- Then map exact operations for:
  - pod status/start/stop
  - template lookup/use
  - endpoint discovery
  - serverless endpoint creation/use
  - public endpoint metadata and request format

Docs already identified
- `https://docs.runpod.io/api-reference/overview`
- `https://docs.runpod.io/llms.txt`
- `https://docs.runpod.io/public-endpoints/requests`
- `https://rest.runpod.io/v1/openapi.json`

Implementation map in AISBF
- `aisbf/config.py`
  - extend `ProviderConfig` with `runpod_config: Optional[Dict] = None`
- `aisbf/providers/__init__.py`
  - register new provider type `runpod`
- new file `aisbf/providers/runpod.py`
  - main handler/orchestrator
- `templates/dashboard/providers.html`
  - add `runpod` provider type option and config UI
- `aisbf/routes/dashboard/providers.py`
  - add any RunPod-specific dashboard actions/status endpoints if needed
- `aisbf/app/model_cache.py`
  - integrate caching/refresh for `runpod_public` discovered models
- `aisbf/database.py`
  - add persistent lifecycle/runtime state for runpod providers

Planned `runpod_config` structure
Example target shape:

```json
{
  "mode": "pod",
  "wrapper_mode": "openai",
  "account_name": "personal-runpod",
  "management_api": "auto",
  "idle_shutdown_ms": 900000,
  "startup_poll_interval_ms": 3000,
  "startup_timeout_ms": 300000,
  "pod_id": "abc123",
  "template_id": "tmpl_xyz",
  "endpoint_id": "",
  "serverless_template_id": "",
  "public_endpoint_protocol_default": "auto",
  "public_models": {
    "model-slug": {
      "protocol": "openai",
      "capabilities": ["chat", "vision"]
    }
  }
}
```

Modes
- `pod`
- `serverless_template`
- `public`

Wrapper modes for non-public
- `openai`
- `ollama`
- `coderai`

Representation rules
- Non-public runpod providers:
  - one wrapper mode per provider
  - lifecycle managed by AISBF
- `runpod_public`:
  - one provider with many discovered models/endpoints
  - protocol auto-detected per model
  - optional manual override per model in config

Architecture to implement
1. `RunpodProviderHandler` as orchestrator
- It should handle lifecycle and dispatch, not just protocol forwarding
- Responsibilities:
  - load `runpod_config`
  - ensure pod/endpoint is ready before forwarding requests
  - cache status/discovery
  - delegate to existing protocol behavior

2. Delegation model
- For pod/serverless-backed providers:
  - once ready, speak protocol based on provider-level `wrapper_mode`
  - delegate internally to existing handlers:
    - `OpenAIProviderHandler`
    - `OllamaProviderHandler`
    - `CoderAIProviderHandler`
- For `runpod_public`:
  - discover public models/endpoints
  - resolve protocol per model
  - dispatch request using model-specific protocol behavior

3. Readiness lifecycle
- On request for pod-backed provider:
  - read cached status from DB/cache
  - if running and endpoint known, reuse
  - if stopped, start pod
  - poll until ready or timeout
  - persist status/ready endpoint back to DB/cache
- On request for serverless-template mode:
  - resolve or create usable endpoint from template as configured
  - cache endpoint metadata

4. Idle shutdown
- Store persistent last-used timestamps and runtime state in DB
- Add background loop that:
  - scans runpod provider state
  - if `now - last_used_at > idle_shutdown_ms` and provider is pod-backed and running
  - stop the pod
  - persist updated status

Database work needed
Add a new table in `aisbf/database.py`, e.g. `runpod_provider_state` with fields like:
- `provider_scope` (`global` / `user`)
- `owner_user_id`
- `provider_id`
- `mode`
- `wrapper_mode`
- `resource_id`
- `resource_kind` (`pod`, `endpoint`, `public`)
- `status`
- `endpoint_url`
- `public_catalog_json`
- `metadata`
- `last_used_at`
- `last_status_sync_at`
- `updated_at`
- unique on `(owner_user_id, provider_id)`

Add helpers:
- `get_runpod_provider_state(...)`
- `save_runpod_provider_state(...)`
- `touch_runpod_provider_state(...)`
- `list_runpod_provider_states(...)`

This DB-backed state is required for:
- round-robin multi-instance consistency
- idle shutdown scanning
- readiness caching
- public endpoint discovery caching

Cache/model discovery work
For `runpod_public` in `aisbf/app/model_cache.py`:
- cache discovered public models
- refresh periodically or on-demand
- store enough metadata per model:
  - model id/slug
  - protocol
  - capabilities
  - route base
  - request mode (`runsync`, `run`, `status`)
  - parameter/schema hints if available

Dashboard work
In `templates/dashboard/providers.html`:
- add provider type option: `runpod`
- add description text for `runpod`
- add UI section for `runpod_config`
- likely fields:
  - account label
  - mode (`pod`, `serverless_template`, `public`)
  - wrapper mode (`openai`, `ollama`, `coderai`) for non-public
  - API key field if not top-level
  - pod id
  - template id
  - endpoint id
  - serverless template id
  - idle shutdown ms
  - startup timeout ms
  - poll interval ms
  - auto-discovery toggle
  - per-model protocol override editor for public models

Potential server-side additions in `aisbf/routes/dashboard/providers.py`
- refresh RunPod public discovery
- show RunPod lifecycle status
- optional manual start/stop actions later if useful

Protocol behavior plan
1. Pod-backed `openai`
- after pod ready, delegate to OpenAI-compatible request/model list flow
- endpoint likely `/v1/...`

2. Pod-backed `ollama`
- after pod ready, delegate to Ollama flow
- endpoint likely `/api/...`

3. Pod-backed `coderai`
- after pod ready, delegate to CoderAI flow
- endpoint/path depends on service running in the pod

4. `runpod_public`
- public endpoints are not one uniform protocol
- implement model-level protocol metadata
- auto-detect protocol from endpoint metadata/docs/naming where possible
- allow manual override per model
- request path likely uses `https://api.runpod.ai/v2/<endpoint>/...`
- do not fake this part; implement from verified docs only

Suggested next-session execution order
1. Verify RunPod API contract and choose the current supported management API surface
2. Add `runpod_config` to `aisbf/config.py`
3. Add DB-backed `runpod_provider_state` table and helpers in `aisbf/database.py`
4. Create `aisbf/providers/runpod.py`
5. Register `runpod` in `aisbf/providers/__init__.py`
6. Add idle shutdown background task in startup/background task area
7. Add dashboard UI/config save support in `templates/dashboard/providers.html`
8. Hook `runpod_public` discovery into `aisbf/app/model_cache.py`
9. Validate with compile/tests

Recommended tests to add
- config validation for `runpod_config`
- DB CRUD for `runpod_provider_state`
- lifecycle tests:
  - stopped pod -> start called
  - running pod -> no start
  - idle timeout -> stop called
- public model discovery parsing
- protocol selection:
  - public model auto-detect
  - public model manual override
- delegation tests:
  - `wrapper_mode=openai`
  - `wrapper_mode=ollama`
  - `wrapper_mode=coderai`

Files already reviewed for this work
- `aisbf/config.py`
- `aisbf/providers/__init__.py`
- `aisbf/providers/openai.py`
- `aisbf/providers/ollama.py`
- `aisbf/providers/coderai.py`
- `aisbf/providers/base.py`
- `aisbf/app/model_cache.py`
- `aisbf/routes/dashboard/providers.py`
- `templates/dashboard/providers.html`

Suggested next-session prompt
"Implement full RunPod provider support for AISBF. First determine whether RunPod REST/OpenAPI or GraphQL is the newer/current supported management API, then use that API for pod lifecycle, endpoint discovery, and template/serverless management. Add a new `runpod` provider type with `runpod_config`, DB-backed lifecycle state, auto-start/wait, idle shutdown, wrapper-mode delegation (`openai`, `ollama`, `coderai`), and `runpod_public` as one provider with many discovered models and per-model protocol auto-detect/manual override. Preserve multi-instance consistency by storing lifecycle state in the database."
