# Dashboard Studio Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the standalone Studio app into the AISBF dashboard as a role-aware `Studio` page with dashboard-native theming, unified model selection across providers/rotations/autoselects, and best-effort capability inference for autodetected and manually configured models.

**Architecture:** Add a new dashboard Studio route and template that reuse the existing dashboard shell while introducing a workspace-oriented layout. Back the page with a dedicated Studio catalog service that resolves visible resources for the current principal, normalizes provider/rotation/autoselect entries into a stable frontend payload, and merges explicit plus inferred capabilities. Extend existing provider/model save flows so capability inference runs whenever models are autodetected or edited.

**Tech Stack:** FastAPI, Jinja2 templates, existing dashboard JS/CSS, Python service helpers, pytest

---

## File Structure

**Routing and page rendering:**
- Modify: `aisbf/routes/dashboard/providers.py` - add `/dashboard/studio` page route plus Studio JSON endpoints near other dashboard routes.
- Modify: `main.py` - ensure the updated dashboard router is still initialized; verify no extra registration is needed.

**Studio data/service layer:**
- Create: `aisbf/studio.py` - shared helpers for capability inference, catalog normalization, scope filtering, and diagnostics formatting.
- Modify: `aisbf/handlers.py` - reuse or extract existing `_detect_capabilities()` logic so Studio and API model-list flows share one inference vocabulary instead of diverging.
- Modify: `aisbf/config.py` - extend `ProviderModelConfig` to store Studio-related capability metadata and optional inference metadata cleanly.

**Persistence and config integration:**
- Modify: `aisbf/database.py` - add helper methods for normalized user-owned resource loading if needed by Studio catalog resolution, without changing current storage model.
- Modify: `aisbf/routes/dashboard/providers.py` - hook capability inference into manual model save and autodetect save flows.
- Modify: `aisbf/routes/dashboard/settings.py` - if existing save endpoints are reused for user resource writes, route capability refresh through the shared Studio helper.

**Templates and frontend assets:**
- Modify: `templates/base.html` - add `Studio` navigation link for both admin and users; allow a full-width/Studio page body mode.
- Create: `templates/dashboard/studio.html` - dashboard-native Studio page bootstrapped with serialized catalog JSON and theme-aware workspace markup.
- Create: `static/dashboard/studio.css` - Studio-specific styles remapped onto dashboard CSS variables.
- Create: `static/dashboard/studio.js` - client bootstrap, target switching, capability-state rendering, diagnostics display, and future-ready data wiring.
- Modify: `static/i18n/en.json` - add `nav.studio` and Studio UI strings used by the page.

**Tests:**
- Create: `tests/test_studio.py` - unit tests for catalog normalization, scope filtering, and capability inference.
- Modify: `tests/providers/test_claude_provider.py` or create a new dashboard-focused test module only if provider autodetect persistence needs route-level regression coverage.
- Create: `tests/routes/test_dashboard_studio.py` - route tests for admin/user Studio page and JSON catalog behavior.

---

### Task 1: Build the shared Studio catalog and capability service

**Files:**
- Create: `aisbf/studio.py`
- Modify: `aisbf/handlers.py:1671-1804`
- Test: `tests/test_studio.py`

- [ ] **Step 1: Write the failing catalog normalization and capability inference tests**

Create `tests/test_studio.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_studio.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'aisbf.studio'`

- [ ] **Step 3: Write the minimal shared Studio service implementation**

Create `aisbf/studio.py`:

