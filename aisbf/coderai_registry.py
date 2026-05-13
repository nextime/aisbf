from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from aisbf.config import config
from aisbf.database import DatabaseRegistry


logger = logging.getLogger(__name__)


def _providers_json_path() -> Path:
    path = Path.home() / '.aisbf' / 'providers.json'
    if path.exists():
        return path
    source_dir = config._get_config_source_dir()
    return source_dir / 'providers.json'


def _load_global_provider_config(provider_id: str) -> Optional[Dict[str, Any]]:
    provider = config.providers.get(provider_id)
    if provider:
        return provider.model_dump() if hasattr(provider, 'model_dump') else dict(provider)
    try:
        with open(_providers_json_path()) as f:
            payload = json.load(f)
        providers = payload.get('providers', payload)
        provider_config = providers.get(provider_id)
        return provider_config if isinstance(provider_config, dict) else None
    except Exception as e:
        logger.debug(f"Failed to load global provider config for {provider_id}: {e}")
        return None


def _load_user_provider_config(user_id: int, provider_id: str) -> Optional[Dict[str, Any]]:
    try:
        db = DatabaseRegistry.get_config_database()
        record = db.get_user_provider(user_id, provider_id) if db else None
        if record and isinstance(record.get('config'), dict):
            return record['config']
    except Exception as e:
        logger.debug(f"Failed to load user provider config for user={user_id} provider={provider_id}: {e}")
    return None


def _iter_user_coderai_matches(provider_id: str) -> list[Tuple[int, Dict[str, Any]]]:
    try:
        db = DatabaseRegistry.get_config_database()
        if not db:
            return []
        matches: list[Tuple[int, Dict[str, Any]]] = []
        for row in db.get_all_user_providers():
            if row.get('provider_id') != provider_id:
                continue
            provider_config = row.get('config')
            if isinstance(provider_config, dict) and provider_config.get('type') == 'coderai':
                user_id = row.get('user_id')
                if user_id is not None:
                    matches.append((user_id, provider_config))
        return matches
    except Exception as e:
        logger.debug(f"Failed to resolve user owner for provider={provider_id}: {e}")
    return []


def resolve_coderai_provider_owner(provider_id: str, username: Optional[str] = None) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    user_matches = _iter_user_coderai_matches(provider_id)

    if username == 'global':
        global_config = _load_global_provider_config(provider_id)
        if global_config and global_config.get('type') == 'coderai':
            return None, global_config
        return None, None

    if username:
        try:
            db = DatabaseRegistry.get_config_database()
            user = db.get_user_by_username(username) if db else None
            if not user:
                return None, None
            requested_user_id = user.get('id')
            for user_id, provider_config in user_matches:
                if user_id == requested_user_id:
                    return user_id, provider_config
            return None, None
        except Exception as e:
            logger.debug(f"Failed to resolve user by username for provider={provider_id} username={username}: {e}")
            return None, None

    if user_matches:
        if len(user_matches) == 1:
            return user_matches[0]
        logger.warning(f"Ambiguous user-scoped coderai provider owner for provider_id={provider_id}; refusing fallback without explicit username")
        return None, None

    global_config = _load_global_provider_config(provider_id)
    if global_config and global_config.get('type') == 'coderai':
        return None, global_config
    return None, None


def resolve_coderai_provider_for_user(user_id: Optional[int], provider_id: str) -> Optional[Dict[str, Any]]:
    if user_id is None:
        provider_config = _load_global_provider_config(provider_id)
        if provider_config and provider_config.get('type') == 'coderai':
            return provider_config
        return None

    provider_config = _load_user_provider_config(user_id, provider_id)
    if provider_config and provider_config.get('type') == 'coderai':
        return provider_config
    return None


def resolve_coderai_registration(provider_id: str, username: Optional[str] = None) -> Tuple[Optional[int], Optional[Dict[str, Any]], Optional[str]]:
    owner_user_id, provider_config = resolve_coderai_provider_owner(provider_id, username=username)
    if not provider_config:
        return None, None, None
    coderai_config = provider_config.get('coderai_config') or {}
    registration_token = coderai_config.get('registration_token') or provider_config.get('registration_token')
    if isinstance(registration_token, str):
        registration_token = registration_token.strip() or None
    return owner_user_id, provider_config, registration_token


def validate_coderai_registration_token(provider_id: str, presented_token: Optional[str], username: Optional[str] = None) -> Tuple[bool, Optional[int], Optional[Dict[str, Any]], Optional[str]]:
    owner_user_id, provider_config, expected_token = resolve_coderai_registration(provider_id, username=username)
    if not provider_config:
        return False, None, None, 'Provider not found or not a coderai provider'
    if expected_token and presented_token != expected_token:
        return False, owner_user_id, provider_config, 'Invalid registration token'
    if not expected_token:
        return False, owner_user_id, provider_config, 'Registration token not configured'
    return True, owner_user_id, provider_config, None
