# MinIO Archive for Studio-Generated Files

## Overview

Replace the local `~/.aisbf/studio/archive/` filesystem writes with an optional MinIO-backed object store. When MinIO is configured, all instances in a cluster write to and read from the same bucket. Local filesystem remains the fallback when MinIO is not configured, so single-node installs need no changes.

---

## Step 1 — Dependency

Add `boto3` to requirements (the AWS SDK, which is the standard MinIO Python client since MinIO exposes an S3-compatible API):

```
boto3>=1.34
```

No `aioboto3` needed — archive writes happen in response to generation requests and a synchronous upload is acceptable; the generation itself already takes seconds.

---

## Step 2 — Admin Settings (DB + API + UI)

### Database

Add `get_archive_storage_settings` / `save_archive_storage_settings` in `database.py`, following the exact pattern of `get_market_settings` / `save_market_settings`. Stored under key `archive_storage` in the `admin_settings` table as a JSON object:

```json
{
  "backend": "local",
  "endpoint_url": "http://minio:9000",
  "access_key": "",
  "secret_key": "",
  "bucket": "aisbf-archive",
  "region": "us-east-1",
  "presign_ttl_seconds": 3600,
  "public_url_base": ""
}
```

`backend` is either `"local"` or `"minio"`. `public_url_base` is optional — if set (e.g. `https://cdn.example.com/aisbf-archive`), presigned URLs are skipped and a plain public URL is constructed instead (useful when the bucket is public behind a CDN).

### API

Two endpoints in `routes/dashboard/admin.py`:

- `GET /api/admin/settings/archive-storage` — returns current settings with `secret_key` masked
- `POST /api/admin/settings/archive-storage` — saves and immediately validates the connection by calling `list_buckets()` on the client; returns an error if unreachable

### UI

New section in `admin_payment_settings.html` (or a dedicated `admin_storage_settings.html` linked from the settings nav). Fields:

- Backend toggle: local / MinIO
- Endpoint URL
- Access key
- Secret key
- Bucket name
- Region
- Presign TTL (seconds)
- Public URL base (optional)

Save button calls the POST endpoint and shows a connection test result inline.

---

## Step 3 — Storage Abstraction (`aisbf/archive_storage.py`)

New module with a simple interface:

```python
class ArchiveStorage:
    def put(self, object_key: str, data: bytes, content_type: str) -> str:
        """Store bytes, return a URL (presigned or public)."""

    def get_url(self, object_key: str) -> str:
        """Return a URL for an existing object."""

    def delete(self, object_key: str) -> None: ...

    def list_prefix(self, prefix: str) -> list[dict]:
        """List objects under a prefix, return dicts with key/size/last_modified."""
```

### `LocalArchiveStorage`

Wraps the current `Path.write_bytes` / `iterdir` / `unlink` logic extracted from `studio_services.py`. Returns `/dashboard/static/studio-archive/{key}` URLs. No new logic — this is a refactor of what exists today.

### `MinioArchiveStorage`

Uses `boto3.client('s3', endpoint_url=..., aws_access_key_id=..., aws_secret_access_key=...)`.

- `put`: `client.put_object(Bucket=bucket, Key=object_key, Body=data, ContentType=content_type)`
- `get_url`: if `public_url_base` is set, returns `f"{public_url_base}/{object_key}"`, otherwise calls `client.generate_presigned_url('get_object', Params={...}, ExpiresIn=ttl)`
- `delete`: `client.delete_object(Bucket=bucket, Key=object_key)`
- `list_prefix`: `client.list_objects_v2(Bucket=bucket, Prefix=prefix)`

### Factory

`get_archive_storage() -> ArchiveStorage` reads settings from the DB and returns the right implementation. Result is cached in a module-level variable and invalidated when settings are saved via the admin POST endpoint.

### Object key convention

`{scope}/{filename}` where scope is `admin` or `user_{owner_id}` — matches the existing local directory structure exactly, so the scope-path logic in `studio_services.py` maps 1:1 to object key prefixes.

---

## Step 4 — Integration into `studio_services.py`