```python
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
    "a2t": "audio_input",
    "transcription": "transcription",
    "tts": "speech_generation",
    "t2a": "audio_generation",
    "a2a": "audio_generation",
    "embeddings": "embeddings",
    "function_calling": "tool_use",
    "reasoning": "reasoning",
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
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def _normalize_existing_capabilities(values: Optional[Iterable[str]]) -> List[str]:
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
    explicit = _normalize_existing_capabilities(explicit_capabilities)
    if explicit:
        return StudioCapabilityResult(capabilities=explicit, source="explicit", unknown=False, notes=[])

    capabilities = _normalize_existing_capabilities((provider_metadata or {}).get("capabilities"))
    source = "provider_metadata" if capabilities else "heuristic"
    notes: List[str] = []

    name = (model_name or "").lower()
    architecture = architecture or {}
    input_modalities = architecture.get("input_modalities") or []
    output_modalities = architecture.get("output_modalities") or []

    if not capabilities:
        if any(token in name for token in ["gpt", "claude", "gemini", "llama", "mixtral"]):
            capabilities.append("chat")
        if any(token in name for token in ["vision", "gpt-4o", "claude-3", "gemini-1.5", "gemini-2"]):
            capabilities.append("vision")
        if any(token in name for token in ["dall-e", "dalle", "imagen", "flux", "sdxl", "stable-diffusion"]):
            capabilities.append("image_generation")
        if any(token in name for token in ["edit", "img2img", "inpaint", "controlnet"]):
            capabilities.append("image_edit")
        if any(token in name for token in ["sora", "runway", "pika"]):
            capabilities.append("video_generation")
        if any(token in name for token in ["whisper", "transcribe", "stt"]):
            capabilities.extend(["audio_input", "transcription"])
        if any(token in name for token in ["tts", "bark", "eleven", "speech"]):
            capabilities.append("speech_generation")
        if any(token in name for token in ["audiogen", "musicgen"]):
            capabilities.append("audio_generation")
        if any(token in name for token in ["embed", "embedding", "bge", "e5"]):
            capabilities.append("embeddings")

    if "image" in input_modalities and "vision" not in capabilities:
        capabilities.append("vision")
    if "audio" in input_modalities and "audio_input" not in capabilities:
        capabilities.append("audio_input")
    if "text" in output_modalities and "transcription" not in capabilities and "audio" in input_modalities:
        capabilities.append("transcription")
    if "audio" in output_modalities and "speech_generation" not in capabilities:
        capabilities.append("speech_generation")

    capabilities = _dedupe(capabilities)
    unknown = not capabilities
    if unknown:
        notes.append(f"No confident Studio capabilities inferred for {provider_type}:{model_name}")
        capabilities = ["chat"] if provider_type in {"openai", "anthropic", "google", "kilo", "claude", "qwen", "codex"} else []
        source = "fallback"
        unknown = not capabilities

    return StudioCapabilityResult(
        capabilities=capabilities,
        source=source,
        unknown=unknown,
        notes=notes,
    )


def merge_capabilities(
    base_capabilities: Iterable[str],
    override_capabilities: Optional[Iterable[str]] = None,
    support_mode: str = "override",
) -> StudioCapabilityMergeResult:
    base = _normalize_existing_capabilities(base_capabilities)
    override = _normalize_existing_capabilities(override_capabilities)
    if not override:
        return StudioCapabilityMergeResult(capabilities=base, partial_capabilities=[])
    if support_mode == "intersection":
        final = [item for item in base if item in override]
        partial = [item for item in base if item not in final]
        return StudioCapabilityMergeResult(capabilities=final, partial_capabilities=partial)
    return StudioCapabilityMergeResult(capabilities=override, partial_capabilities=[])


def build_catalog_entry(
    scope: str,
    owner_id: Optional[int],
    kind: str,
    source_id: str,
    target_id: str,
    label: str,
    description: Optional[str],
    capabilities: Iterable[str],
    availability_state: str,
    availability_reason: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    prefix_map = {
        "provider_model": "provider",
        "rotation": "rotation",
        "autoselect": "autoselect",
    }
    prefix = prefix_map[kind]
    entry_id = f"{prefix}/{source_id}/{target_id}" if kind == "provider_model" else f"{prefix}/{target_id}"
    return {
        "id": entry_id,
        "kind": kind,
        "owner_scope": scope,
        "owner_id": owner_id,
        "source_id": source_id,
        "target_id": target_id,
        "label": label,
        "description": description,
        "capabilities": _normalize_existing_capabilities(capabilities),
        "availability_state": availability_state,
        "availability_reason": availability_reason,
        "metadata": metadata or {},
    }
```

- [ ] **Step 4: Bridge existing handler capability detection through the shared helper**

Replace the body of `_detect_capabilities()` in `aisbf/handlers.py` with:

```python
def _detect_capabilities(self, model_name: str, provider_type: str) -> List[str]:
    """Auto-detect model capabilities based on model name and provider type."""
    from aisbf.studio import infer_model_capabilities

    result = infer_model_capabilities(
        model_name=model_name,
        provider_type=provider_type,
        explicit_capabilities=None,
        architecture=None,
        provider_metadata=None,
    )
    return result.capabilities
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_studio.py -v`

Expected: PASS for all four tests

- [ ] **Step 6: Commit**

```bash
git add aisbf/studio.py aisbf/handlers.py tests/test_studio.py
git commit -m "feat(studio): add shared capability inference service"
```

---

### Task 2: Add a dashboard-native Studio page and navigation entry

**Files:**
- Modify: `templates/base.html:827-899`
- Create: `templates/dashboard/studio.html`
- Create: `static/dashboard/studio.css`
- Create: `static/dashboard/studio.js`
- Modify: `static/i18n/en.json`
- Test: `tests/routes/test_dashboard_studio.py`

- [ ] **Step 1: Write the failing dashboard route and nav tests**

