"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Claude Code OAuth2 provider handler.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Why did the programmer quit his job? Because he didn't get arrays!
"""
import httpx
import asyncio
import time
import random
from typing import Dict, List, Optional, Union, Any
from anthropic import Anthropic
from ..models import Model
from ..config import config
from .base import BaseProviderHandler, AnthropicFormatConverter, AISBF_DEBUG


class ClaudeProviderHandler(BaseProviderHandler):
    """
    Handler for Claude Code OAuth2 integration using Anthropic SDK.
    
    This handler uses OAuth2 authentication to access Claude models through
    the official Anthropic Python SDK. OAuth2 access tokens are passed as
    the api_key parameter to the SDK, which handles proper message formatting,
    retries, and streaming.
    
    For admin users (user_id=None), credentials are loaded from file.
    For non-admin users, credentials are loaded from the database.
    """
    
    # NOTE: OAuth2 API uses its own model naming scheme that differs from standard Anthropic API
    
    def __init__(self, provider_id: str, api_key: Optional[str] = None, user_id: Optional[int] = None, provider_config: Optional[Any] = None):
        super().__init__(provider_id, api_key, user_id=user_id)
        if provider_config is not None:
            # Use provider config passed from factory (user-specific config)
            self.provider_config = provider_config
        else:
            # Fallback to global config
            self.provider_config = config.get_provider(provider_id)
        
        # Get credentials file path from config
        if isinstance(self.provider_config, dict):
            claude_config = self.provider_config.get('claude_config')
        else:
            claude_config = getattr(self.provider_config, 'claude_config', None)
        credentials_file = None
        if claude_config and isinstance(claude_config, dict):
            credentials_file = claude_config.get('credentials_file')
        
        # Only the ONE config admin (user_id=None from aisbf.json) uses file-based credentials
        # All other users (including database admins with user_id) use database credentials
        if user_id is not None:
            self.auth = self._load_auth_from_db(provider_id, credentials_file)
        else:
            # Config admin (from aisbf.json): use file-based credentials
            from ..auth.claude import ClaudeAuth
            self.auth = ClaudeAuth(credentials_file=credentials_file)
        
        # HTTP client for direct API requests (OAuth2 requires direct HTTP, not SDK)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
        
        # Streaming idle watchdog configuration (Phase 1.3)
        self.stream_idle_timeout = 90.0  # seconds - matches vendors/claude
        
        # Cache token tracking for analytics (Phase 2.3)
        self.cache_stats = {
            'cache_hits': 0,
            'cache_misses': 0,
            'cache_tokens_read': 0,
            'cache_tokens_created': 0,
            'total_requests': 0,
        }
        
        # Session management for quota tracking
        self.session_state = {
            'initialized': False,
            'session_id': None,
            'device_id': None,
            'account_uuid': None,
            'organization_id': None,
            'last_initialized': None,
            'quota_5h_reset': None,
            'quota_5h_utilization': None,
            'quota_7d_reset': None,
            'quota_7d_utilization': None,
            'representative_claim': None,
            'status': None,
            'session_timeout': 3600,  # 1 hour session timeout
        }
        
        # Initialize persistent identifiers for metadata
        self._init_session_identifiers()
    
    def _load_auth_from_db(self, provider_id: str, credentials_file: str):
        """
        Load OAuth2 credentials:
        - Admin users (user_id=None): ONLY load from file
        - Regular users: ONLY load from database, NO file fallback
        """
        from ..auth.claude import ClaudeAuth
        import logging
        
        if self.user_id is None:
            # Admin user: ONLY use file-based credentials
            logging.getLogger(__name__).info(f"ClaudeProviderHandler: Admin user, loading credentials from file: {credentials_file}")
            return ClaudeAuth(credentials_file=credentials_file)
        
        # Regular user: ONLY use database credentials, NO file fallback
        try:
            from ..database import DatabaseRegistry
            db = DatabaseRegistry.get_config_database()
            if db:
                db_creds = db.get_user_oauth2_credentials(
                    user_id=self.user_id,
                    provider_id=provider_id,
                    auth_type='claude_oauth2'
                )
                if db_creds and db_creds.get('credentials'):
                    # Create auth instance with skip_initial_load=True to avoid file read
                    # Pass save callback to save credentials back to database
                     auth = ClaudeAuth(
                         credentials_file=credentials_file, 
                         skip_initial_load=True,
                         save_callback=lambda creds: self._save_auth_to_db(creds)
                     )
                     # Set tokens directly from database
                     auth.tokens = db_creds['credentials'].get('tokens', {})
                     # Add expires_at if missing (for existing credentials saved before fix)
                     if auth.tokens and 'expires_at' not in auth.tokens and 'expires_in' in auth.tokens:
                         import time
                         auth.tokens['expires_at'] = time.time() + auth.tokens.get('expires_in', 3600)
                     import logging
                     logging.getLogger(__name__).info(f"ClaudeProviderHandler: Loaded credentials from database for user {self.user_id}")
                     return auth
        except Exception as e:
            logging.getLogger(__name__).warning(f"ClaudeProviderHandler: Failed to load credentials from database: {e}")
        
        # For regular users, NO file fallback - return empty auth instance
        logging.getLogger(__name__).info(f"ClaudeProviderHandler: No database credentials found for user {self.user_id}, returning unauthenticated instance")
        return ClaudeAuth(credentials_file=credentials_file, skip_initial_load=True)
    
    def _init_session_identifiers(self):
        """Initialize persistent session identifiers (device_id, account_uuid, session_id)."""
        import uuid
        import hashlib
        
        if not self.session_state.get('device_id'):
            device_seed = f"{self.provider_id}-{time.time()}"
            self.session_state['device_id'] = hashlib.sha256(device_seed.encode()).hexdigest()
        
        if not self.session_state.get('account_uuid'):
            account_id = self.auth.get_account_id()
            if account_id:
                self.session_state['account_uuid'] = account_id
            else:
                self.session_state['account_uuid'] = str(uuid.uuid4())
    
    async def _initialize_session(self):
        """Initialize session by sending a quota request to get rate limit information."""
        import logging
        import json
        
        logger = logging.getLogger(__name__)
        logger.info("ClaudeProviderHandler: Initializing session for quota tracking")
        
        try:
            headers = await self._get_auth_headers(stream=False)
            
            payload = {
                'model': 'claude-haiku-4-5-20251001',
                'max_tokens': 1,
                'messages': [
                    {
                        'role': 'user',
                        'content': 'quota'
                    }
                ],
                'metadata': {
                    'user_id': json.dumps({
                        'device_id': self.session_state['device_id'],
                        'account_uuid': self.session_state['account_uuid'],
                        'session_id': self.session_state['session_id']
                    })
                }
            }
            
            api_url = 'https://api.anthropic.com/v1/messages?beta=true'
            response = await self.client.post(api_url, headers=headers, json=payload)
            
            if response.status_code == 200:
                headers_dict = dict(response.headers)
                
                self.session_state.update({
                    'initialized': True,
                    'last_initialized': time.time(),
                    'organization_id': headers_dict.get('anthropic-organization-id'),
                    'quota_5h_reset': headers_dict.get('anthropic-ratelimit-unified-5h-reset'),
                    'quota_5h_utilization': headers_dict.get('anthropic-ratelimit-unified-5h-utilization'),
                    'quota_7d_reset': headers_dict.get('anthropic-ratelimit-unified-7d-reset'),
                    'quota_7d_utilization': headers_dict.get('anthropic-ratelimit-unified-7d-utilization'),
                    'representative_claim': headers_dict.get('anthropic-ratelimit-unified-representative-claim'),
                    'status': headers_dict.get('anthropic-ratelimit-unified-status'),
                })
                
                logger.info(f"ClaudeProviderHandler: Session initialized successfully")
                logger.info(f"  Organization ID: {self.session_state['organization_id']}")
                logger.info(f"  5h utilization: {self.session_state['quota_5h_utilization']}")
                logger.info(f"  7d utilization: {self.session_state['quota_7d_utilization']}")
                logger.info(f"  Representative claim: {self.session_state['representative_claim']}")
                logger.info(f"  Status: {self.session_state['status']}")
                
                return True
            else:
                logger.warning(f"ClaudeProviderHandler: Session initialization failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"ClaudeProviderHandler: Session initialization error: {e}", exc_info=True)
            return False
    
    def _should_refresh_session(self) -> bool:
        """Check if session should be refreshed based on timeout or rate limit status."""
        if not self.session_state['initialized']:
            return True
        
        if self.session_state['last_initialized']:
            age = time.time() - self.session_state['last_initialized']
            if age > self.session_state['session_timeout']:
                return True
        
        if self.session_state['status'] != 'allowed':
            return True
        
        return False
    
    async def _ensure_session(self):
        """Ensure session is initialized and valid before making requests."""
        if self._should_refresh_session():
            import logging
            logger = logging.getLogger(__name__)
            logger.info("ClaudeProviderHandler: Session needs refresh, initializing...")
            await self._initialize_session()
    
    def _update_session_from_headers(self, headers: Dict):
        """Update session state from response headers."""
        import logging
        logger = logging.getLogger(__name__)
        
        if 'anthropic-ratelimit-unified-5h-utilization' in headers:
            old_util = self.session_state.get('quota_5h_utilization')
            new_util = headers.get('anthropic-ratelimit-unified-5h-utilization')
            
            self.session_state.update({
                'quota_5h_reset': headers.get('anthropic-ratelimit-unified-5h-reset'),
                'quota_5h_utilization': new_util,
                'quota_7d_reset': headers.get('anthropic-ratelimit-unified-7d-reset'),
                'quota_7d_utilization': headers.get('anthropic-ratelimit-unified-7d-utilization'),
                'representative_claim': headers.get('anthropic-ratelimit-unified-representative-claim'),
                'status': headers.get('anthropic-ratelimit-unified-status'),
            })
            
            if old_util != new_util:
                logger.debug(f"ClaudeProviderHandler: Quota utilization updated: {old_util} -> {new_util}")
    
    async def _get_sdk_client(self):
        """Get or create an Anthropic SDK client configured with OAuth2 auth token."""
        import logging
        logger = logging.getLogger(__name__)

        access_token = await self.auth.get_valid_token()
        
        if not access_token:
            logger.error("ClaudeProviderHandler: No OAuth2 access token available")
            raise Exception("No OAuth2 access token. Please re-authenticate with /login")
        
        self._sdk_client = Anthropic(
            auth_token=access_token,
            max_retries=3,
            timeout=httpx.Timeout(300.0, connect=30.0),
        )
        
        logger.info("ClaudeProviderHandler: Created SDK client with OAuth2 auth token")
        return self._sdk_client
    
    async def _get_auth_headers(self, stream: bool = False):
        """Get HTTP headers with OAuth2 Bearer token."""
        import logging
        import uuid
        import platform
        logger = logging.getLogger(__name__)

        access_token = await self.auth.get_valid_token()
        
        if not self.session_state.get('session_id'):
            self.session_state['session_id'] = str(uuid.uuid4())
        
        session_id = self.session_state['session_id']
        request_id = str(uuid.uuid4())
        
        headers = {
            'accept': 'application/json',
            'anthropic-beta': 'oauth-2025-04-20,interleaved-thinking-2025-05-14,redact-thinking-2026-02-12,context-management-2025-06-27,prompt-caching-scope-2026-01-05,structured-outputs-2025-12-15',
            'anthropic-dangerous-direct-browser-access': 'true',
            'anthropic-version': '2023-06-01',
            'authorization': f'Bearer {access_token}',
            'content-type': 'application/json',
            'user-agent': 'claude-cli/99.0.0 (undefined, cli)',
            'x-app': 'cli',
            'x-claude-code-session-id': session_id,
            'x-client-request-id': request_id,
            'x-stainless-arch': platform.machine() or 'x64',
            'x-stainless-lang': 'js',
            'x-stainless-os': platform.system() or 'Linux',
            'x-stainless-package-version': '0.81.0',
            'x-stainless-retry-count': '0',
            'x-stainless-runtime': 'node',
            'x-stainless-runtime-version': 'v22.22.0',
            'x-stainless-timeout': '600',
        }
        
        if stream:
            headers['accept'] = 'text/event-stream'
            headers['accept-encoding'] = 'identity'
        else:
            headers['accept-encoding'] = 'gzip, deflate, br, zstd'
        
        logger.info("ClaudeProviderHandler: Created auth headers matching claude-cli client")
        logger.debug(f"ClaudeProviderHandler: Session ID: {session_id}, Request ID: {request_id}")
        
        import json
        logger.debug(f"ClaudeProviderHandler: Full headers: {json.dumps(headers, indent=2)}")
        return headers
    
    def _sanitize_tool_call_id(self, tool_call_id: str) -> str:
        """Sanitize tool call ID for Claude API compatibility."""
        import re
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', tool_call_id)
        return sanitized
    
    def _filter_empty_content(self, content: Union[str, List, None]) -> Union[str, List, None]:
        """Filter empty content from messages for Claude API compatibility."""
        if content is None:
            return None
        
        if isinstance(content, str):
            if content.strip() == "":
                return None
            return content
        
        if isinstance(content, list):
            filtered = []
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get('type', '')
                    if block_type == 'text':
                        text = block.get('text', '')
                        if text and text.strip():
                            filtered.append(block)
                    else:
                        filtered.append(block)
                else:
                    filtered.append(block)
            
            if not filtered:
                return None
            return filtered
        
        return content
    
    def _apply_cache_control(self, anthropic_messages: List[Dict], enable_caching: bool = True) -> List[Dict]:
        """Apply ephemeral cache_control to messages for prompt caching."""
        if not enable_caching or not anthropic_messages:
            return anthropic_messages
        
        import logging
        logger = logging.getLogger(__name__)
        
        if len(anthropic_messages) < 4:
            logger.debug(f"ClaudeProviderHandler: Skipping cache control (only {len(anthropic_messages)} messages)")
            return anthropic_messages
        
        cache_indices = []
        
        for i in range(max(0, len(anthropic_messages) - 2), len(anthropic_messages)):
            cache_indices.append(i)
        
        for idx in cache_indices:
            msg = anthropic_messages[idx]
            content = msg.get('content')
            
            if isinstance(content, str):
                if content.strip():
                    msg['content'] = [
                        {
                            'type': 'text',
                            'text': content,
                            'cache_control': {'type': 'ephemeral'}
                        }
                    ]
                    logger.debug(f"ClaudeProviderHandler: Applied cache_control to message {idx} (string content)")
            elif isinstance(content, list) and content:
                last_block = content[-1]
                if isinstance(last_block, dict):
                    last_block['cache_control'] = {'type': 'ephemeral'}
                    logger.debug(f"ClaudeProviderHandler: Applied cache_control to message {idx} (list content)")
        
        logger.info(f"ClaudeProviderHandler: Applied cache_control to {len(cache_indices)} messages for prompt caching")
        return anthropic_messages
    
    def _validate_messages(self, messages: List[Dict]) -> List[Dict]:
        """Validate and normalize message roles for Claude API compatibility."""
        import logging
        logger = logging.getLogger(__name__)
        
        if not messages:
            return messages
        
        valid_roles = {'user', 'assistant', 'system', 'tool'}
        normalized = []
        issues_found = 0
        
        for i, msg in enumerate(messages):
            role = msg.get('role', '')
            content = msg.get('content', '')
            
            if role not in valid_roles:
                logger.warning(f"ClaudeProviderHandler: Unknown message role '{role}' at index {i}, treating as 'user'")
                msg['role'] = 'user'
                role = 'user'
                issues_found += 1
            
            if role == 'system' and i > 0:
                logger.warning(f"ClaudeProviderHandler: System message at index {i} (not at start), converting to user")
                msg['role'] = 'user'
                role = 'user'
                issues_found += 1
            
            if role == 'tool':
                tool_call_id = msg.get('tool_call_id') or msg.get('name')
                if not tool_call_id:
                    logger.warning(f"ClaudeProviderHandler: Tool message at index {i} missing tool_call_id, adding placeholder")
                    msg['tool_call_id'] = f"placeholder_{i}"
                    issues_found += 1
            
            if normalized:
                last_role = normalized[-1].get('role', '')
                
                if role == 'user' and last_role == 'user':
                    logger.debug(f"ClaudeProviderHandler: Inserting synthetic assistant message between consecutive user messages at index {i}")
                    normalized.append({
                        'role': 'assistant',
                        'content': '(empty)'
                    })
                    issues_found += 1
                
                elif role == 'assistant' and last_role == 'assistant':
                    logger.debug(f"ClaudeProviderHandler: Merging consecutive assistant messages at index {i}")
                    prev_content = normalized[-1].get('content', '')
                    if isinstance(prev_content, str) and isinstance(content, str):
                        normalized[-1]['content'] = f"{prev_content}\n{content}"
                    else:
                        normalized[-1]['content'] = content
                    issues_found += 1
                    continue
            
            normalized.append(msg.copy())
        
        if issues_found:
            logger.info(f"ClaudeProviderHandler: Message validation fixed {issues_found} issue(s)")
        
        return normalized
    
    def _truncate_tool_result(self, content: str, max_chars: int = 100000) -> tuple:
        """Truncate tool result content if it exceeds the size limit."""
        import logging
        logger = logging.getLogger(__name__)
        
        if not content or len(content) <= max_chars:
            return content, False
        
        truncation_notice = f"\n\n[Tool result truncated: exceeded {max_chars} character limit. Original length: {len(content)} characters.]"
        truncated = content[:max_chars - len(truncation_notice)] + truncation_notice
        
        logger.warning(f"ClaudeProviderHandler: Tool result truncated from {len(content)} to {max_chars} characters")
        return truncated, True
    
    def _get_cache_config(self, user_id: int = None, provider_id: str = None, model_name: str = None) -> Dict:
        """Get prompt caching configuration from provider config and user settings."""
        cache_config = {
            'enabled': False,
            'min_messages': 4,
        }
        
        if self.provider_config:
            if isinstance(self.provider_config, dict):
                claude_config = self.provider_config.get('claude_config')
            else:
                claude_config = getattr(self.provider_config, 'claude_config', None)
            
            if claude_config and isinstance(claude_config, dict):
                cache_config['enabled'] = claude_config.get('enable_prompt_caching', False)
                cache_config['min_messages'] = claude_config.get('cache_min_messages', 4)
        
        # Check user's cache settings (overrides provider config)
        if user_id and cache_config['enabled']:
            try:
                from aisbf.database import DatabaseRegistry
                db = DatabaseRegistry.get_config_database()
                user_setting = db.get_user_cache_settings(user_id, provider_id, model_name)
                if not user_setting['cache_enabled']:
                    cache_config['enabled'] = False
                    import logging
                    logging.getLogger(__name__).info(f"User {user_id} disabled cache for provider={provider_id}, model={model_name}")
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Error checking user cache settings: {e}")
        
        return cache_config
    
    def _get_fallback_models(self) -> List[str]:
        """Get list of fallback models from provider config."""
        fallback_models = []
        
        if self.provider_config:
            if isinstance(self.provider_config, dict):
                claude_config = self.provider_config.get('claude_config')
            else:
                claude_config = getattr(self.provider_config, 'claude_config', None)
            
            if claude_config and isinstance(claude_config, dict):
                fallback_models = claude_config.get('fallback_models', [])
        
        return fallback_models
    
    def _convert_tool_choice_to_anthropic(self, tool_choice: Optional[Union[str, Dict]]) -> Optional[Dict]:
        """Convert OpenAI tool_choice format to Anthropic format."""
        import logging
        
        if not tool_choice:
            return None
        
        if isinstance(tool_choice, str):
            if tool_choice == "auto":
                return {"type": "auto"}
            elif tool_choice == "none":
                return None
            elif tool_choice == "required":
                return {"type": "any"}
            else:
                logging.warning(f"Unknown tool_choice string: {tool_choice}, using auto")
                return {"type": "auto"}
        
        if isinstance(tool_choice, dict):
            if tool_choice.get("type") == "function":
                function = tool_choice.get("function", {})
                tool_name = function.get("name")
                if tool_name:
                    return {"type": "tool", "name": tool_name}
                else:
                    logging.warning(f"tool_choice dict missing function name: {tool_choice}")
                    return {"type": "auto"}
            else:
                logging.warning(f"Unknown tool_choice dict format: {tool_choice}, passing through")
                return tool_choice
        
        logging.warning(f"Unknown tool_choice type: {type(tool_choice)}, using auto")
        return {"type": "auto"}
    
    def _convert_tools_to_anthropic(self, tools: Optional[List[Dict]]) -> Optional[List[Dict]]:
        """Convert OpenAI tools format to Anthropic format."""
        import logging
        
        if not tools:
            return None
        
        def normalize_schema(schema: Dict) -> Dict:
            """Recursively normalize JSON Schema for Anthropic compatibility."""
            if not isinstance(schema, dict):
                return schema
            
            result = {}
            for key, value in schema.items():
                if key == "type" and isinstance(value, list):
                    non_null_types = [t for t in value if t != "null"]
                    if len(non_null_types) == 1:
                        result[key] = non_null_types[0]
                    elif len(non_null_types) > 1:
                        result[key] = non_null_types
                    else:
                        result[key] = "string"
                elif key == "properties" and isinstance(value, dict):
                    result[key] = {k: normalize_schema(v) for k, v in value.items()}
                elif key == "items" and isinstance(value, dict):
                    result[key] = normalize_schema(value)
                elif key == "additionalProperties" and value is False:
                    continue
                elif key == "required" and isinstance(value, list):
                    properties = schema.get("properties", {})
                    cleaned_required = []
                    for field in value:
                        if field in properties:
                            field_schema = properties[field]
                            if isinstance(field_schema, dict):
                                field_type = field_schema.get("type")
                                if isinstance(field_type, list) and "null" in field_type:
                                    continue
                            cleaned_required.append(field)
                    if cleaned_required:
                        result[key] = cleaned_required
                else:
                    result[key] = value
            
            return result
        
        anthropic_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                function = tool.get("function", {})
                parameters = function.get("parameters", {})
                
                normalized_schema = normalize_schema(parameters)
                
                anthropic_tool = {
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "input_schema": normalized_schema
                }
                anthropic_tools.append(anthropic_tool)
                logging.info(f"Converted tool to Anthropic format: {anthropic_tool['name']}")
            else:
                logging.warning(f"Unknown tool type: {tool.get('type')}, skipping")
        
        return anthropic_tools if anthropic_tools else None
    
    def _extract_images_from_content(self, content: Union[str, List, None]) -> List[Dict]:
        """Extract images from OpenAI message content format."""
        import logging
        logger = logging.getLogger(__name__)
        
        if not isinstance(content, list):
            return []
        
        images = []
        max_image_size = 5 * 1024 * 1024
        
        for block in content:
            if not isinstance(block, dict):
                continue
            
            block_type = block.get('type', '')
            
            if block_type == 'image_url':
                image_url_obj = block.get('image_url', {})
                url = image_url_obj.get('url', '') if isinstance(image_url_obj, dict) else ''
                
                if not url:
                    logger.warning("ClaudeProviderHandler: Empty image URL in content block")
                    continue
                
                if url.startswith('data:'):
                    try:
                        header, data = url.split(',', 1)
                        media_part = header.split(';')[0]
                        media_type = media_part.replace('data:', '')
                        
                        if len(data) > max_image_size:
                            logger.warning(f"ClaudeProviderHandler: Image too large ({len(data)} bytes), skipping")
                            continue
                        
                        image_block = {
                            'type': 'image',
                            'source': {
                                'type': 'base64',
                                'media_type': media_type,
                                'data': data
                            }
                        }
                        images.append(image_block)
                        logger.debug(f"ClaudeProviderHandler: Extracted base64 image ({media_type}, {len(data)} bytes)")
                        
                    except (ValueError, IndexError) as e:
                        logger.warning(f"ClaudeProviderHandler: Failed to parse data URL: {e}")
                
                elif url.startswith(('http://', 'https://')):
                    image_block = {
                        'type': 'image',
                        'source': {
                            'type': 'url',
                            'url': url
                        }
                    }
                    images.append(image_block)
                    logger.debug(f"ClaudeProviderHandler: Extracted URL image: {url[:80]}...")
                
                else:
                    logger.warning(f"ClaudeProviderHandler: Unsupported image URL format: {url[:80]}...")
            
            elif block_type == 'image':
                if 'source' in block:
                    images.append(block)
                    logger.debug("ClaudeProviderHandler: Passed through existing image block")
        
        return images
    
    def _convert_messages_to_anthropic(self, messages: List[Dict]) -> tuple:
        """
        Convert OpenAI messages format to Anthropic format.
        Delegates to shared AnthropicFormatConverter.convert_messages_to_anthropic().
        """
        return AnthropicFormatConverter.convert_messages_to_anthropic(messages, sanitize_ids=True)
    
    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        # Get fallback models from config (Phase 3.3)
        fallback_models = self._get_fallback_models()
        models_to_try = [model] + fallback_models
        
        last_error = None
        
        for attempt, current_model in enumerate(models_to_try):
            try:
                if attempt > 0:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"ClaudeProviderHandler: Retrying with fallback model: {current_model} (original: {model})")
                
                result = await self._handle_request_with_model(
                    model=current_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=stream,
                    tools=tools,
                    tool_choice=tool_choice
                )
                
                if stream:
                    return self._wrap_streaming_with_retry(result, current_model, messages, max_tokens, temperature, tools, tool_choice, models_to_try, attempt)
                
                return result
                
            except Exception as e:
                last_error = e
                import logging
                logger = logging.getLogger(__name__)
                
                error_str = str(e).lower()
                is_retryable = any(keyword in error_str for keyword in [
                    'rate limit', 'overloaded', 'too many requests', '429', '529', '503'
                ])
                
                if is_retryable and attempt < len(models_to_try) - 1:
                    logger.warning(f"ClaudeProviderHandler: Retryable error with {current_model}, trying next fallback model")
                    wait_time = min(2 ** attempt + random.uniform(0, 1), 30)
                    logger.info(f"ClaudeProviderHandler: Waiting {wait_time:.1f}s before retry")
                    await asyncio.sleep(wait_time)
                    continue
                
                logger.error(f"ClaudeProviderHandler: Error with model {current_model}: {str(e)}", exc_info=True)
                self.record_failure()
                raise e
        
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"ClaudeProviderHandler: All models failed (tried: {models_to_try})")
        raise last_error
    
    async def _wrap_streaming_with_retry(self, stream_generator, current_model, messages, max_tokens, temperature, tools, tool_choice, models_to_try, attempt):
        """Wrapper that consumes the streaming generator and catches errors."""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            async for chunk in stream_generator:
                yield chunk
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            is_retryable = any(keyword in error_str for keyword in [
                'rate limit', 'overloaded', 'too many requests', '429', '529', '503'
            ])
            
            if is_retryable and attempt < len(models_to_try) - 1:
                next_model = models_to_try[attempt + 1]
                logger.warning(f"ClaudeProviderHandler: Streaming error with {current_model}, retrying with {next_model}")
                
                wait_time = min(2 ** (attempt + 1) + random.uniform(0, 1), 30)
                logger.info(f"ClaudeProviderHandler: Waiting {wait_time:.1f}s before retry")
                await asyncio.sleep(wait_time)
                
                try:
                    result = await self._handle_request_with_model(
                        model=next_model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        stream=True,
                        tools=tools,
                        tool_choice=tool_choice
                    )
                    async for chunk in self._wrap_streaming_with_retry(result, next_model, messages, max_tokens, temperature, tools, tool_choice, models_to_try, attempt + 1):
                        yield chunk
                    return
                except Exception as retry_error:
                    logger.error(f"ClaudeProviderHandler: Retry with {next_model} also failed: {str(retry_error)}")
                    raise retry_error
            
            logger.error(f"ClaudeProviderHandler: Streaming error: {str(e)}", exc_info=True)
            raise e
    
    async def _handle_request_with_model(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                                        temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                                        tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        """Handle request with a specific model using direct HTTP requests."""
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        logger.info(f"ClaudeProviderHandler: Handling request for model {model} (Direct HTTP mode)")
        
        if AISBF_DEBUG:
            logger.info(f"ClaudeProviderHandler: Messages: {messages}")
        else:
            logger.info(f"ClaudeProviderHandler: Messages count: {len(messages)}")

        await self._ensure_session()
        await self.apply_rate_limit()
        
        validated_messages = self._validate_messages(messages)
        
        system_message, anthropic_messages = self._convert_messages_to_anthropic(validated_messages)
        
        # Apply prompt caching based on user and provider settings
        cache_config = self._get_cache_config(
            user_id=getattr(self, 'user_id', None),
            provider_id=self.provider_id,
            model_name=model
        )
        
        if cache_config['enabled']:
            anthropic_messages = self._apply_cache_control(anthropic_messages)
        
        # Sanitize system message to avoid Claude's unofficial client detection
        # Replace "You are Kilo," or "You are Kiro," with "You are" to prevent
        # contradiction with "You are Claude Code" that triggers detection
        if system_message:
            import re
            system_message = re.sub(
                r'\bYou are (Kilo|Kiro),',
                'You are',
                system_message,
                flags=re.IGNORECASE
            )
        
        payload = {
            'model': model,
            'messages': anthropic_messages,
            'max_tokens': max_tokens or 4096,
        }
        
        if temperature is not None and temperature > 0:
            payload['temperature'] = temperature
        
        if system_message:
            billing_header = {
                'type': 'text',
                'text': 'x-anthropic-billing-header: cc_version=99.0.0.e8c; cc_entrypoint=cli;'
            }
            claude_intro = {
                'type': 'text',
                'text': 'You are Claude Code, Anthropic\'s official CLI for Claude.'
            }
            user_system = {
                'type': 'text',
                'text': system_message
            }
            payload['system'] = [billing_header, claude_intro, user_system]
        
        payload['metadata'] = {
            'user_id': json.dumps({
                'device_id': self.session_state['device_id'],
                'account_uuid': self.session_state['account_uuid'],
                'session_id': self.session_state['session_id']
            })
        }
        
        if tools:
            anthropic_tools = self._convert_tools_to_anthropic(tools)
            if anthropic_tools:
                payload['tools'] = anthropic_tools
        
        if tool_choice and tools:
            anthropic_tool_choice = self._convert_tool_choice_to_anthropic(tool_choice)
            if anthropic_tool_choice:
                payload['tool_choice'] = anthropic_tool_choice
        
        headers = await self._get_auth_headers(stream=stream)
        api_url = 'https://api.anthropic.com/v1/messages?beta=true'
        
        logger.info(f"ClaudeProviderHandler: Request payload keys: {list(payload.keys())}")
        if AISBF_DEBUG:
            logger.info(f"ClaudeProviderHandler: Full payload: {json.dumps(payload, indent=2)}")
        
        try:
            if stream:
                payload['stream'] = True
                logger.info(f"ClaudeProviderHandler: Using direct HTTP streaming mode")
                return self._handle_streaming_request_with_retry(api_url, payload, headers, model)
            else:
                logger.info(f"ClaudeProviderHandler: Using direct HTTP non-streaming mode")
                response = await self._request_with_retry(api_url, headers, payload, max_retries=3)
                
                logger.info(f"ClaudeProviderHandler: HTTP response received successfully")
                
                self._update_session_from_headers(dict(response.headers))
                
                self.record_success()
                
                response_data = response.json()
                
                if AISBF_DEBUG:
                    logger.info(f"=== RAW CLAUDE RESPONSE ===")
                    logger.info(f"Raw response data: {json.dumps(response_data, indent=2, default=str)}")
                    logger.info(f"=== END RAW CLAUDE RESPONSE ===")
                
                openai_response = self._convert_to_openai_format(response_data, model)
                
                if AISBF_DEBUG:
                    logger.info(f"=== FINAL CLAUDE RESPONSE DICT ===")
                    logger.info(f"Final response: {json.dumps(openai_response, indent=2, default=str)}")
                    logger.info(f"=== END FINAL CLAUDE RESPONSE DICT ===")
                
                return openai_response
                
        except Exception as e:
            logger.error(f"ClaudeProviderHandler: HTTP request failed: {e}", exc_info=True)
            raise
    
    async def _request_with_retry(self, api_url: str, headers: Dict, payload: Dict, max_retries: int = 3):
        """Non-streaming request with automatic retry for transient errors."""
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await self.client.post(api_url, headers=headers, json=payload)
                
                logger.info(f"ClaudeProviderHandler: Response status: {response.status_code} (attempt {attempt + 1}/{max_retries})")
                
                if response.status_code in (429, 529, 503):
                    should_retry = response.headers.get('x-should-retry', 'false').lower() == 'true'
                    
                    if should_retry or response.status_code in (529, 503):
                        if attempt < max_retries - 1:
                            wait_time = min(2 ** attempt + random.uniform(0, 1), 30)
                            
                            try:
                                error_data = response.json()
                                error_message = error_data.get('error', {}).get('message', '')
                                logger.warning(f"ClaudeProviderHandler: Retryable error: {error_message}")
                            except Exception:
                                pass
                            
                            logger.info(f"ClaudeProviderHandler: Retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            try:
                                response_data = response.json()
                            except Exception:
                                response_data = response.text
                            
                            self.handle_429_error(response_data, dict(response.headers))
                            response.raise_for_status()
                
                if response.status_code >= 400:
                    try:
                        error_body = response.json()
                        error_message = error_body.get('error', {}).get('message', 'Unknown error')
                        error_type = error_body.get('error', {}).get('type', 'unknown')
                        logger.error(f"ClaudeProviderHandler: API error response: {json.dumps(error_body, indent=2)}")
                        logger.error(f"ClaudeProviderHandler: Error type: {error_type}")
                        logger.error(f"ClaudeProviderHandler: Error message: {error_message}")
                    except Exception:
                        logger.error(f"ClaudeProviderHandler: API error response (text): {response.text}")
                    
                    response.raise_for_status()
                
                return response
                
            except httpx.TimeoutException as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = min(2 ** attempt + random.uniform(0, 1), 30)
                    logger.warning(f"ClaudeProviderHandler: Request timeout, retrying in {wait_time:.1f}s")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"ClaudeProviderHandler: Request timeout after {max_retries} attempts")
                    raise
            
            except httpx.HTTPError as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = min(2 ** attempt + random.uniform(0, 1), 30)
                    logger.warning(f"ClaudeProviderHandler: HTTP error, retrying in {wait_time:.1f}s: {e}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"ClaudeProviderHandler: HTTP error after {max_retries} attempts: {e}")
                    raise
        
        raise last_error or Exception("Request failed after max retries")
    
    async def _handle_streaming_request_with_retry(self, api_url: str, payload: Dict, headers: Dict, model: str):
        """Wrapper for streaming request that catches rate limit errors at the call site."""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            async for chunk in self._handle_streaming_request(api_url, payload, headers, model):
                yield chunk
        except Exception as e:
            error_str = str(e).lower()
            if '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str:
                logger.error(f"ClaudeProviderHandler: Streaming rate limit error: {e}")
                raise Exception(f"Rate limit error: {e}")
            raise
    
    async def _handle_streaming_request(self, api_url: str, payload: Dict, headers: Dict, model: str):
        """Handle streaming request to Claude API using direct HTTP."""
        import logging
        import json
        
        logger = logging.getLogger(__name__)
        logger.info(f"ClaudeProviderHandler: Starting streaming request to {api_url}")
        
        if AISBF_DEBUG:
            logger.info(f"=== STREAMING REQUEST DETAILS ===")
            logger.info(f"URL: {api_url}")
            logger.info(f"Headers (auth redacted): {json.dumps({k: v for k, v in headers.items() if k.lower() != 'authorization'}, indent=2)}")
            logger.info(f"Payload: {json.dumps(payload, indent=2)}")
            logger.info(f"=== END STREAMING REQUEST DETAILS ===")
        
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as streaming_client:
            async with streaming_client.stream(
                "POST",
                api_url,
                headers=headers,
                json=payload
            ) as response:
                logger.info(f"ClaudeProviderHandler: Streaming response status: {response.status_code}")
                
                self._update_session_from_headers(dict(response.headers))
                
                if response.status_code >= 400:
                    error_text = await response.aread()
                    logger.error(f"ClaudeProviderHandler: Streaming error response: {error_text}")
                    
                    try:
                        error_json = json.loads(error_text)
                        error_message = error_json.get('error', {}).get('message', 'Unknown error')
                        error_type = error_json.get('error', {}).get('type', 'unknown')
                        logger.error(f"ClaudeProviderHandler: Error type: {error_type}")
                        logger.error(f"ClaudeProviderHandler: Error message: {error_message}")
                        
                        if response.status_code == 429:
                            raise Exception(f"Rate limit error (429): {error_type} - {error_message}")
                        else:
                            raise Exception(f"Claude API error ({response.status_code}): {error_message}")
                    except json.JSONDecodeError:
                        logger.error(f"ClaudeProviderHandler: Could not parse error response as JSON")
                        if response.status_code == 429:
                            raise Exception(f"Rate limit error (429): Too Many Requests - {error_text.decode() if isinstance(error_text, bytes) else error_text}")
                        else:
                            raise Exception(f"Claude API error: {response.status_code} - {error_text.decode() if isinstance(error_text, bytes) else error_text}")
                
                completion_id = f"claude-{int(time.time())}"
                created_time = int(time.time())
                
                first_chunk = True
                accumulated_content = ""
                accumulated_tool_calls = []
                
                accumulated_thinking = ""
                thinking_signature = ""
                is_redacted_thinking = False
                
                content_block_index = 0
                current_tool_calls = []
                
                last_event_time = time.time()
                idle_timeout = self.stream_idle_timeout
                
                stream_stop_reason = None
                
                async for line in response.aiter_lines():
                    if time.time() - last_event_time > idle_timeout:
                        logger.error(f"ClaudeProviderHandler: Stream idle timeout ({idle_timeout}s)")
                        raise TimeoutError(f"Stream idle for {idle_timeout}s")
                    
                    if not line or not line.startswith('data: '):
                        continue
                    
                    data_str = line[6:]
                    
                    if data_str == '[DONE]':
                        break
                    
                    try:
                        chunk_data = json.loads(data_str)
                        
                        last_event_time = time.time()
                        
                        event_type = chunk_data.get('type')
                        
                        if event_type == 'content_block_start':
                            content_block = chunk_data.get('content_block', {})
                            block_type = content_block.get('type', '')
                            
                            if block_type == 'tool_use':
                                tool_call = {
                                    'index': content_block_index,
                                    'id': content_block.get('id', ''),
                                    'type': 'function',
                                    'function': {
                                        'name': content_block.get('name', ''),
                                        'arguments': ''
                                    }
                                }
                                current_tool_calls.append(tool_call)
                                logger.debug(f"ClaudeProviderHandler: Tool use block started: {tool_call['function']['name']}")
                            
                            elif block_type == 'thinking':
                                accumulated_thinking = ""
                                is_redacted_thinking = False
                                thinking_signature = ""
                                logger.debug(f"ClaudeProviderHandler: Thinking block started")
                            
                            elif block_type == 'redacted_thinking':
                                accumulated_thinking = ""
                                is_redacted_thinking = True
                                thinking_signature = ""
                                logger.debug(f"ClaudeProviderHandler: Redacted thinking block started")
                            
                            content_block_index += 1
                        
                        elif event_type == 'content_block_delta':
                            delta = chunk_data.get('delta', {})
                            delta_type = delta.get('type', '')
                            
                            if delta_type == 'text_delta':
                                text = delta.get('text', '')
                                accumulated_content += text
                                
                                openai_delta = {'content': text}
                                if first_chunk:
                                    openai_delta['role'] = 'assistant'
                                    first_chunk = False
                                
                                openai_chunk = {
                                    'id': completion_id,
                                    'object': 'chat.completion.chunk',
                                    'created': created_time,
                                    'model': f'{self.provider_id}/{model}',
                                    'choices': [{
                                        'index': 0,
                                        'delta': openai_delta,
                                        'finish_reason': None
                                    }]
                                }
                                
                                yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                            
                            elif delta_type == 'input_json_delta':
                                partial_json = delta.get('partial_json', '')
                                if current_tool_calls:
                                    current_tool_calls[-1]['function']['arguments'] += partial_json
                            
                            elif delta_type == 'thinking_delta':
                                thinking_text = delta.get('thinking', '')
                                accumulated_thinking += thinking_text
                                logger.debug(f"ClaudeProviderHandler: Thinking delta: {len(thinking_text)} chars")
                            
                            elif delta_type == 'signature_delta':
                                signature = delta.get('signature', '')
                                thinking_signature = signature
                                logger.debug(f"ClaudeProviderHandler: Thinking signature received")
                        
                        elif event_type == 'content_block_stop':
                            if current_tool_calls:
                                tool_call = current_tool_calls[-1]
                                try:
                                    args = json.loads(tool_call['function']['arguments']) if tool_call['function']['arguments'] else {}
                                    tool_call['function']['arguments'] = json.dumps(args)
                                except json.JSONDecodeError:
                                    logger.warning(f"ClaudeProviderHandler: Invalid tool call arguments JSON")
                                    tool_call['function']['arguments'] = '{}'
                                
                                tool_call_chunk = {
                                    'id': completion_id,
                                    'object': 'chat.completion.chunk',
                                    'created': created_time,
                                    'model': f'{self.provider_id}/{model}',
                                    'choices': [{
                                        'index': 0,
                                        'delta': {
                                            'tool_calls': [{
                                                'index': tool_call['index'],
                                                'id': tool_call['id'],
                                                'type': tool_call['type'],
                                                'function': tool_call['function']
                                            }]
                                        },
                                        'finish_reason': None
                                    }]
                                }
                                
                                yield f"data: {json.dumps(tool_call_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                                logger.debug(f"ClaudeProviderHandler: Emitted tool call: {tool_call['function']['name']}")
                            
                            elif accumulated_thinking:
                                block_type = "redacted_thinking" if is_redacted_thinking else "thinking"
                                logger.info(f"ClaudeProviderHandler: {block_type} block completed ({len(accumulated_thinking)} chars)")
                                accumulated_thinking = ""
                                is_redacted_thinking = False
                                thinking_signature = ""
                        
                        elif event_type == 'message_delta':
                            delta_data = chunk_data.get('delta', {})
                            usage = chunk_data.get('usage', {})
                            
                            stream_stop_reason = delta_data.get('stop_reason')
                            if stream_stop_reason:
                                logger.debug(f"ClaudeProviderHandler: Stream stop_reason: {stream_stop_reason}")
                            
                            if usage:
                                logger.debug(f"ClaudeProviderHandler: Streaming usage update: {usage}")
                                
                                cache_read = usage.get('cache_read_input_tokens', 0)
                                cache_creation = usage.get('cache_creation_input_tokens', 0)
                                if cache_read > 0:
                                    self.cache_stats['cache_hits'] += 1
                                    self.cache_stats['cache_tokens_read'] += cache_read
                                if cache_creation > 0:
                                    self.cache_stats['cache_misses'] += 1
                                    self.cache_stats['cache_tokens_created'] += cache_creation
                        
                        elif event_type == 'message_stop':
                            stop_reason_map = {
                                'end_turn': 'stop',
                                'max_tokens': 'length',
                                'stop_sequence': 'stop',
                                'tool_use': 'tool_calls'
                            }
                            if stream_stop_reason:
                                finish_reason = stop_reason_map.get(stream_stop_reason, 'stop')
                            elif current_tool_calls:
                                finish_reason = 'tool_calls'
                            else:
                                finish_reason = 'stop'
                            logger.debug(f"ClaudeProviderHandler: Final finish_reason: {finish_reason}")
                            
                            final_chunk = {
                                'id': completion_id,
                                'object': 'chat.completion.chunk',
                                'created': created_time,
                                'model': f'{self.provider_id}/{model}',
                                'choices': [{
                                    'index': 0,
                                    'delta': {},
                                    'finish_reason': finish_reason
                                }]
                            }
                            
                            yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                            # Yield control to event loop to ensure chunk is flushed to client
                            await asyncio.sleep(0)
                            yield b"data: [DONE]\n\n"
                            # Final flush to ensure all buffered data reaches the client
                            await asyncio.sleep(0)
                    
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse streaming chunk: {e}")
                        continue
    
    def _convert_to_openai_format(self, claude_response: Dict, model: str) -> Dict:
        """Convert Claude API response to OpenAI format."""
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        logger.info(f"ClaudeProviderHandler: Converting response to OpenAI format")
        
        content_text = ""
        tool_calls = []
        thinking_text = ""
        
        if 'content' in claude_response:
            for block in claude_response['content']:
                block_type = block.get('type', '')
                
                if block_type == 'text':
                    content_text += block.get('text', '')
                elif block_type == 'tool_use':
                    tool_calls.append({
                        'id': block.get('id', f"call_{len(tool_calls)}"),
                        'type': 'function',
                        'function': {
                            'name': block.get('name', ''),
                            'arguments': json.dumps(block.get('input', {}))
                        }
                    })
                elif block_type == 'thinking':
                    thinking_text = block.get('thinking', '')
                    logger.debug(f"ClaudeProviderHandler: Extracted thinking block ({len(thinking_text)} chars)")
                elif block_type == 'redacted_thinking':
                    logger.debug(f"ClaudeProviderHandler: Found redacted_thinking block")
        
        stop_reason_map = {
            'end_turn': 'stop',
            'max_tokens': 'length',
            'stop_sequence': 'stop',
            'tool_use': 'tool_calls'
        }
        stop_reason = claude_response.get('stop_reason', 'end_turn')
        finish_reason = stop_reason_map.get(stop_reason, 'stop')
        
        usage = claude_response.get('usage', {})
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        cache_read_tokens = usage.get('cache_read_input_tokens', 0)
        cache_creation_tokens = usage.get('cache_creation_input_tokens', 0)
        
        if cache_read_tokens or cache_creation_tokens:
            logger.info(f"ClaudeProviderHandler: Cache usage - read: {cache_read_tokens}, creation: {cache_creation_tokens}")
        
        openai_response = {
            'id': f"claude-{model}-{int(time.time())}",
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': f'{self.provider_id}/{model}',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': content_text if content_text else None
                },
                'finish_reason': finish_reason
            }],
            'usage': {
                'prompt_tokens': input_tokens,
                'completion_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                'prompt_tokens_details': {
                    'cached_tokens': cache_read_tokens,
                    'audio_tokens': 0
                },
                'completion_tokens_details': {
                    'reasoning_tokens': 0,
                    'audio_tokens': 0
                }
            }
        }
        
        if tool_calls:
            openai_response['choices'][0]['message']['tool_calls'] = tool_calls
        
        if thinking_text:
            openai_response['choices'][0]['message']['provider_options'] = {
                'anthropic': {
                    'thinking': thinking_text
                }
            }
            logger.debug(f"ClaudeProviderHandler: Added thinking content to response ({len(thinking_text)} chars)")
        
        return openai_response
    
    def _convert_sdk_response_to_openai(self, response, model: str) -> Dict:
        """Convert Anthropic SDK response object to OpenAI format."""
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        message_content = ""
        tool_calls = []
        thinking_text = ""
        
        for block in response.content:
            block_type = getattr(block, 'type', '')
            
            if block_type == 'text' or hasattr(block, 'text'):
                message_content += getattr(block, 'text', '')
            elif block_type == 'tool_use':
                tool_calls.append({
                    'id': getattr(block, 'id', f"call_{len(tool_calls)}"),
                    'type': 'function',
                    'function': {
                        'name': getattr(block, 'name', ''),
                        'arguments': json.dumps(getattr(block, 'input', {}))
                    }
                })
            elif block_type == 'thinking':
                thinking_text = getattr(block, 'thinking', '')
                logger.debug(f"ClaudeProviderHandler: Extracted thinking block ({len(thinking_text)} chars)")
            elif block_type == 'redacted_thinking':
                logger.debug(f"ClaudeProviderHandler: Found redacted_thinking block")
        
        stop_reason_map = {
            'end_turn': 'stop',
            'max_tokens': 'length',
            'stop_sequence': 'stop',
            'tool_use': 'tool_calls'
        }
        stop_reason = getattr(response, 'stop_reason', 'end_turn') or 'end_turn'
        finish_reason = stop_reason_map.get(stop_reason, 'stop')
        
        usage = getattr(response, 'usage', None)
        input_tokens = getattr(usage, 'input_tokens', 0) if usage else 0
        output_tokens = getattr(usage, 'output_tokens', 0) if usage else 0
        cache_read_tokens = getattr(usage, 'cache_read_input_tokens', 0) if usage else 0
        cache_creation_tokens = getattr(usage, 'cache_creation_input_tokens', 0) if usage else 0
        
        if cache_read_tokens or cache_creation_tokens:
            logger.info(f"ClaudeProviderHandler: Cache usage - read: {cache_read_tokens}, creation: {cache_creation_tokens}")
        
        openai_response = {
            'id': getattr(response, 'id', f"claude-{model}-{int(time.time())}"),
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': f'{self.provider_id}/{model}',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': message_content if message_content else None,
                },
                'finish_reason': finish_reason
            }],
            'usage': {
                'prompt_tokens': input_tokens,
                'completion_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                'prompt_tokens_details': {
                    'cached_tokens': cache_read_tokens,
                    'audio_tokens': 0
                },
                'completion_tokens_details': {
                    'reasoning_tokens': 0,
                    'audio_tokens': 0
                }
            }
        }
        
        if tool_calls:
            openai_response['choices'][0]['message']['tool_calls'] = tool_calls
        
        if thinking_text:
            openai_response['choices'][0]['message']['provider_options'] = {
                'anthropic': {
                    'thinking': thinking_text
                }
            }
            logger.debug(f"ClaudeProviderHandler: Added thinking content to response ({len(thinking_text)} chars)")
        
        return openai_response
    
    async def _handle_streaming_request_sdk(self, client, request_kwargs: Dict, model: str):
        """Handle streaming request using Anthropic SDK's async streaming API."""
        import logging
        import json
        logger = logging.getLogger(__name__)
        
        logger.info(f"ClaudeProviderHandler: Starting SDK streaming request")
        
        completion_id = f"claude-{int(time.time())}"
        created_time = int(time.time())
        
        first_chunk = True
        accumulated_content = ""
        accumulated_thinking = ""
        thinking_signature = ""
        is_redacted_thinking = False
        content_block_index = 0
        current_tool_calls = []
        
        last_event_time = time.time()
        idle_timeout = self.stream_idle_timeout
        
        try:
            stream = await client.messages.create(**request_kwargs, stream=True)
            
            async for event in stream:
                last_event_time = time.time()
                
                if time.time() - last_event_time > idle_timeout:
                    logger.error(f"ClaudeProviderHandler: Stream idle timeout ({idle_timeout}s)")
                    raise TimeoutError(f"Stream idle for {idle_timeout}s")
                
                event_type = getattr(event, 'type', None)
                
                if event_type == 'content_block_start':
                    content_block = getattr(event, 'content_block', None)
                    if content_block:
                        block_type = getattr(content_block, 'type', '')
                        
                        if block_type == 'tool_use':
                            tool_call = {
                                'index': content_block_index,
                                'id': getattr(content_block, 'id', ''),
                                'type': 'function',
                                'function': {
                                    'name': getattr(content_block, 'name', ''),
                                    'arguments': ''
                                }
                            }
                            current_tool_calls.append(tool_call)
                            logger.debug(f"ClaudeProviderHandler: Tool use block started: {tool_call['function']['name']}")
                        
                        elif block_type == 'thinking':
                            accumulated_thinking = ""
                            is_redacted_thinking = False
                            thinking_signature = ""
                            logger.debug(f"ClaudeProviderHandler: Thinking block started")
                        
                        elif block_type == 'redacted_thinking':
                            accumulated_thinking = ""
                            is_redacted_thinking = True
                            thinking_signature = ""
                            logger.debug(f"ClaudeProviderHandler: Redacted thinking block started")
                        
                        content_block_index += 1
                
                elif event_type == 'content_block_delta':
                    delta = getattr(event, 'delta', None)
                    if delta:
                        delta_type = getattr(delta, 'type', '')
                        
                        if delta_type == 'text_delta':
                            text = getattr(delta, 'text', '')
                            accumulated_content += text
                            
                            openai_delta = {'content': text}
                            if first_chunk:
                                openai_delta['role'] = 'assistant'
                                first_chunk = False
                            
                            openai_chunk = {
                                'id': completion_id,
                                'object': 'chat.completion.chunk',
                                'created': created_time,
                                'model': f'{self.provider_id}/{model}',
                                'choices': [{
                                    'index': 0,
                                    'delta': openai_delta,
                                    'finish_reason': None
                                }]
                            }
                            
                            yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                        
                        elif delta_type == 'input_json_delta':
                            partial_json = getattr(delta, 'partial_json', '')
                            if current_tool_calls:
                                current_tool_calls[-1]['function']['arguments'] += partial_json
                        
                        elif delta_type == 'thinking_delta':
                            thinking_text = getattr(delta, 'thinking', '')
                            accumulated_thinking += thinking_text
                            logger.debug(f"ClaudeProviderHandler: Thinking delta: {len(thinking_text)} chars")
                        
                        elif delta_type == 'signature_delta':
                            signature = getattr(delta, 'signature', '')
                            thinking_signature = signature
                            logger.debug(f"ClaudeProviderHandler: Thinking signature received")
                
                elif event_type == 'content_block_stop':
                    if current_tool_calls:
                        tool_call = current_tool_calls[-1]
                        try:
                            args = json.loads(tool_call['function']['arguments']) if tool_call['function']['arguments'] else {}
                            tool_call['function']['arguments'] = json.dumps(args)
                        except json.JSONDecodeError:
                            logger.warning(f"ClaudeProviderHandler: Invalid tool call arguments JSON")
                            tool_call['function']['arguments'] = '{}'
                        
                        tool_call_chunk = {
                            'id': completion_id,
                            'object': 'chat.completion.chunk',
                            'created': created_time,
                            'model': f'{self.provider_id}/{model}',
                            'choices': [{
                                'index': 0,
                                'delta': {
                                    'tool_calls': [{
                                        'index': tool_call['index'],
                                        'id': tool_call['id'],
                                        'type': tool_call['type'],
                                        'function': tool_call['function']
                                    }]
                                },
                                'finish_reason': None
                            }]
                        }
                        
                        yield f"data: {json.dumps(tool_call_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                        logger.debug(f"ClaudeProviderHandler: Emitted tool call: {tool_call['function']['name']}")
                    
                    elif accumulated_thinking:
                        block_type = "redacted_thinking" if is_redacted_thinking else "thinking"
                        logger.info(f"ClaudeProviderHandler: {block_type} block completed ({len(accumulated_thinking)} chars)")
                        accumulated_thinking = ""
                        is_redacted_thinking = False
                        thinking_signature = ""
                
                elif event_type == 'message_delta':
                    usage = getattr(event, 'usage', None)
                    if usage:
                        logger.debug(f"ClaudeProviderHandler: Streaming usage update: {usage}")
                        
                        cache_read = getattr(usage, 'cache_read_input_tokens', 0)
                        cache_creation = getattr(usage, 'cache_creation_input_tokens', 0)
                        if cache_read > 0:
                            self.cache_stats['cache_hits'] += 1
                            self.cache_stats['cache_tokens_read'] += cache_read
                        if cache_creation > 0:
                            self.cache_stats['cache_misses'] += 1
                            self.cache_stats['cache_tokens_created'] += cache_creation
                
                elif event_type == 'message_stop':
                    final_chunk = {
                        'id': completion_id,
                        'object': 'chat.completion.chunk',
                        'created': created_time,
                        'model': f'{self.provider_id}/{model}',
                        'choices': [{
                            'index': 0,
                            'delta': {},
                            'finish_reason': 'stop'
                        }]
                    }
                    
                    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                    # Yield control to event loop to ensure chunk is flushed to client
                    await asyncio.sleep(0)
                    yield b"data: [DONE]\n\n"
                    # Final flush to ensure all buffered data reaches the client
                    await asyncio.sleep(0)
            
            logger.info(f"ClaudeProviderHandler: SDK streaming completed successfully")
            self.record_success()
            
        except Exception as e:
            logger.error(f"ClaudeProviderHandler: SDK streaming error: {str(e)}", exc_info=True)
            raise
    
    def get_cache_stats(self) -> Dict:
        """Get cache usage statistics (Phase 2.3)."""
        total = self.cache_stats['cache_hits'] + self.cache_stats['cache_misses']
        hit_rate = (self.cache_stats['cache_hits'] / total * 100) if total > 0 else 0
        
        return {
            **self.cache_stats,
            'total_cache_events': total,
            'cache_hit_rate_percent': round(hit_rate, 2),
        }
    
    # Model caching is now handled by the base class using the unified cache system
    # _get_models_cache_path(), _save_models_cache(), _load_models_cache() are inherited from BaseProviderHandler

    async def get_models(self) -> List[Model]:
        """Return list of available Claude models by querying the API."""
        try:
            import logging
            import json
            logging.info("=" * 80)
            logging.info("ClaudeProviderHandler: Starting model list retrieval")
            logging.info("=" * 80)

            # First try to load from cache
            cached_models = self._load_models_cache()
            if cached_models:
                logging.info(f"ClaudeProviderHandler: ✓ Returning {len(cached_models)} models from cache")
                return cached_models

            await self.apply_rate_limit()

            try:
                logging.info("ClaudeProviderHandler: [1/3] Attempting primary API endpoint...")

                headers = await self._get_auth_headers(stream=False)
                
                api_endpoint = 'https://api.anthropic.com/v1/models'
                logging.info(f"ClaudeProviderHandler: Calling API endpoint: {api_endpoint}")
                logging.info(f"ClaudeProviderHandler: Using OAuth2 authentication with full headers")
                
                response = await self.client.get(api_endpoint, headers=headers)
                
                logging.info(f"ClaudeProviderHandler: API response status: {response.status_code}")
                
                if response.status_code == 200:
                    models_data = response.json()
                    logging.info(f"ClaudeProviderHandler: ✓ Primary API call successful!")
                    logging.info(f"ClaudeProviderHandler: Response data keys: {list(models_data.keys())}")
                    logging.info(f"ClaudeProviderHandler: Retrieved {len(models_data.get('data', []))} models from API")
                    
                    if AISBF_DEBUG:
                        logging.info(f"ClaudeProviderHandler: Full API response: {models_data}")
                    
                    models = []
                    for model_data in models_data.get('data', []):
                        model_id = model_data.get('id', '')
                        display_name = model_data.get('display_name') or model_data.get('name') or model_id
                        
                        context_size = (
                            model_data.get('max_input_tokens') or
                            model_data.get('context_window') or
                            model_data.get('context_length') or
                            model_data.get('max_tokens')
                        )
                        
                        description = model_data.get('description')
                        
                        models.append(Model(
                            id=model_id,
                            name=display_name,
                            provider_id=self.provider_id,
                            context_size=context_size,
                            context_length=context_size,
                            description=description
                        ))
                        logging.info(f"ClaudeProviderHandler:   - {model_id} ({display_name}, context: {context_size})")
                    
                    if models:
                        self._save_models_cache(models)
                        
                        logging.info("=" * 80)
                        logging.info(f"ClaudeProviderHandler: ✓ SUCCESS - Returning {len(models)} models from primary API")
                        logging.info(f"ClaudeProviderHandler: Source: Dynamic API retrieval (Anthropic)")
                        logging.info("=" * 80)
                        return models
                    else:
                        logging.warning("ClaudeProviderHandler: ✗ Primary API returned empty model list")
                else:
                    logging.warning(f"ClaudeProviderHandler: ✗ Primary API call failed with status {response.status_code}")
                    try:
                        error_body = response.json()
                        logging.warning(f"ClaudeProviderHandler: Error response: {error_body}")
                    except:
                        logging.warning(f"ClaudeProviderHandler: Error response (text): {response.text[:200]}")
            
            except Exception as api_error:
                logging.warning(f"ClaudeProviderHandler: ✗ Exception during primary API call")
                logging.warning(f"ClaudeProviderHandler: Error type: {type(api_error).__name__}")
                logging.warning(f"ClaudeProviderHandler: Error message: {str(api_error)}")
                if AISBF_DEBUG:
                    logging.warning(f"ClaudeProviderHandler: Full traceback:", exc_info=True)
            
            try:
                logging.info("-" * 80)
                logging.info("ClaudeProviderHandler: [2/3] Attempting fallback endpoint...")
                
                fallback_endpoint = 'http://lisa.nexlab.net:5000/claude/models'
                logging.info(f"ClaudeProviderHandler: Calling fallback endpoint: {fallback_endpoint}")
                
                fallback_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
                
                try:
                    fallback_response = await fallback_client.get(fallback_endpoint)
                    logging.info(f"ClaudeProviderHandler: Fallback response status: {fallback_response.status_code}")
                    
                    if fallback_response.status_code == 200:
                        fallback_data = fallback_response.json()
                        logging.info(f"ClaudeProviderHandler: ✓ Fallback API call successful!")
                        
                        if AISBF_DEBUG:
                            logging.info(f"ClaudeProviderHandler: Fallback response: {fallback_data}")
                        
                        models_list = fallback_data if isinstance(fallback_data, list) else fallback_data.get('data', fallback_data.get('models', []))
                        
                        models = []
                        for model_data in models_list:
                            if isinstance(model_data, str):
                                models.append(Model(id=model_data, name=model_data, provider_id=self.provider_id))
                            elif isinstance(model_data, dict):
                                model_id = model_data.get('id', model_data.get('model', ''))
                                display_name = model_data.get('name', model_data.get('display_name', model_id))
                                
                                context_size = (
                                    model_data.get('max_input_tokens') or
                                    model_data.get('context_window') or
                                    model_data.get('context_length') or
                                    model_data.get('context_size') or
                                    model_data.get('max_tokens')
                                )
                                
                                description = model_data.get('description')
                                
                                models.append(Model(
                                    id=model_id,
                                    name=display_name,
                                    provider_id=self.provider_id,
                                    context_size=context_size,
                                    context_length=context_size,
                                    description=description
                                ))
                        
                        if models:
                            for model in models:
                                logging.info(f"ClaudeProviderHandler:   - {model.id} ({model.name})")
                            
                            self._save_models_cache(models)
                            
                            logging.info("=" * 80)
                            logging.info(f"ClaudeProviderHandler: ✓ SUCCESS - Returning {len(models)} models from fallback API")
                            logging.info(f"ClaudeProviderHandler: Source: Dynamic API retrieval (Fallback)")
                            logging.info("=" * 80)
                            return models
                        else:
                            logging.warning("ClaudeProviderHandler: ✗ Fallback API returned empty model list")
                    else:
                        logging.warning(f"ClaudeProviderHandler: ✗ Fallback API call failed with status {fallback_response.status_code}")
                        try:
                            error_body = fallback_response.json()
                            logging.warning(f"ClaudeProviderHandler: Fallback error response: {error_body}")
                        except:
                            logging.warning(f"ClaudeProviderHandler: Fallback error response (text): {fallback_response.text[:200]}")
                finally:
                    await fallback_client.aclose()
                    
            except Exception as fallback_error:
                logging.warning(f"ClaudeProviderHandler: ✗ Exception during fallback API call")
                logging.warning(f"ClaudeProviderHandler: Error type: {type(fallback_error).__name__}")
                logging.warning(f"ClaudeProviderHandler: Error message: {str(fallback_error)}")
                if AISBF_DEBUG:
                    logging.warning(f"ClaudeProviderHandler: Full traceback:", exc_info=True)
            
            logging.info("-" * 80)
            logging.info("ClaudeProviderHandler: [3/3] Attempting to load from cache...")
            
            cached_models = self._load_models_cache()
            if cached_models:
                for model in cached_models:
                    logging.info(f"ClaudeProviderHandler:   - {model.id} ({model.name})")
                
                logging.info("=" * 80)
                logging.info(f"ClaudeProviderHandler: ✓ Returning {len(cached_models)} models from cache")
                logging.info(f"ClaudeProviderHandler: Source: Cached model list")
                logging.info("=" * 80)
                return cached_models
            
            logging.info("-" * 80)
            logging.info("ClaudeProviderHandler: Using static fallback model list")
            static_models = [
                Model(id="claude-3-7-sonnet-20250219", name="Claude 3.7 Sonnet", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-5-sonnet-20241022", name="Claude 3.5 Sonnet", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-opus-20240229", name="Claude 3 Opus", provider_id=self.provider_id, context_size=200000, context_length=200000),
            ]
            
            for model in static_models:
                logging.info(f"ClaudeProviderHandler:   - {model.id} ({model.name})")
            
            logging.info("=" * 80)
            logging.info(f"ClaudeProviderHandler: ✓ Returning {len(static_models)} models from static list")
            logging.info(f"ClaudeProviderHandler: Source: Static fallback configuration")
            logging.info("=" * 80)
            
            return static_models
        except Exception as e:
            import logging
            logging.error("=" * 80)
            logging.error(f"ClaudeProviderHandler: ✗ FATAL ERROR getting models: {str(e)}")
            logging.error("=" * 80)
            logging.error(f"ClaudeProviderHandler: Error details:", exc_info=True)
            raise e
