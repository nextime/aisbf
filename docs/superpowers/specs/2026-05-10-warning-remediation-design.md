# Warning Remediation Design

**Date:** 2026-05-10  
**Status:** Approved  
**Approach:** Narrow Deprecation API Replacement

## Problem Statement

The current Studio-related verification test slice passes, but emits nine warnings from three specific deprecated API usages in the codebase:

1. Pydantic v2 deprecation in `aisbf/models.py` due to `class Config`
2. FastAPI deprecation in `aisbf/routes/dashboard/settings.py` due to `Query(..., regex=...)`
3. FastAPI lifespan deprecation in `main.py` due to `@app.on_event("startup")` and `@app.on_event("shutdown")`

The user wants these warnings fixed rather than suppressed.

## Requirements

1. Remove the currently reported deprecation warnings by replacing deprecated APIs with their modern equivalents
2. Preserve existing runtime behavior and validation semantics
3. Keep the fix narrowly scoped to the warning sources already identified
4. Re-run the same warning-producing test slice after implementation
5. Avoid unrelated refactors or warning suppression-only solutions

## Root Cause Analysis

### 1. `aisbf/models.py`

`Message` uses the Pydantic v1 pattern:

```python
class Config:
    extra = "allow"
```

In Pydantic v2, class-based config is deprecated in favor of `ConfigDict` and `model_config`.

### 2. `aisbf/routes/dashboard/settings.py`

These route parameters still use deprecated `regex=` arguments:

- `order_by`
- `direction`
- `status_filter`
- `role_filter`

FastAPI now expects `pattern=` instead.

### 3. `main.py`

The app defines lifecycle hooks with:

- `@app.on_event("startup")`
- `@app.on_event("shutdown")`

FastAPI now prefers lifespan handlers for startup/shutdown orchestration.

## Scope

### In Scope

- `aisbf/models.py`
- `aisbf/routes/dashboard/settings.py`
- `main.py`
- Any directly related tests that must be adjusted only if the implementation requires it

### Out of Scope

- Warnings not present in the user-provided output
- Broad Pydantic/FastAPI modernization outside these concrete deprecations
- Behavior changes to startup, shutdown, route validation, or model parsing
- Warning suppression via pytest filters or runtime warning silencing

## Design Overview

## 1. Pydantic Config Modernization

### Target

- `aisbf/models.py`

### Change

Replace the class-based config on `Message` with a v2-style `ConfigDict`.

### Intended Result

The model should continue allowing extra fields exactly as before, but without the `PydanticDeprecatedSince20` warning.

### Implementation Shape

From:

```python
class Message(BaseModel):
    ...

    class Config:
        extra = "allow"
```

To:

```python
class Message(BaseModel):
    ...

    model_config = ConfigDict(extra="allow")
```

And update imports accordingly.

### Risk

Low. This is a direct behavior-preserving migration path officially supported by Pydantic v2.

## 2. FastAPI Query Pattern Modernization

### Target

- `aisbf/routes/dashboard/settings.py`

### Change

Replace the deprecated `regex=` keyword with `pattern=` in the four affected `Query(...)` declarations.

### Intended Result

Route validation rules remain identical because the same regular expression strings are preserved.

### Implementation Shape

From:

```python
order_by: str = Query('created_at', regex='^(username|last_login|created_at|tier_name)$')
```

To:

```python
order_by: str = Query('created_at', pattern='^(username|last_login|created_at|tier_name)$')
```

Apply the same keyword replacement to:

- `direction`
- `status_filter`
- `role_filter`

### Risk

Low. The validation intent remains the same.

## 3. FastAPI Lifespan Migration

### Target

- `main.py`

### Change

Replace the deprecated startup/shutdown decorators with a lifespan context manager, while preserving the same initialization and cleanup order.

### Intended Result

The app should initialize and shut down exactly as before, but without the `on_event is deprecated` warnings.

### Migration Strategy

The current startup and shutdown logic is already grouped in two functions. The safest migration is:

1. Extract the startup body into an async helper
2. Extract the shutdown body into an async helper
3. Create a lifespan context manager that:
   - awaits startup helper before `yield`
   - awaits shutdown helper after `yield`
4. Pass the lifespan handler when constructing the FastAPI app, or assign it in the supported way used by the current app structure

### Behavioral Constraints

The following must remain unchanged:

- server IP geolocation check
- app initialization order
- database/cache/response-cache/request-batcher initialization
- TOR/payment service startup
- router initialization
- background task startup
- TOR disconnect and multiprocessing cleanup on shutdown

### Risk

Moderate. Lifespan touches application boot/shutdown behavior, so implementation must preserve ordering and async semantics exactly.

## Testing Strategy

The same test slice that currently produces the warnings should be used as the primary verification target:

```bash
PYTHONPATH=/working/aisbf pytest tests/test_license_headers.py tests/test_studio.py tests/routes/test_dashboard_studio.py tests/providers/test_claude_provider.py tests/auth/test_claude_auth.py -v
```

## Success Criteria

This remediation is successful if all of the following are true:

- The tests still pass after the change
- The `class Config` warning from `aisbf/models.py` is gone
- The `regex` warnings from `aisbf/routes/dashboard/settings.py` are gone
- The `on_event` warnings from `main.py` are gone
- No warning suppression mechanism was added
- No new behavioral regressions are introduced in startup, shutdown, or route validation

## Risks and Mitigations

### Risk: lifespan migration changes startup semantics

**Mitigation:** preserve the existing startup/shutdown bodies almost verbatim, moving them into helpers rather than refactoring logic while migrating.

### Risk: validation behavior drift from `regex` to `pattern`

**Mitigation:** keep the exact same regex strings and only replace the keyword.

### Risk: partial modernization leaves hidden warning sources

**Mitigation:** use the same end-to-end verification command that originally emitted the warnings and compare warning output after the fix.