Create `tests/routes/test_dashboard_studio.py`:

```python
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_dashboard_nav_includes_studio_for_logged_in_user(monkeypatch):
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["user_id"] = 7
        session["role"] = "user"
        session["username"] = "alice"

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert 'data-i18n="nav.studio"' in response.text


def test_dashboard_studio_requires_auth():
    response = client.get("/dashboard/studio", follow_redirects=False)

    assert response.status_code in {302, 303}


def test_dashboard_studio_page_renders_for_user_session(monkeypatch):
    with client.session_transaction() as session:
        session["logged_in"] = True
        session["user_id"] = 7
        session["role"] = "user"
        session["username"] = "alice"

    response = client.get("/dashboard/studio")

    assert response.status_code == 200
    assert "studio-app" in response.text
    assert "studio-bootstrap" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/routes/test_dashboard_studio.py -v`

Expected: FAIL because `/dashboard/studio` does not exist and the nav does not contain `nav.studio`

- [ ] **Step 3: Add the Studio nav entry and full-width body hook**

In `templates/base.html`, update the nav block so it includes:

```html
<a href="{{ url_for(request, '/dashboard/studio') }}" {% if '/studio' in request.path %}class="active"{% endif %} data-i18n="nav.studio">Studio</a>
```

Place it after the Autoselect link. Then change the page wrapper near the content block to:

```html
<div class="container {% if studio_full_width|default(false) %}container-studio{% endif %}">
    <div class="content {% if studio_full_width|default(false) %}content-studio{% endif %}">
        {% block content %}{% endblock %}
    </div>
</div>
```

Add these CSS rules inside the main `<style>` block:

```css
.container-studio { max-width: 100%; padding-left: 12px; padding-right: 12px; }
.content-studio { padding: 0; overflow: hidden; min-height: calc(100vh - 220px); }
@media (max-width: 768px) {
    .container-studio { padding-left: 6px; padding-right: 6px; }
    .content-studio { min-height: calc(100vh - 180px); }
}
```

- [ ] **Step 4: Add the dashboard Studio template and themed assets**

Create `templates/dashboard/studio.html`:

```html
{% extends "base.html" %}

{% block title %}Studio - AISBF Dashboard{% endblock %}

{% block content %}
<link rel="stylesheet" href="{{ url_for(request, '/static/dashboard/studio.css') }}">
<div id="studio-app" class="studio-shell">
    <script id="studio-bootstrap" type="application/json">{{ studio_bootstrap_json|safe }}</script>
    <aside class="studio-sidebar">
        <div class="studio-sidebar-head">
            <h2 data-i18n="studio.title">Studio</h2>
            <p data-i18n="studio.subtitle">Unified workspace for chat, multimodal tools, and pipelines.</p>
        </div>
        <div class="studio-targets" id="studio-targets"></div>
    </aside>
    <section class="studio-main">
        <header class="studio-toolbar">
            <div>
                <h3 id="studio-current-title">—</h3>
                <p id="studio-current-description" class="studio-muted"></p>
            </div>
            <div class="studio-state" id="studio-state"></div>
        </header>
        <nav class="studio-capabilities" id="studio-capabilities"></nav>
        <section class="studio-diagnostics" id="studio-diagnostics"></section>
        <section class="studio-workspace">
            <div class="studio-placeholder" data-i18n="studio.placeholder">
                Select a target to inspect capabilities and prepare future Studio execution.
            </div>
        </section>
    </section>
</div>
<script src="{{ url_for(request, '/static/dashboard/studio.js') }}"></script>
{% endblock %}
```

Create `static/dashboard/studio.css`:

