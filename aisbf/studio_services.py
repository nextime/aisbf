"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free
"""

from __future__ import annotations

import re
import base64
import json
import mimetypes
import time
import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from aisbf.database import DatabaseRegistry


class StudioService:
    def __init__(self) -> None:
        base_dir = Path.home() / ".aisbf" / "studio"
        self.base_dir = base_dir
        self.characters_dir = base_dir / "characters"
        self.environments_dir = base_dir / "environments"
        self.voices_dir = base_dir / "voices"
        self.archive_dir = base_dir / "archive"
        self.pipelines_dir = base_dir / "pipelines"
        for directory in (
            self.characters_dir,
            self.environments_dir,
            self.voices_dir,
            self.archive_dir,
            self.pipelines_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    STUDIO_FUNCTION_BINDINGS = [
        {
            "id": "chat",
            "label": "Chat",
            "kind": "single",
            "category": "chat",
            "endpoint": "/chat/completions",
            "roles": [
                {"key": "model", "label": "Chat model", "capabilities": ["text_generation"]},
            ],
        },
        {
            "id": "img-gen",
            "label": "Image generate",
            "kind": "single",
            "category": "image",
            "endpoint": "/images/generations",
            "roles": [
                {"key": "model", "label": "Image model", "capabilities": ["image_generation"]},
            ],
        },
        {
            "id": "img-edit",
            "label": "Image edit",
            "kind": "single",
            "category": "image",
            "endpoint": "/images/edits",
            "roles": [
                {"key": "model", "label": "Edit model", "capabilities": ["image_to_image"]},
            ],
        },
        {
            "id": "img-inpaint",
            "label": "Inpaint",
            "kind": "single",
            "category": "image",
            "endpoint": "/images/inpaint",
            "roles": [
                {"key": "model", "label": "Inpaint model", "capabilities": ["inpainting"]},
            ],
        },
        {
            "id": "img-upscale",
            "label": "Image upscale",
            "kind": "single",
            "category": "image",
            "endpoint": "/images/upscale",
            "roles": [
                {"key": "model", "label": "Upscale model", "capabilities": ["image_upscaling"]},
            ],
        },
        {
            "id": "img-depth",
            "label": "Depth",
            "kind": "single",
            "category": "image",
            "endpoint": "/images/depth",
            "roles": [
                {"key": "model", "label": "Depth model", "capabilities": ["depth_estimation"]},
            ],
        },
        {
            "id": "img-seg",
            "label": "Segment",
            "kind": "single",
            "category": "image",
            "endpoint": "/images/segment",
            "roles": [
                {"key": "model", "label": "Segmentation model", "capabilities": ["image_segmentation"]},
            ],
        },
        {
            "id": "img-faceswap",
            "label": "Face swap",
            "kind": "single",
            "category": "image",
            "endpoint": "/images/faceswap",
            "roles": [
                {"key": "model", "label": "Face swap model", "capabilities": ["image_to_image"]},
            ],
        },
        {
            "id": "img-deblur",
            "label": "Deblur",
            "kind": "single",
            "category": "image",
            "endpoint": "/images/deblur",
            "roles": [
                {"key": "model", "label": "Deblur model", "capabilities": ["image_to_image", "image_upscaling"]},
            ],
        },
        {
            "id": "img-unpix",
            "label": "Unpixelate",
            "kind": "single",
            "category": "image",
            "endpoint": "/images/unpixelate",
            "roles": [
                {"key": "model", "label": "Restore model", "capabilities": ["image_to_image", "image_upscaling"]},
            ],
        },
        {
            "id": "img-outfit",
            "label": "Outfit change",
            "kind": "single",
            "category": "image",
            "endpoint": "/images/outfit",
            "roles": [
                {"key": "model", "label": "Outfit model", "capabilities": ["image_to_image", "inpainting"]},
            ],
        },
        {
            "id": "img-to3d",
            "label": "2D to 3D",
            "kind": "single",
            "category": "3d",
            "endpoint": "/images/to3d",
            "roles": [
                {"key": "model", "label": "2D to 3D model", "capabilities": ["image_to_3d", "model_3d_generation"]},
            ],
        },
        {
            "id": "img-from3d",
            "label": "3D to 2D",
            "kind": "single",
            "category": "3d",
            "endpoint": "/images/from3d",
            "roles": [
                {"key": "model", "label": "3D render model", "capabilities": ["model_3d_to_image", "model_3d_generation"]},
            ],
        },
        {
            "id": "vid-t2v",
            "label": "Text to video",
            "kind": "single",
            "category": "video",
            "endpoint": "/video/generations",
            "roles": [
                {"key": "model", "label": "Video model", "capabilities": ["video_generation"]},
            ],
        },
        {
            "id": "vid-i2v",
            "label": "Image to video",
            "kind": "single",
            "category": "video",
            "endpoint": "/video/generations",
            "roles": [
                {"key": "model", "label": "I2V model", "capabilities": ["image_to_video", "video_generation"]},
            ],
        },
        {
            "id": "vid-v2v",
            "label": "Video to video",
            "kind": "single",
            "category": "video",
            "endpoint": "/video/generations",
            "roles": [
                {"key": "model", "label": "V2V model", "capabilities": ["video_to_video", "video_generation"]},
            ],
        },
        {
            "id": "vid-ti2v",
            "label": "Ti2V",
            "kind": "single",
            "category": "video",
            "endpoint": "/video/generations",
            "roles": [
                {"key": "model", "label": "Ti2V model", "capabilities": ["video_generation", "image_to_video", "video_to_video"]},
            ],
        },
        {
            "id": "vid-interp",
            "label": "Interpolate",
            "kind": "single",
            "category": "video",
            "endpoint": "/video/interpolate",
            "roles": [
                {"key": "model", "label": "Interpolation model", "capabilities": ["video_interpolation", "video_generation"]},
            ],
        },
        {
            "id": "vid-sub",
            "label": "Subtitles",
            "kind": "single",
            "category": "video",
            "endpoint": "/video/subtitle",
            "roles": [
                {"key": "model", "label": "Subtitle model", "capabilities": ["subtitle_generation", "speech_to_text"]},
            ],
        },
        {
            "id": "vid-dub",
            "label": "Video dub",
            "kind": "multi",
            "category": "video",
            "endpoint": "/video/dub",
            "roles": [
                {"key": "stt_model", "label": "Speech to text", "capabilities": ["speech_to_text"]},
                {"key": "tts_model", "label": "Text to speech", "capabilities": ["text_to_speech"]},
                {"key": "video_model", "label": "Video model", "capabilities": ["video_to_video", "video_generation"], "optional": True},
            ],
        },
        {
            "id": "vid-up",
            "label": "Video upscale",
            "kind": "single",
            "category": "video",
            "endpoint": "/video/upscale",
            "roles": [
                {"key": "model", "label": "Upscale model", "capabilities": ["video_upscaling", "video_generation"]},
            ],
        },
        {
            "id": "vid-faceswap",
            "label": "Video face swap",
            "kind": "single",
            "category": "video",
            "endpoint": "/images/faceswap",
            "roles": [
                {"key": "model", "label": "Face swap model", "capabilities": ["image_to_image", "video_to_video"]},
            ],
        },
        {
            "id": "vid-outfit",
            "label": "Video outfit change",
            "kind": "single",
            "category": "video",
            "endpoint": "/images/outfit",
            "roles": [
                {"key": "model", "label": "Outfit model", "capabilities": ["image_to_image", "inpainting", "video_to_video"]},
            ],
        },
        {
            "id": "vid-to3d",
            "label": "Video to 3D",
            "kind": "single",
            "category": "3d",
            "endpoint": "/video/to3d",
            "roles": [
                {"key": "model", "label": "Video to 3D model", "capabilities": ["video_to_3d", "model_3d_generation"]},
            ],
        },
        {
            "id": "vid-from3d",
            "label": "3D to video",
            "kind": "single",
            "category": "3d",
            "endpoint": "/video/from3d",
            "roles": [
                {"key": "model", "label": "3D video render model", "capabilities": ["video_generation", "model_3d_generation"]},
            ],
        },
        {
            "id": "aud-gen",
            "label": "Audio generate",
            "kind": "single",
            "category": "audio",
            "endpoint": "/audio/generate",
            "roles": [
                {"key": "model", "label": "Audio model", "capabilities": ["audio_generation"]},
            ],
        },
        {
            "id": "aud-tts",
            "label": "Text to speech",
            "kind": "single",
            "category": "audio",
            "endpoint": "/audio/speech",
            "roles": [
                {"key": "model", "label": "TTS model", "capabilities": ["text_to_speech"]},
            ],
        },
        {
            "id": "aud-clone",
            "label": "Voice clone",
            "kind": "single",
            "category": "audio",
            "endpoint": "/audio/clone",
            "roles": [
                {"key": "model", "label": "Voice clone model", "capabilities": ["text_to_speech"]},
            ],
        },
        {
            "id": "aud-convert",
            "label": "Voice convert",
            "kind": "single",
            "category": "audio",
            "endpoint": "/audio/convert",
            "roles": [
                {"key": "model", "label": "Voice convert model", "capabilities": ["audio_to_audio", "speech_to_text"]},
            ],
        },
        {
            "id": "aud-stt",
            "label": "Transcribe",
            "kind": "single",
            "category": "audio",
            "endpoint": "/audio/transcriptions",
            "roles": [
                {"key": "model", "label": "STT model", "capabilities": ["speech_to_text"]},
            ],
        },
        {
            "id": "aud-understand",
            "label": "Audio understand",
            "kind": "multi",
            "category": "audio",
            "endpoint": "/pipelines/audio-understand",
            "roles": [
                {"key": "audio_model", "label": "Audio model", "capabilities": ["speech_to_text"]},
                {"key": "text_model", "label": "Reasoning model", "capabilities": ["text_generation"], "optional": True},
            ],
        },
        {
            "id": "aud-music-dub",
            "label": "Music dub",
            "kind": "multi",
            "category": "audio",
            "endpoint": "/pipelines/audio-music-dub",
            "roles": [
                {"key": "stt_model", "label": "Speech to text", "capabilities": ["speech_to_text"]},
                {"key": "tts_model", "label": "Text to speech", "capabilities": ["text_to_speech"]},
                {"key": "audio_model", "label": "Audio model", "capabilities": ["audio_generation", "audio_to_audio"], "optional": True},
            ],
        },
        {
            "id": "aud-stems",
            "label": "Stem separation",
            "kind": "single",
            "category": "audio",
            "endpoint": "/audio/stems",
            "roles": [
                {"key": "model", "label": "Stem model", "capabilities": ["audio_to_audio", "audio_generation"]},
            ],
        },
        {
            "id": "aud-clean",
            "label": "Audio cleanup",
            "kind": "single",
            "category": "audio",
            "endpoint": "/audio/cleanup",
            "roles": [
                {"key": "model", "label": "Cleanup model", "capabilities": ["audio_to_audio", "speech_to_text"]},
            ],
        },
        {
            "id": "embed",
            "label": "Embeddings",
            "kind": "single",
            "category": "embed",
            "endpoint": "/embeddings",
            "roles": [
                {"key": "model", "label": "Embedding model", "capabilities": ["embeddings"]},
            ],
        },
        {
            "id": "3d-generate",
            "label": "3D generate",
            "kind": "single",
            "category": "3d",
            "endpoint": "/pipelines/3d-generate",
            "roles": [
                {"key": "model", "label": "3D model", "capabilities": ["model_3d_generation"]},
            ],
        },
        {
            "id": "3d-img-to3d",
            "label": "Image to 3D",
            "kind": "single",
            "category": "3d",
            "endpoint": "/images/to3d",
            "roles": [
                {"key": "model", "label": "Image to 3D model", "capabilities": ["image_to_3d", "model_3d_generation"]},
            ],
        },
        {
            "id": "3d-vid-to3d",
            "label": "Video to 3D",
            "kind": "single",
            "category": "3d",
            "endpoint": "/video/to3d",
            "roles": [
                {"key": "model", "label": "Video to 3D model", "capabilities": ["video_to_3d", "model_3d_generation"]},
            ],
        },
        {
            "id": "3d-from3d",
            "label": "3D render",
            "kind": "single",
            "category": "3d",
            "endpoint": "/images/from3d",
            "roles": [
                {"key": "model", "label": "3D render model", "capabilities": ["model_3d_to_image", "model_3d_generation"]},
            ],
        },
        {
            "id": "pipe-image-to-video",
            "label": "Pipeline image to video",
            "kind": "multi",
            "category": "pipe",
            "endpoint": "/pipelines/image-to-video",
            "roles": [
                {"key": "image_model", "label": "Image model", "capabilities": ["image_generation"]},
                {"key": "video_model", "label": "Video model", "capabilities": ["image_to_video", "video_generation"]},
            ],
        },
        {
            "id": "pipe-audio-dub",
            "label": "Pipeline audio dub",
            "kind": "multi",
            "category": "pipe",
            "endpoint": "/pipelines/audio-dub",
            "roles": [
                {"key": "stt_model", "label": "Speech to text", "capabilities": ["speech_to_text"]},
                {"key": "tts_model", "label": "Text to speech", "capabilities": ["text_to_speech"]},
            ],
        },
    ]

    def _scope_dir(self, root: Path, scope: str, owner_id: Optional[int]) -> Path:
        name = "admin" if scope == "admin" or owner_id is None else f"user_{owner_id}"
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _uses_database(self, scope: str, owner_id: Optional[int]) -> bool:
        return scope != "admin" and owner_id is not None

    def _admin_pipelines_path(self) -> Path:
        return Path.home() / ".aisbf" / "pipelines.json"

    def _admin_bindings_path(self) -> Path:
        return Path.home() / ".aisbf" / "studio_bindings.json"

    def _slugify_pipeline_id(self, value: str) -> str:
        text = (value or "pipeline").strip().lower()
        text = re.sub(r"[^a-z0-9]+", "-", text)
        text = text.strip("-")
        return text or "pipeline"

    def load_studio_system_prompt(self, scope: str, owner_id: Optional[int]) -> str:
        default_prompt = self._load_default_studio_system_prompt()
        if self._uses_database(scope, owner_id) and owner_id is not None:
            user_prompt = self._db().get_user_prompt(owner_id, "studio_system")
            return user_prompt if user_prompt is not None else default_prompt
        config_path = Path.home() / ".aisbf" / "STUDIO_SYSTEM.md"
        if config_path.exists():
            try:
                return config_path.read_text()
            except Exception:
                return default_prompt
        return default_prompt

    def _load_default_studio_system_prompt(self) -> str:
        installed_dirs = [
            Path('/usr/share/aisbf'),
            Path.home() / '.local' / 'share' / 'aisbf',
        ]
        for installed_dir in installed_dirs:
            prompt_file = installed_dir / 'STUDIO_SYSTEM.md'
            if prompt_file.exists():
                try:
                    return prompt_file.read_text()
                except Exception:
                    break
        source_file = Path(__file__).parent.parent / 'config' / 'STUDIO_SYSTEM.md'
        if source_file.exists():
            try:
                return source_file.read_text()
            except Exception:
                pass
        return "You are AiSBF, a general assistant..."

    def _db(self):
        return DatabaseRegistry.get_config_database()

    def _item_dir(self, root: Path, scope: str, owner_id: Optional[int], name: str) -> Path:
        path = self._scope_dir(root, scope, owner_id) / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _meta_path(self, item_dir: Path) -> Path:
        return item_dir / "meta.json"

    def _read_meta(self, item_dir: Path) -> Optional[Dict[str, Any]]:
        meta_path = self._meta_path(item_dir)
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text())
        except Exception:
            return None

    def _write_meta(self, item_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(payload)
        payload.setdefault("updated_at", int(time.time()))
        if "created_at" not in payload:
            payload["created_at"] = payload["updated_at"]
        self._meta_path(item_dir).write_text(json.dumps(payload, indent=2))
        return payload

    def _list_items(self, root: Path, scope: str, owner_id: Optional[int]) -> List[Dict[str, Any]]:
        scoped = self._scope_dir(root, scope, owner_id)
        items: List[Dict[str, Any]] = []
        for item_dir in sorted(scoped.iterdir()):
            if not item_dir.is_dir():
                continue
            meta = self._read_meta(item_dir)
            if meta:
                items.append(meta)
        items.sort(key=lambda row: row.get("updated_at", 0), reverse=True)
        return items

    def _delete_item(self, root: Path, scope: str, owner_id: Optional[int], name: str) -> bool:
        item_dir = self._item_dir(root, scope, owner_id, name)
        if not item_dir.exists():
            return False
        for child in item_dir.iterdir():
            if child.is_file():
                child.unlink()
        item_dir.rmdir()
        return True

    def _store_uploads(self, item_dir: Path, uploads: List[str], prefix: str) -> List[str]:
        stored: List[str] = []
        for index, data_url in enumerate(uploads or []):
            if not isinstance(data_url, str) or "," not in data_url:
                continue
            header, encoded = data_url.split(",", 1)
            ext = ".bin"
            if "image/" in header:
                ext = ".png"
            elif "audio/" in header:
                ext = ".wav"
            elif "video/" in header:
                ext = ".mp4"
            target = item_dir / f"{prefix}_{index}{ext}"
            try:
                target.write_bytes(base64.b64decode(encoded))
                stored.append(target.name)
            except Exception:
                continue
        return stored

    def list_characters(self, scope: str, owner_id: Optional[int]) -> List[Dict[str, Any]]:
        if self._uses_database(scope, owner_id):
            return self._db().list_studio_assets(owner_id, "character")
        return self._list_items(self.characters_dir, scope, owner_id)

    def get_character(self, scope: str, owner_id: Optional[int], name: str) -> Optional[Dict[str, Any]]:
        if self._uses_database(scope, owner_id):
            item = self._db().get_studio_asset(owner_id, "character", name)
        else:
            item = self._read_meta(self._item_dir(self.characters_dir, scope, owner_id, name))
        return self._normalize_profile_item(item, "character")

    def save_character(self, scope: str, owner_id: Optional[int], payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload.get("name")
        if self._uses_database(scope, owner_id):
            existing = self._db().get_studio_asset(owner_id, "character", name) or {"name": name}
            images = payload.get("images") or existing.get("ref_images", [])
            meta = {
                "ref_images": images,
                "image_count": len(images),
                "scope": scope,
                "owner_id": owner_id,
            }
            return self._db().upsert_studio_asset(owner_id, "character", name, payload.get("description", ""), meta, images)
        item_dir = self._item_dir(self.characters_dir, scope, owner_id, name)
        existing = self._read_meta(item_dir) or {"name": name}
        images = payload.get("images") or []
        stored = self._store_uploads(item_dir, images, "ref")
        existing.update({
            "name": name,
            "description": payload.get("description", ""),
            "kind": "character",
            "ref_images": stored or existing.get("ref_images", []),
            "thumbnail_url": f"/admin/api/characters/{name}/thumbnail",
            "scope": scope,
            "owner_id": owner_id,
        })
        return self._write_meta(item_dir, existing)

    def list_environments(self, scope: str, owner_id: Optional[int]) -> List[Dict[str, Any]]:
        if self._uses_database(scope, owner_id):
            return self._db().list_studio_assets(owner_id, "environment")
        return self._list_items(self.environments_dir, scope, owner_id)

    def get_environment(self, scope: str, owner_id: Optional[int], name: str) -> Optional[Dict[str, Any]]:
        if self._uses_database(scope, owner_id):
            item = self._db().get_studio_asset(owner_id, "environment", name)
        else:
            item = self._read_meta(self._item_dir(self.environments_dir, scope, owner_id, name))
        return self._normalize_profile_item(item, "environment")

    def save_environment(self, scope: str, owner_id: Optional[int], payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload.get("name")
        if self._uses_database(scope, owner_id):
            existing = self._db().get_studio_asset(owner_id, "environment", name) or {"name": name}
            images = payload.get("images") or existing.get("ref_images", [])
            meta = {
                "ref_images": images,
                "image_count": len(images),
                "scope": scope,
                "owner_id": owner_id,
            }
            return self._db().upsert_studio_asset(owner_id, "environment", name, payload.get("description", ""), meta, images)
        item_dir = self._item_dir(self.environments_dir, scope, owner_id, name)
        existing = self._read_meta(item_dir) or {"name": name}
        images = payload.get("images") or []
        stored = self._store_uploads(item_dir, images, "env")
        existing.update({
            "name": name,
            "description": payload.get("description", ""),
            "kind": "environment",
            "ref_images": stored or existing.get("ref_images", []),
            "thumbnail_url": f"/admin/api/environments/{name}/thumbnail",
            "scope": scope,
            "owner_id": owner_id,
        })
        return self._write_meta(item_dir, existing)

    def list_voices(self, scope: str, owner_id: Optional[int]) -> List[Dict[str, Any]]:
        if self._uses_database(scope, owner_id):
            return self._db().list_studio_assets(owner_id, "voice")
        return self._list_items(self.voices_dir, scope, owner_id)

    def save_voice(self, scope: str, owner_id: Optional[int], payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload.get("name")
        if self._uses_database(scope, owner_id):
            existing = self._db().get_studio_asset(owner_id, "voice", name) or {"name": name}
            samples = payload.get("samples") or existing.get("sample_files", [])
            meta = {
                "sample_files": samples,
                "scope": scope,
                "owner_id": owner_id,
            }
            return self._db().upsert_studio_asset(owner_id, "voice", name, payload.get("description", ""), meta, samples, payload.get("quote", existing.get("quote", "")))
        item_dir = self._item_dir(self.voices_dir, scope, owner_id, name)
        existing = self._read_meta(item_dir) or {"name": name}
        samples = payload.get("samples") or []
        stored = self._store_uploads(item_dir, samples, "voice")
        existing.update({
            "name": name,
            "description": payload.get("description", ""),
            "kind": "voice",
            "sample_files": stored or existing.get("sample_files", []),
            "quote": payload.get("quote", existing.get("quote", "")),
            "scope": scope,
            "owner_id": owner_id,
        })
        return self._write_meta(item_dir, existing)

    def list_archive(self, scope: str, owner_id: Optional[int]) -> List[Dict[str, Any]]:
        scoped = self._scope_dir(self.archive_dir, scope, owner_id)
        files: List[Dict[str, Any]] = []
        for file_path in sorted(scoped.iterdir()):
            if not file_path.is_file():
                continue
            mime, _ = mimetypes.guess_type(file_path.name)
            if mime and mime.startswith("image"):
                kind = "image"
            elif mime and mime.startswith("video"):
                kind = "video"
            elif mime and mime.startswith("audio"):
                kind = "audio"
            else:
                kind = "file"
            stat = file_path.stat()
            files.append({
                "filename": file_path.name,
                "url": f"/dashboard/static/studio-archive/{'admin' if scope == 'admin' or owner_id is None else f'user_{owner_id}'}/{file_path.name}",
                "size": stat.st_size,
                "created": int(stat.st_mtime),
                "type": kind,
            })
        files.sort(key=lambda row: row["created"], reverse=True)
        return files

    def save_pipeline(self, scope: str, owner_id: Optional[int], payload: Dict[str, Any]) -> Dict[str, Any]:
        pipeline_id = self._slugify_pipeline_id(payload.get("id") or payload.get("name", "pipeline"))
        name = (payload.get("name") or pipeline_id).strip() or pipeline_id
        description = payload.get("description", "")
        steps = payload.get("steps", [])
        if self._uses_database(scope, owner_id):
            return self._db().upsert_studio_pipeline(owner_id, pipeline_id, name, description, steps)
        pipelines_path = self._admin_pipelines_path()
        existing_rows = self._read_pipelines_json(pipelines_path)
        created_at = int(time.time())
        for row in existing_rows:
            if row.get("id") == pipeline_id:
                created_at = row.get("created_at") or created_at
                break
        record = {
            "id": pipeline_id,
            "name": name,
            "description": description,
            "steps": steps,
            "scope": scope,
            "owner_id": owner_id,
            "created_at": created_at,
            "updated_at": int(time.time()),
        }
        updated_rows = [row for row in existing_rows if row.get("id") != pipeline_id]
        updated_rows.insert(0, record)
        self._write_pipelines_json(pipelines_path, updated_rows)
        return record

    def list_pipelines(self, scope: str, owner_id: Optional[int]) -> List[Dict[str, Any]]:
        if self._uses_database(scope, owner_id):
            return self._db().list_studio_pipelines(owner_id)
        return self._read_pipelines_json(self._admin_pipelines_path())

    def delete_pipeline(self, scope: str, owner_id: Optional[int], pipeline_id: str) -> bool:
        if self._uses_database(scope, owner_id):
            return self._db().delete_studio_pipeline(owner_id, pipeline_id)
        pipelines_path = self._admin_pipelines_path()
        rows = self._read_pipelines_json(pipelines_path)
        updated_rows = [row for row in rows if row.get("id") != pipeline_id]
        if len(updated_rows) == len(rows):
            return False
        self._write_pipelines_json(pipelines_path, updated_rows)
        return True

    def get_pipeline(self, scope: str, owner_id: Optional[int], pipeline_id: str) -> Optional[Dict[str, Any]]:
        if self._uses_database(scope, owner_id):
            return self._db().get_studio_pipeline(owner_id, pipeline_id)
        rows = self.list_pipelines(scope, owner_id)
        for row in rows:
            if row.get("id") == pipeline_id:
                return row
        return None

    def _read_pipelines_json(self, file_path: Path) -> List[Dict[str, Any]]:
        if not file_path.exists():
            return []
        try:
            raw = file_path.read_text()
        except Exception:
            return []
        try:
            rows = json.loads(raw)
        except Exception:
            return []
        if not isinstance(rows, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            pipeline_id = self._slugify_pipeline_id(str(row.get("id") or row.get("name") or "pipeline"))
            normalized.append({
                "id": pipeline_id,
                "name": row.get("name") or pipeline_id,
                "description": row.get("description") or "",
                "steps": row.get("steps") or [],
                "scope": row.get("scope") or "admin",
                "owner_id": row.get("owner_id"),
                "created_at": int(row.get("created_at") or time.time()),
                "updated_at": int(row.get("updated_at") or row.get("created_at") or time.time()),
            })
        normalized.sort(key=lambda row: row.get("updated_at", 0), reverse=True)
        return normalized

    def _write_pipelines_json(self, file_path: Path, rows: List[Dict[str, Any]]) -> None:
        payload = json.dumps(rows, indent=2)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(f"{payload}\n")

    def _pipeline_step_binding_map(self) -> Dict[str, Dict[str, Any]]:
        return {item["id"]: item for item in self.STUDIO_FUNCTION_BINDINGS}

    def _normalize_pipeline_steps(self, steps: Any) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        if not isinstance(steps, list):
            return normalized
        known = self._pipeline_step_binding_map()
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_type = str(step.get("type") or "").strip()
            if not step_type:
                continue
            meta = known.get(step_type, {})
            normalized.append({
                "type": step_type,
                "label": str(step.get("label") or meta.get("label") or step_type).strip() or step_type,
                "params": step.get("params") if isinstance(step.get("params"), dict) else {},
            })
        return normalized

    def _pipeline_context(self, seed_input: Any, seed_story: Any, prior_steps: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "input": seed_input,
            "story": seed_story,
            "steps": prior_steps,
        }

    def _resolve_pipeline_value(self, value: Any, context: Dict[str, Any]) -> Any:
        if isinstance(value, str):
            pattern = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
            matches = list(pattern.finditer(value))
            if not matches:
                return value

            def lookup(expr: str):
                expr = (expr or "").strip()
                if not expr:
                    return ""
                current: Any = context
                for token in expr.split('.'):
                    token = token.strip()
                    if not token:
                        return ""
                    step_match = re.fullmatch(r"step(\d+)", token)
                    if step_match:
                        idx = int(step_match.group(1))
                        steps = current.get("steps") if isinstance(current, dict) else None
                        if not isinstance(steps, list) or idx < 0 or idx >= len(steps):
                            return ""
                        current = steps[idx]
                        continue
                    if isinstance(current, dict):
                        current = current.get(token)
                    elif isinstance(current, list) and token.isdigit():
                        idx = int(token)
                        if idx < 0 or idx >= len(current):
                            return ""
                        current = current[idx]
                    else:
                        return ""
                return current

            if len(matches) == 1 and matches[0].span() == (0, len(value)):
                return self._resolve_pipeline_value(lookup(matches[0].group(1)), context)

            resolved = value
            for match in reversed(matches):
                replacement = lookup(match.group(1))
                if replacement is None:
                    replacement = ""
                elif isinstance(replacement, (dict, list)):
                    replacement = json.dumps(replacement)
                else:
                    replacement = str(replacement)
                resolved = resolved[:match.start()] + replacement + resolved[match.end():]
            return resolved
        if isinstance(value, dict):
            return {key: self._resolve_pipeline_value(val, context) for key, val in value.items()}
        if isinstance(value, list):
            return [self._resolve_pipeline_value(item, context) for item in value]
        return value

    def _coerce_pipeline_bool(self, value: Any) -> Any:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "on"}:
                return True
            if lowered in {"false", "no", "off"}:
                return False
        return value

    def _extract_step_artifacts(self, response_payload: Any) -> Dict[str, Any]:
        artifacts: Dict[str, Any] = {
            "raw": response_payload,
        }
        if isinstance(response_payload, dict):
            for key in ("output", "url", "b64_wav", "text", "input", "data", "result", "results", "steps"):
                if key in response_payload:
                    artifacts[key] = response_payload.get(key)

            choices = response_payload.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0] if isinstance(choices[0], dict) else None
                if first:
                    message = first.get("message")
                    if isinstance(message, dict) and isinstance(message.get("content"), str):
                        artifacts.setdefault("output", message.get("content"))
                    elif isinstance(first.get("text"), str):
                        artifacts.setdefault("output", first.get("text"))

            data = response_payload.get("data")
            if isinstance(data, list) and data:
                first = data[0] if isinstance(data[0], dict) else None
                if first:
                    for key in ("url", "b64_json", "revised_prompt", "text", "embedding"):
                        if key in first:
                            artifacts.setdefault(key, first.get(key))

            if "url" not in artifacts:
                for key in ("video_url", "audio_url", "image_url", "file_url"):
                    if isinstance(response_payload.get(key), str) and response_payload.get(key).strip():
                        artifacts["url"] = response_payload.get(key).strip()
                        break

            if "output" not in artifacts:
                for key in ("text", "caption", "transcript", "description", "summary", "result"):
                    if isinstance(response_payload.get(key), str) and response_payload.get(key).strip():
                        artifacts["output"] = response_payload.get(key).strip()
                        break
        elif isinstance(response_payload, str):
            artifacts["output"] = response_payload
        return artifacts

    async def _execute_pipeline_step(self, api_base: str, step: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        known = self._pipeline_step_binding_map()
        meta = known.get(step.get("type"), {})
        endpoint = meta.get("endpoint")
        if not endpoint:
            raise ValueError(f"Unsupported pipeline step type: {step.get('type')}")

        body = self._resolve_pipeline_value(deepcopy(step.get("params") or {}), context)
        if isinstance(body, dict):
            body = {key: self._coerce_pipeline_bool(val) for key, val in body.items()}
        else:
            body = {}

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            response = await client.post(f"{api_base}{endpoint}", json=body)
            response.raise_for_status()
            payload = response.json()

        artifacts = self._extract_step_artifacts(payload)
        return {
            "type": step.get("type"),
            "label": step.get("label") or meta.get("label") or step.get("type") or "step",
            "request": body,
            "response": payload,
            **artifacts,
        }

    def function_binding_definitions(self) -> List[Dict[str, Any]]:
        return json.loads(json.dumps(self.STUDIO_FUNCTION_BINDINGS))

    def _normalize_function_bindings(self, payload: Any) -> Dict[str, Dict[str, str]]:
        if not isinstance(payload, dict):
            return {}
        normalized: Dict[str, Dict[str, str]] = {}
        allowed = {item["id"]: {role["key"] for role in item.get("roles", [])} for item in self.STUDIO_FUNCTION_BINDINGS}
        for binding_id, role_map in payload.items():
            if binding_id not in allowed or not isinstance(role_map, dict):
                continue
            clean_roles: Dict[str, str] = {}
            for role_key, model_id in role_map.items():
                if role_key in allowed[binding_id] and isinstance(model_id, str) and model_id.strip():
                    clean_roles[role_key] = model_id.strip()
            if clean_roles:
                normalized[binding_id] = clean_roles
        return normalized

    def list_function_bindings(self, scope: str, owner_id: Optional[int]) -> Dict[str, Dict[str, str]]:
        if self._uses_database(scope, owner_id) and owner_id is not None:
            raw = self._db().get_user_prompt(owner_id, "studio_function_bindings")
            if raw is None:
                return {}
            try:
                payload = json.loads(raw)
            except Exception:
                return {}
            return self._normalize_function_bindings(payload)
        path = self._admin_bindings_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text())
        except Exception:
            return {}
        return self._normalize_function_bindings(payload)

    def save_function_binding(self, scope: str, owner_id: Optional[int], binding_id: str, roles: Dict[str, str]) -> Dict[str, Dict[str, str]]:
        bindings = self.list_function_bindings(scope, owner_id)
        updated = dict(bindings)
        normalized = self._normalize_function_bindings({binding_id: roles})
        if binding_id in normalized:
            updated[binding_id] = normalized[binding_id]
        else:
            updated.pop(binding_id, None)
        if self._uses_database(scope, owner_id) and owner_id is not None:
            self._db().set_user_prompt(owner_id, "studio_function_bindings", json.dumps(updated, indent=2))
            return updated
        path = self._admin_bindings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(updated, indent=2) + "\n")
        return updated

    def delete_function_binding(self, scope: str, owner_id: Optional[int], binding_id: str) -> Dict[str, Dict[str, str]]:
        bindings = self.list_function_bindings(scope, owner_id)
        if binding_id not in bindings:
            return bindings
        updated = dict(bindings)
        updated.pop(binding_id, None)
        if self._uses_database(scope, owner_id) and owner_id is not None:
            self._db().set_user_prompt(owner_id, "studio_function_bindings", json.dumps(updated, indent=2))
            return updated
        path = self._admin_bindings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(updated, indent=2) + "\n")
        return updated

    def delete_character(self, scope: str, owner_id: Optional[int], name: str) -> bool:
        if self._uses_database(scope, owner_id):
            return self._db().delete_studio_asset(owner_id, "character", name)
        return self._delete_item(self.characters_dir, scope, owner_id, name)

    def delete_environment(self, scope: str, owner_id: Optional[int], name: str) -> bool:
        if self._uses_database(scope, owner_id):
            return self._db().delete_studio_asset(owner_id, "environment", name)
        return self._delete_item(self.environments_dir, scope, owner_id, name)

    def delete_voice(self, scope: str, owner_id: Optional[int], name: str) -> bool:
        if self._uses_database(scope, owner_id):
            return self._db().delete_studio_asset(owner_id, "voice", name)
        return self._delete_item(self.voices_dir, scope, owner_id, name)

    def get_character_thumbnail_bytes(self, scope: str, owner_id: Optional[int], name: str) -> Optional[bytes]:
        item = self.get_character(scope, owner_id, name) or {}
        ref_images = item.get("ref_images", [])
        if not ref_images:
            return None
        first = ref_images[0]
        if self._uses_database(scope, owner_id):
            if isinstance(first, str) and "," in first:
                try:
                    return base64.b64decode(first.split(",", 1)[1])
                except Exception:
                    return None
            return None
        item_dir = self._item_dir(self.characters_dir, scope, owner_id, name)
        path = item_dir / first
        return path.read_bytes() if path.exists() else None

    def get_environment_thumbnail_bytes(self, scope: str, owner_id: Optional[int], name: str) -> Optional[bytes]:
        item = self.get_environment(scope, owner_id, name) or {}
        ref_images = item.get("ref_images", [])
        if not ref_images:
            return None
        first = ref_images[0]
        if self._uses_database(scope, owner_id):
            if isinstance(first, str) and "," in first:
                try:
                    return base64.b64decode(first.split(",", 1)[1])
                except Exception:
                    return None
            return None
        item_dir = self._item_dir(self.environments_dir, scope, owner_id, name)
        path = item_dir / first
        return path.read_bytes() if path.exists() else None

    def _normalize_profile_item(self, item: Optional[Dict[str, Any]], kind: str) -> Optional[Dict[str, Any]]:
        if not item:
            return None
        normalized = dict(item)
        refs = list(normalized.get("ref_images") or [])
        normalized.setdefault("kind", kind)
        normalized.setdefault("image_count", len(refs))
        normalized["images"] = [
            {
                "label": f"ref{index}",
                "data": ref,
            }
            for index, ref in enumerate(refs)
            if isinstance(ref, str)
        ]
        return normalized

    def run_pipeline(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        steps = self._normalize_pipeline_steps(payload.get("steps") or [])
        seed_input = payload.get("input") or payload.get("story") or ""
        seed_story = payload.get("story") or payload.get("input") or ""
        api_base = str(payload.get("api_base") or payload.get("_api_base") or "").rstrip("/")
        if not api_base:
            raise ValueError("Pipeline execution requires an API base path")

        results: List[Dict[str, Any]] = []

        async def _runner():
            for index, step in enumerate(steps):
                context = self._pipeline_context(seed_input, seed_story, results)
                try:
                    step_result = await self._execute_pipeline_step(api_base, step, context)
                    step_result["step"] = index
                except Exception as exc:
                    results.append({
                        "step": index,
                        "type": step.get("type", "step"),
                        "label": step.get("label") or step.get("type", f"step-{index}"),
                        "error": str(exc),
                    })
                    break
                else:
                    results.append(step_result)

        asyncio.run(_runner())
        return {"steps": results}

    def pipeline_step_types(self) -> List[Dict[str, Any]]:
        return [
            {"type": "chat", "label": "Chat", "params": [["model", "text", "Model", ""], ["prompt", "textarea", "Prompt", "{{input}}"]]},
            {"type": "img-gen", "label": "Image generate", "params": [["model", "text", "Model", ""], ["prompt", "textarea", "Prompt", "{{input}}"], ["size", "text", "Size", "1024x1024"]]},
            {"type": "img-edit", "label": "Image edit", "params": [["model", "text", "Model", ""], ["image", "ref", "Image ref", "{{input}}"], ["prompt", "textarea", "Prompt", "Enhance this image"]]},
            {"type": "img-faceswap", "label": "Face swap", "params": [["model", "text", "Model", ""], ["source_face", "ref", "Source face", "{{input}}"], ["target", "ref", "Target", "{{step0.url}}"], ["target_type", "select:image|video", "Target type", "image"]]},
            {"type": "vid-t2v", "label": "Text to video", "params": [["model", "text", "Model", ""], ["prompt", "textarea", "Prompt", "{{input}}"]]},
            {"type": "vid-dub", "label": "Video dub", "params": [["video_model", "text", "Video model", ""], ["stt_model", "text", "STT model", ""], ["tts_model", "text", "TTS model", ""], ["video", "ref", "Video ref", "{{input}}"], ["source_lang", "text", "Source language", ""], ["target_lang", "text", "Target language", "en"], ["burn_subtitles", "checkbox", "Burn subtitles", false]]},
            {"type": "aud-gen", "label": "Audio generate", "params": [["model", "text", "Model", ""], ["prompt", "textarea", "Prompt", "{{input}}"]]},
            {"type": "aud-tts", "label": "Text to speech", "params": [["model", "text", "Model", ""], ["input", "textarea", "Input text", "{{input}}"], ["voice", "text", "Voice", "alloy"]]},
            {"type": "aud-stt", "label": "Transcribe", "params": [["model", "text", "Model", ""], ["file", "ref", "Audio ref", "{{input}}"]]},
            {"type": "aud-clone", "label": "Voice clone", "params": [["model", "text", "Model", ""], ["input", "textarea", "Input text", "{{input}}"], ["reference_audio", "ref", "Reference audio", "{{step0.url}}"], ["ref_text", "textarea", "Reference transcript", ""]]},
            {"type": "aud-convert", "label": "Voice convert", "params": [["model", "text", "Model", ""], ["audio", "ref", "Audio ref", "{{input}}"], ["target_voice", "ref", "Target voice", "{{step0.url}}"]]},
            {"type": "embed", "label": "Embeddings", "params": [["model", "text", "Model", ""], ["input", "textarea", "Input", "{{input}}"]]},
            {"type": "3d-generate", "label": "3D generate", "params": [["model", "text", "Model", ""], ["prompt", "textarea", "Prompt", "{{input}}"]]},
            {"type": "img-to3d", "label": "Image to 3D", "params": [["model", "text", "Model", ""], ["image", "ref", "Image ref", "{{input}}"], ["prompt", "textarea", "Prompt", ""]]},
            {"type": "img-from3d", "label": "3D to image", "params": [["model", "text", "Model", ""], ["scene", "ref", "3D ref", "{{input}}"], ["prompt", "textarea", "Prompt", ""]]},
        ]

    def get_cached_models(self) -> Dict[str, Any]:
        return {"hf": [], "gguf": []}

    def get_admin_tokens(self) -> List[Dict[str, Any]]:
        return []


studio_service = StudioService()