Three touch points:

### `_scope_dir`

Currently creates and returns a `Path`. Extract the scope name logic into a separate `_scope_prefix(scope, owner_id) -> str` method used by both backends:

```python
def _scope_prefix(self, scope: str, owner_id: Optional[int]) -> str:
    return "admin" if scope == "admin" or owner_id is None else f"user_{owner_id}"
```

`_scope_dir` continues to use this internally for local storage; MinIO code uses `_scope_prefix` directly.

### Output file saving

Currently done inline wherever generation results are written (e.g. `target.write_bytes(base64.b64decode(encoded))`). These become:

```python
url = storage.put(f"{scope_prefix}/{filename}", data, content_type)
```

The returned URL is stored in the result metadata instead of constructing a static path string.

### `list_archive`

Replace `scoped.iterdir()` with `storage.list_prefix(scope_prefix)`. The returned dicts have `key`, `size`, `last_modified` — map to the existing response shape (`filename`, `url`, `size`, `created`, `type`). URL comes from `storage.get_url(key)`.

### File deletion

Replace `file_path.unlink()` with `storage.delete(object_key)`.

---

## Step 5 — Presigned URL Expiry Handling

Presigned URLs expire (default 1 hour, configurable in admin settings). The frontend calls the archive listing endpoint fresh on each page load, which regenerates presigned URLs at listing time — no special handling needed.

If a user keeps the archive tab open past the TTL and clicks a stale link, it will 403. This is acceptable standard S3 presigned URL behavior. The TTL can be set higher (e.g. 24h) for lower-churn archives.

---

## Step 6 — Migration Tool (optional)

A one-shot admin action:

`POST /api/admin/settings/archive-storage/migrate`

Iterates `~/.aisbf/studio/archive/` on the local node, uploads each file to MinIO using the same key convention, then optionally deletes local copies. Returns a progress count in the response.

Only needs to run once on one node after MinIO is configured. Not strictly required — new files go to MinIO immediately after the backend is switched; old local files simply stop being accessible via the new URLs. Whether to migrate historical files is the admin's choice.

---

## Step 7 — Bucket Bootstrapping

On `MinioArchiveStorage.__init__`, check if the configured bucket exists and create it if not:

```python
client.create_bucket(Bucket=bucket)
```

This means the admin only needs to provide credentials — the bucket is auto-provisioned on first use. If creation fails (permissions issue), surface the error in the connection test response from the admin POST endpoint.

---

## Files to Create / Modify

| File | Action | Notes |
|---|---|---|
| `aisbf/archive_storage.py` | **Create** | `ArchiveStorage` base, `LocalArchiveStorage`, `MinioArchiveStorage`, `get_archive_storage()` factory |
| `aisbf/database.py` | **Modify** | Add `get_archive_storage_settings`, `save_archive_storage_settings` |
| `aisbf/studio_services.py` | **Modify** | Extract `_scope_prefix`, replace all `Path` write/read/list/delete calls in archive methods with `get_archive_storage()` calls |
| `aisbf/routes/dashboard/admin.py` | **Modify** | Add GET/POST `/api/admin/settings/archive-storage` endpoints; optional `/migrate` action |
| `templates/dashboard/admin_payment_settings.html` | **Modify** | Add MinIO settings section with connection test feedback |
| `requirements.txt` / `pyproject.toml` | **Modify** | Add `boto3>=1.34` |

---

## Current State Reference

- Local archive path: `~/.aisbf/studio/archive/{scope}/`
- Current serving: FastAPI `StaticFiles` mounted at `/dashboard/static/studio-archive/`
- Current URL pattern: `/dashboard/static/studio-archive/admin/{filename}` or `/dashboard/static/studio-archive/user_{owner_id}/{filename}`
- Write entry point: `StudioService._store_uploads()` in `studio_services.py:566`
- List entry point: `StudioService.list_archive()` in `studio_services.py:696`
- Settings storage pattern: `admin_settings` table, key/JSON-value pairs — see `get_market_settings` / `save_market_settings` in `database.py` as the reference implementation