```css
.studio-shell {
    display: grid;
    grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
    min-height: calc(100vh - 230px);
    background: linear-gradient(180deg, var(--bg-panel) 0%, var(--bg-page) 100%);
}
.studio-sidebar {
    border-right: 1px solid var(--color-border);
    background: color-mix(in srgb, var(--bg-panel) 85%, var(--bg-accent) 15%);
    padding: 18px;
}
.studio-sidebar-head h2 { font-size: 1.3rem; margin-bottom: 6px; }
.studio-sidebar-head p,
.studio-muted { color: var(--color-muted); }
.studio-targets { display: flex; flex-direction: column; gap: 10px; margin-top: 18px; }
.studio-target {
    border: 1px solid var(--color-border);
    background: var(--bg-page);
    border-radius: 10px;
    padding: 12px;
    cursor: pointer;
}
.studio-target.active { border-color: var(--color-primary); box-shadow: 0 0 0 1px var(--color-primary) inset; }
.studio-main { display: flex; flex-direction: column; min-width: 0; }
.studio-toolbar, .studio-capabilities, .studio-diagnostics, .studio-workspace { padding: 18px 22px; }
.studio-toolbar { display: flex; justify-content: space-between; gap: 16px; border-bottom: 1px solid var(--color-border); }
.studio-capabilities { display: flex; flex-wrap: wrap; gap: 10px; border-bottom: 1px solid var(--color-border); }
.studio-chip {
    padding: 6px 10px;
    border-radius: 999px;
    border: 1px solid var(--color-border);
    background: var(--bg-accent);
    color: var(--color-text);
    font-size: 0.82rem;
    font-weight: 600;
}
.studio-chip.partial { border-color: #d68910; color: #f0c060; }
.studio-chip.unavailable { border-color: #c0392b; color: #f3b2b2; }
.studio-diagnostics { display: flex; flex-direction: column; gap: 12px; border-bottom: 1px solid var(--color-border); }
.studio-note {
    border: 1px solid var(--color-border);
    background: var(--bg-page);
    border-radius: 10px;
    padding: 12px 14px;
}
.studio-workspace { flex: 1; display: flex; }
.studio-placeholder {
    width: 100%; min-height: 260px; border: 1px dashed var(--color-border);
    border-radius: 12px; display: flex; align-items: center; justify-content: center;
    color: var(--color-muted); background: color-mix(in srgb, var(--bg-page) 85%, var(--bg-accent) 15%);
}
@media (max-width: 900px) {
    .studio-shell { grid-template-columns: 1fr; }
    .studio-sidebar { border-right: none; border-bottom: 1px solid var(--color-border); }
}
```

Create `static/dashboard/studio.js`:

```javascript
(function () {
  const bootstrapNode = document.getElementById('studio-bootstrap');
  if (!bootstrapNode) return;

  const payload = JSON.parse(bootstrapNode.textContent || '{}');
  const targets = payload.targets || [];
  const targetList = document.getElementById('studio-targets');
  const capabilityBar = document.getElementById('studio-capabilities');
  const diagnostics = document.getElementById('studio-diagnostics');
  const title = document.getElementById('studio-current-title');
  const description = document.getElementById('studio-current-description');
  const state = document.getElementById('studio-state');

  function renderTarget(entry, active) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'studio-target' + (active ? ' active' : '');
    button.innerHTML = `
      <div><strong>${entry.label}</strong></div>
      <div class="studio-muted">${entry.kind} · ${entry.owner_scope}</div>
      <div class="studio-muted">${entry.description || ''}</div>
    `;
    button.addEventListener('click', () => selectEntry(entry.id));
    return button;
  }

  function renderCapabilities(entry) {
    capabilityBar.innerHTML = '';
    const supported = entry.capabilities || [];
    const partial = (entry.partial_capabilities || []);
    if (!supported.length && !partial.length) {
      capabilityBar.innerHTML = '<span class="studio-muted">No Studio capabilities detected yet.</span>';
      return;
    }
    supported.forEach((capability) => {
      const chip = document.createElement('span');
      chip.className = 'studio-chip';
      chip.textContent = capability;
      capabilityBar.appendChild(chip);
    });
    partial.forEach((capability) => {
      const chip = document.createElement('span');
      chip.className = 'studio-chip partial';
      chip.textContent = capability + ' (partial)';
      capabilityBar.appendChild(chip);
    });
  }

  function renderDiagnostics(entry) {
    diagnostics.innerHTML = '';
    const messages = [];
    if (entry.availability_reason) messages.push(entry.availability_reason);
    (entry.notes || []).forEach((note) => messages.push(note));
    if (!messages.length) {
      diagnostics.innerHTML = '<div class="studio-note">Catalog entry is ready for Studio use.</div>';
      return;
    }
    messages.forEach((message) => {
      const note = document.createElement('div');
      note.className = 'studio-note';
      note.textContent = message;
      diagnostics.appendChild(note);
    });
  }

  function selectEntry(entryId) {
    const current = targets.find((entry) => entry.id === entryId) || targets[0];
    if (!current) return;
    title.textContent = current.label;
    description.textContent = current.description || '';
    state.textContent = current.availability_state || 'unknown';
    renderCapabilities(current);
    renderDiagnostics(current);
    targetList.innerHTML = '';
    targets.forEach((entry) => targetList.appendChild(renderTarget(entry, entry.id === current.id)));
  }

  if (!targets.length) {
    targetList.innerHTML = '<div class="studio-note">No Studio targets are available yet.</div>';
    return;
  }

  selectEntry(targets[0].id);
})();
```

- [ ] **Step 5: Add English translations for Studio strings**

In `static/i18n/en.json`, extend the root object with:

```json
"nav": {
  "studio": "Studio"
},
"studio": {
  "title": "Studio",
  "subtitle": "Unified workspace for chat, multimodal tools, and pipelines.",
  "placeholder": "Select a target to inspect capabilities and prepare future Studio execution."
}
```

Merge these keys into the existing `nav` object rather than duplicating it.

- [ ] **Step 6: Run tests to confirm the nav and page tests still fail only on missing backend route**

Run: `pytest tests/routes/test_dashboard_studio.py -v`

Expected: the nav assertion passes, but `/dashboard/studio` still fails until the backend route is added in the next task

- [ ] **Step 7: Commit**

```bash
git add templates/base.html templates/dashboard/studio.html static/dashboard/studio.css static/dashboard/studio.js static/i18n/en.json tests/routes/test_dashboard_studio.py
git commit -m "feat(studio): add dashboard studio UI shell"
```

---

### Task 3: Add Studio route handlers and role-aware catalog resolution

**Files:**
- Modify: `aisbf/routes/dashboard/providers.py`
- Modify: `aisbf/studio.py`
- Modify: `tests/routes/test_dashboard_studio.py`
- Test: `tests/routes/test_dashboard_studio.py`

- [ ] **Step 1: Extend tests with admin/user catalog expectations**

Append to `tests/routes/test_dashboard_studio.py`:

```python
def test_dashboard_studio_catalog_returns_only_user_owned_targets(monkeypatch):
    from aisbf.routes.dashboard import providers as providers_module

    def fake_catalog(scope, user_id, config, db):
        assert scope == "user"
        assert user_id == 7
        return [{"id": "provider/custom/gpt-4o", "owner_scope": "user", "label": "GPT-4o", "capabilities": ["chat"]}]

    monkeypatch.setattr(providers_module, "build_studio_catalog", fake_catalog)

    with client.session_transaction() as session:
        session["logged_in"] = True
        session["user_id"] = 7
        session["role"] = "user"
        session["username"] = "alice"

    response = client.get("/dashboard/studio/catalog")

    assert response.status_code == 200
    assert response.json()["targets"][0]["owner_scope"] == "user"


def test_dashboard_studio_catalog_returns_global_targets_for_admin(monkeypatch):
    from aisbf.routes.dashboard import providers as providers_module

    def fake_catalog(scope, user_id, config, db):
        assert scope == "global"
        assert user_id is None
        return [{"id": "provider/openai/gpt-4o", "owner_scope": "global", "label": "GPT-4o", "capabilities": ["chat"]}]

    monkeypatch.setattr(providers_module, "build_studio_catalog", fake_catalog)

    with client.session_transaction() as session:
        session["logged_in"] = True
        session["role"] = "admin"
        session["username"] = "root"

    response = client.get("/dashboard/studio/catalog")

    assert response.status_code == 200
    assert response.json()["targets"][0]["owner_scope"] == "global"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/routes/test_dashboard_studio.py -v`

Expected: FAIL because `build_studio_catalog` and both Studio endpoints do not exist yet

- [ ] **Step 3: Implement catalog builders in `aisbf/studio.py`**

Append to `aisbf/studio.py`:

```python
def _provider_metadata_dict(provider_model: Optional[Dict[str, Any]], fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = dict(fallback or {})
    if provider_model:
        for key in [
            "context_length",
            "pricing",
            "supported_parameters",
            "default_parameters",
            "privacy",
            "nsfw",
            "studio_capability_source",
            "studio_capability_notes",
        ]:
            if provider_model.get(key) is not None:
                data[key] = provider_model.get(key)
    return data


def build_studio_catalog(scope: str, user_id: Optional[int], config: Any, db: Any) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []

    if scope == "global":
        providers = {provider_id: provider.model_dump() for provider_id, provider in config.providers.items()}
        rotations = {rotation_id: rotation.model_dump() for rotation_id, rotation in config.rotations.items()}
        autoselects = {autoselect_id: autoselect.model_dump() for autoselect_id, autoselect in config.autoselect.items()}
    else:
        providers = {row["provider_id"]: row["config"] for row in db.get_user_providers(user_id)}
        rotations = {row["rotation_id"]: row["config"] for row in db.get_user_rotations(user_id)}
        autoselects = {row["autoselect_id"]: row["config"] for row in db.get_user_autoselects(user_id)}

    for provider_id, provider in providers.items():
        for model in provider.get("models") or []:
            result = infer_model_capabilities(
                model_name=model.get("name", ""),
                provider_type=provider.get("type", "openai"),
                explicit_capabilities=model.get("capabilities"),
                architecture=model.get("architecture"),
                provider_metadata=model,
            )
            targets.append(
                build_catalog_entry(
                    scope=scope,
                    owner_id=user_id,
                    kind="provider_model",
                    source_id=provider_id,
                    target_id=model.get("name", "unknown-model"),
                    label=model.get("name", "unknown-model"),
                    description=model.get("description") or provider.get("name") or provider_id,
                    capabilities=result.capabilities,
                    availability_state="ready" if result.capabilities else "partial",
                    availability_reason=None if result.capabilities else "Capabilities still need manual configuration.",
                    metadata=_provider_metadata_dict(model, {"provider_type": provider.get("type")}),
                )
            )
            targets[-1]["notes"] = result.notes

    for rotation_id, rotation in rotations.items():
        merged = merge_capabilities(rotation.get("capabilities") or ["chat"], rotation.get("capabilities"), support_mode="override")
        targets.append(
            build_catalog_entry(
                scope=scope,
                owner_id=user_id,
                kind="rotation",
                source_id=rotation_id,
                target_id=rotation_id,
                label=rotation.get("model_name") or rotation_id,
                description=rotation.get("description") or "Rotation target",
                capabilities=merged.capabilities,
                availability_state="ready" if merged.capabilities else "partial",
                availability_reason=None,
                metadata={
                    "privacy": rotation.get("privacy"),
                    "nsfw": rotation.get("nsfw"),
                    "context_length": rotation.get("context_length"),
                },
            )
        )
        targets[-1]["partial_capabilities"] = merged.partial_capabilities
        targets[-1]["notes"] = []

    for autoselect_id, autoselect in autoselects.items():
        merged = merge_capabilities(autoselect.get("capabilities") or ["chat"], autoselect.get("capabilities"), support_mode="override")
        targets.append(
            build_catalog_entry(
                scope=scope,
                owner_id=user_id,
                kind="autoselect",
                source_id=autoselect_id,
                target_id=autoselect_id,
                label=autoselect.get("model_name") or autoselect_id,
                description=autoselect.get("description") or "Autoselect target",
                capabilities=merged.capabilities,
                availability_state="ready" if merged.capabilities else "partial",
                availability_reason=None,
                metadata={
                    "privacy": autoselect.get("privacy"),
                    "nsfw": autoselect.get("nsfw"),
                    "context_length": autoselect.get("context_length"),
                    "fallback": autoselect.get("fallback"),
                },
            )
        )
        targets[-1]["partial_capabilities"] = merged.partial_capabilities
        targets[-1]["notes"] = []

    return sorted(targets, key=lambda item: (item["kind"], item["label"].lower()))
```

- [ ] **Step 4: Add the Studio page and catalog routes**

In `aisbf/routes/dashboard/providers.py`, add imports near the top:

```python
from aisbf.studio import build_studio_catalog
```

Then add these route handlers after `dashboard_index`:

```python
@router.get("/dashboard/studio", response_class=HTMLResponse)
async def dashboard_studio(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get("user_id")
    scope = "global" if request.session.get("role") == "admin" and not user_id else "user"
    targets = build_studio_catalog(scope=scope, user_id=user_id, config=_config, db=db)
    bootstrap = {
        "scope": scope,
        "targets": targets,
    }
    return _templates.TemplateResponse(
        request=request,
        name="dashboard/studio.html",
        context={
            "request": request,
            "session": request.session,
            "studio_full_width": True,
            "studio_bootstrap_json": json.dumps(bootstrap),
        },
    )


@router.get("/dashboard/studio/catalog")
async def dashboard_studio_catalog(request: Request):
    auth_check = require_dashboard_auth(request)
    if auth_check:
        return auth_check

    db = DatabaseRegistry.get_config_database()
    user_id = request.session.get("user_id")
    scope = "global" if request.session.get("role") == "admin" and not user_id else "user"
    targets = build_studio_catalog(scope=scope, user_id=user_id, config=_config, db=db)
    return JSONResponse({"scope": scope, "targets": targets})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/routes/test_dashboard_studio.py -v`

Expected: PASS for auth redirect, nav presence, Studio page render, and admin/user catalog scope tests

- [ ] **Step 6: Commit**

```bash
git add aisbf/routes/dashboard/providers.py aisbf/studio.py tests/routes/test_dashboard_studio.py
git commit -m "feat(studio): add dashboard studio routes and catalog"
```

---

### Task 4: Persist Studio capability metadata for autodetected and manual provider models

**Files:**
- Modify: `aisbf/config.py`
- Modify: `aisbf/routes/dashboard/providers.py`
- Modify: `tests/test_studio.py`
- Test: `tests/test_studio.py`

- [ ] **Step 1: Write the failing persistence tests for inferred Studio metadata**

Append to `tests/test_studio.py`:

```python
from aisbf.studio import apply_inferred_capabilities_to_model


def test_apply_inferred_capabilities_to_model_sets_missing_fields_only():
    model = {"name": "gpt-4o", "description": "General model"}

    updated = apply_inferred_capabilities_to_model(model, provider_type="openai")

    assert updated["capabilities"] == ["chat", "vision"]
    assert updated["studio_capability_source"] in {"heuristic", "fallback", "provider_metadata"}
    assert "studio_capability_notes" in updated


def test_apply_inferred_capabilities_to_model_preserves_explicit_capabilities():
    model = {"name": "gpt-4o", "capabilities": ["chat"]}

    updated = apply_inferred_capabilities_to_model(model, provider_type="openai")

    assert updated["capabilities"] == ["chat"]
    assert updated["studio_capability_source"] == "explicit"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_studio.py -v`

Expected: FAIL with `ImportError` for `apply_inferred_capabilities_to_model`

- [ ] **Step 3: Extend the provider model config schema for Studio metadata**

In `aisbf/config.py`, add these fields to `ProviderModelConfig` after `enable_response_cache`:

```python
    studio_capability_source: Optional[str] = None
    studio_capability_notes: Optional[List[str]] = None
```

- [ ] **Step 4: Add a helper that stamps inferred capabilities onto model dictionaries**

Append to `aisbf/studio.py`:

```python
def apply_inferred_capabilities_to_model(model: Dict[str, Any], provider_type: str) -> Dict[str, Any]:
    updated = dict(model)
    result = infer_model_capabilities(
        model_name=updated.get("name", ""),
        provider_type=provider_type,
        explicit_capabilities=updated.get("capabilities"),
        architecture=updated.get("architecture"),
        provider_metadata=updated,
    )
    if not updated.get("capabilities"):
        updated["capabilities"] = result.capabilities
    updated["studio_capability_source"] = result.source
    updated["studio_capability_notes"] = result.notes
    return updated
```

- [ ] **Step 5: Run capability inference during provider model save/autodetect flows**

In `aisbf/routes/dashboard/providers.py`, add the import:

```python
from aisbf.studio import apply_inferred_capabilities_to_model, build_studio_catalog
```

Then, wherever provider models are populated from autodetect results before saving, transform them with:

```python
normalized_models = [
    apply_inferred_capabilities_to_model(model, provider.get("type", "openai"))
    for model in detected_models
]
provider["models"] = normalized_models
```

And wherever manually submitted models are assembled from form/JSON payloads before writing config, transform each one with:

```python
provider_models = [
    apply_inferred_capabilities_to_model(model, provider_data.get("type", "openai"))
    for model in provider_models
]
```

If the file already uses a different variable name, preserve the local naming but apply the same transformation exactly once immediately before persistence.

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_studio.py -v`

Expected: PASS for all Studio unit tests, including the new persistence cases

- [ ] **Step 7: Commit**

```bash
git add aisbf/config.py aisbf/studio.py aisbf/routes/dashboard/providers.py tests/test_studio.py
git commit -m "feat(studio): persist inferred model capabilities"
```

---

### Task 5: Surface partial capability states for rotations and autoselects

**Files:**
- Modify: `aisbf/studio.py`
- Modify: `templates/dashboard/studio.html`
- Modify: `static/dashboard/studio.js`
- Modify: `tests/test_studio.py`
- Test: `tests/test_studio.py`

- [ ] **Step 1: Write the failing aggregate-capability tests**

Append to `tests/test_studio.py`:

```python
from aisbf.studio import derive_collection_capabilities


def test_derive_collection_capabilities_returns_intersection_and_partial_remainder():
    result = derive_collection_capabilities([
        ["chat", "vision", "image_generation"],
        ["chat", "vision"],
        ["chat", "vision", "audio_input"],
    ])

    assert result.capabilities == ["chat", "vision"]
    assert sorted(result.partial_capabilities) == ["audio_input", "image_generation"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_studio.py::test_derive_collection_capabilities_returns_intersection_and_partial_remainder -v`

Expected: FAIL with `ImportError` for `derive_collection_capabilities`

- [ ] **Step 3: Implement aggregate capability derivation and apply it to rotations/autoselects**

Append to `aisbf/studio.py`:

```python
@dataclass
class StudioAggregateCapabilityResult:
    capabilities: List[str]
    partial_capabilities: List[str]


def derive_collection_capabilities(capability_sets: Iterable[Iterable[str]]) -> StudioAggregateCapabilityResult:
    normalized = [_normalize_existing_capabilities(items) for items in capability_sets if items]
    if not normalized:
        return StudioAggregateCapabilityResult(capabilities=[], partial_capabilities=[])
    intersection = list(normalized[0])
    for values in normalized[1:]:
        intersection = [item for item in intersection if item in values]
    union = _dedupe(item for values in normalized for item in values)
    partial = [item for item in union if item not in intersection]
    return StudioAggregateCapabilityResult(capabilities=intersection, partial_capabilities=partial)
```

Then update `build_studio_catalog()` so rotation and autoselect entries use `derive_collection_capabilities()` when no explicit `capabilities` are set:

```python
provider_caps = [
    _normalize_existing_capabilities(model.get("capabilities"))
    for provider in providers.values()
    for model in provider.get("models") or []
]
aggregate = derive_collection_capabilities(provider_caps)
final_caps = _normalize_existing_capabilities(rotation.get("capabilities")) or aggregate.capabilities
partial_caps = aggregate.partial_capabilities if not rotation.get("capabilities") else []
```

Apply the same pattern to autoselects by mapping each `available_model` reference back to a provider-model capability list where possible, and defaulting to explicit autoselect capabilities when already present.

- [ ] **Step 4: Surface partial capability states in the Studio UI**

In `static/dashboard/studio.js`, ensure `partial_capabilities` render with `partial` chip styling and add availability note text when `availability_state === 'partial'`.

In `templates/dashboard/studio.html`, change the workspace placeholder block to:

```html
<div class="studio-placeholder" id="studio-placeholder" data-i18n="studio.placeholder">
    Select a target to inspect capabilities and prepare future Studio execution.
</div>
```

Then in `static/dashboard/studio.js`, add:

```javascript
const placeholder = document.getElementById('studio-placeholder');
if (placeholder && current.availability_state === 'partial') {
  placeholder.textContent = 'This target is only partially configured for Studio. Review diagnostics before use.';
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_studio.py -v`

Expected: PASS for aggregate capability inference and prior unit tests

- [ ] **Step 6: Commit**

```bash
git add aisbf/studio.py templates/dashboard/studio.html static/dashboard/studio.js tests/test_studio.py
git commit -m "feat(studio): expose partial capability states"
```

---

### Task 6: Verify end-to-end Studio integration and update project guidance if required

**Files:**
- Modify: `AI.PROMPT` (only if the new Studio integration materially changes project structure or key functionality)
- Test: `tests/test_studio.py`
- Test: `tests/routes/test_dashboard_studio.py`

- [ ] **Step 1: Check whether `AI.PROMPT` needs updating**

Review whether the new Studio page and `aisbf/studio.py` count as a significant project-structure or key-functionality change under `AI.PROMPT`. If yes, add a concise section documenting the new Studio integration points and capability inference responsibilities.

Suggested addition:

```markdown
### aisbf/studio.py
Shared Studio integration helpers:
- Normalizes dashboard-visible provider/rotation/autoselect resources into a unified Studio catalog
- Infers and merges Studio capability metadata for autodetected and manually configured models
- Supports current user-only visibility and future permission-aware expansion
```

- [ ] **Step 2: Run targeted backend tests**

Run: `pytest tests/test_studio.py tests/routes/test_dashboard_studio.py -v`

Expected: PASS for all Studio-specific tests

- [ ] **Step 3: Run a broader regression slice covering dashboard provider behavior**

Run: `pytest tests/providers/test_claude_provider.py tests/auth/test_claude_auth.py -v`

Expected: PASS or, if unrelated failures already exist, capture them explicitly and confirm no Studio-related regressions are introduced

- [ ] **Step 4: Manually verify the Studio page in both roles**

Run the app with the project’s normal startup command, sign in as:
- admin
- regular user with user-owned providers/rotations/autoselects

Verify:
- `Studio` appears in nav for both roles
- `/dashboard/studio` uses dashboard theme tokens in dark and light themes
- user catalog shows only user-owned resources
- admin catalog shows global resources
- entries with incomplete capability metadata render as partial rather than disappearing

- [ ] **Step 5: Commit documentation updates if made**

```bash
git add AI.PROMPT
git commit -m "docs: document dashboard studio integration"
```

Skip this commit if `AI.PROMPT` does not change.

---

## Self-Review

- Spec coverage: this plan covers the new dashboard page, shared theming, unified provider/rotation/autoselect catalog, user-only visibility for now with future permission-ready service boundaries, best-effort capability inference on autodetect/manual insert, partial/unknown handling, and tests.
- Placeholder scan: all implementation tasks include concrete files, code snippets, commands, and expected outcomes; no `TODO`/`TBD` placeholders remain.
- Type consistency: the plan consistently uses `build_studio_catalog`, `infer_model_capabilities`, `apply_inferred_capabilities_to_model`, `derive_collection_capabilities`, `StudioCapabilityResult`, and `StudioAggregateCapabilityResult` across tasks.
