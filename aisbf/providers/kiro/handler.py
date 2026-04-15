"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Kiro Provider Handler - Direct Kiro API integration (Amazon Q Developer).

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
import os
import json
import uuid
import logging
from typing import Dict, List, Optional, Union

from ...config import config
from ...models import Model
from .. import BaseProviderHandler

# Check if debug mode is enabled
AISBF_DEBUG = os.environ.get('AISBF_DEBUG', '').lower() in ('true', '1', 'yes')


class KiroProviderHandler(BaseProviderHandler):
    """
    Handler for direct Kiro API integration (Amazon Q Developer).

    This handler makes direct API calls to Kiro's API using credentials from
    Kiro IDE or kiro-cli, with FULL kiro-gateway feature parity including:
    - Tool calls/function calling
    - Images/multimodal content
    - Complex message merging and validation
    - Role normalization
    - Complete OpenAI <-> Kiro format conversion
    """
    def __init__(self, provider_id: str, api_key: str):
        super().__init__(provider_id, api_key)
        self.provider_config = config.get_provider(provider_id)
        self.region = "us-east-1"  # Default region

        # Import AuthType for checking auth type
        from ...auth.kiro import AuthType
        self.AuthType = AuthType

        # Initialize KiroAuthManager with credentials from config
        self.auth_manager = None
        self._init_auth_manager()

        # HTTP client for making requests
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))

    def _init_auth_manager(self):
        """Initialize KiroAuthManager with credentials from config"""
        try:
            from ...auth.kiro import KiroAuthManager

            # Get Kiro-specific configuration from provider config
            kiro_config = getattr(self.provider_config, 'kiro_config', None)

            if not kiro_config:
                logging.warning(f"No kiro_config found in provider {self.provider_id}, using defaults")
                kiro_config = {}

            # Extract credentials from provider config
            refresh_token = kiro_config.get('refresh_token') if isinstance(kiro_config, dict) else None
            profile_arn = kiro_config.get('profile_arn') if isinstance(kiro_config, dict) else None
            region = kiro_config.get('region', 'us-east-1') if isinstance(kiro_config, dict) else 'us-east-1'
            creds_file = kiro_config.get('creds_file') if isinstance(kiro_config, dict) else None
            sqlite_db = kiro_config.get('sqlite_db') if isinstance(kiro_config, dict) else None
            client_id = kiro_config.get('client_id') if isinstance(kiro_config, dict) else None
            client_secret = kiro_config.get('client_secret') if isinstance(kiro_config, dict) else None

            self.region = region

            # Initialize auth manager
            self.auth_manager = KiroAuthManager(
                refresh_token=refresh_token,
                profile_arn=profile_arn,
                region=region,
                creds_file=creds_file,
                sqlite_db=sqlite_db,
                client_id=client_id,
                client_secret=client_secret
            )

            logging.info(f"KiroProviderHandler: Auth manager initialized for region {region}")

        except Exception as e:
            logging.error(f"Failed to initialize KiroAuthManager: {e}")
            self.auth_manager = None

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            logging.info(f"KiroProviderHandler: Handling request for model {model}")
            if AISBF_DEBUG:
                logging.info(f"KiroProviderHandler: Messages: {messages}")
                logging.info(f"KiroProviderHandler: Tools: {tools}")
            else:
                logging.info(f"KiroProviderHandler: Messages count: {len(messages)}")
                logging.info(f"KiroProviderHandler: Tools count: {len(tools) if tools else 0}")

            if not self.auth_manager:
                raise Exception("Kiro authentication not configured. Please set kiro_config in provider configuration.")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Get access token and profile ARN with retry logic
            max_retries = 3
            retry_delay = 1.0
            access_token = None
            
            for attempt in range(max_retries):
                try:
                    access_token = await self.auth_manager.get_access_token()
                    break
                except (Exception) as e:
                    if "ConnectTimeout" in str(type(e).__name__) or "TimeoutException" in str(type(e).__name__):
                        logging.warning(f"Token retrieval timeout on attempt {attempt + 1}/{max_retries}")
                        if attempt < max_retries - 1:
                            logging.info(f"Retrying in {retry_delay:.1f} seconds...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                        else:
                            logging.error(f"Token retrieval failed after {max_retries} attempts")
                            raise
                    else:
                        raise
            
            profile_arn = self.auth_manager.profile_arn

            # Determine effective profileArn based on auth type
            # AWS SSO OIDC users don't need profileArn and it causes 403 if sent
            effective_profile_arn = ""
            if profile_arn and self.auth_manager._auth_type != self.AuthType.AWS_SSO_OIDC:
                effective_profile_arn = profile_arn
                logging.info(f"KiroProviderHandler: Using profileArn (Kiro Desktop Auth)")
            else:
                logging.info(f"KiroProviderHandler: Skipping profileArn (AWS SSO OIDC/Builder ID)")

            # Use the proper kiro-gateway conversion pipeline to build the payload.
            from .converters_openai import build_kiro_payload_from_dict

            conversation_id = str(uuid.uuid4())

            payload = build_kiro_payload_from_dict(
                model=model,
                messages=messages,
                tools=tools,
                conversation_id=conversation_id,
                profile_arn=effective_profile_arn
            )

            logging.info(f"KiroProviderHandler: Model '{model}' normalized for Kiro API")

            if AISBF_DEBUG:
                logging.info(f"KiroProviderHandler: Kiro payload: {json.dumps(payload, indent=2)}")

            # Make request to Kiro API with proper headers
            headers = self.auth_manager.get_auth_headers(access_token)

            kiro_api_url = f"https://q.{self.region}.amazonaws.com/generateAssistantResponse"

            logging.info(f"KiroProviderHandler: Sending request to {kiro_api_url}")
            logging.info(f"KiroProviderHandler: Stream mode: {stream}")

            # Handle streaming mode
            if stream:
                logging.info(f"KiroProviderHandler: Using streaming mode")
                return self._handle_streaming_request(
                    kiro_api_url=kiro_api_url,
                    payload=payload,
                    headers=headers,
                    model=model
                )

            # Non-streaming request with retry logic
            max_api_retries = 2
            api_retry_delay = 2.0
            response = None
            
            for api_attempt in range(max_api_retries):
                try:
                    response = await self.client.post(
                        kiro_api_url,
                        json=payload,
                        headers=headers
                    )
                    break
                except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException) as e:
                    logging.warning(f"API request timeout on attempt {api_attempt + 1}/{max_api_retries}: {type(e).__name__}")
                    
                    if api_attempt < max_api_retries - 1:
                        logging.info(f"Retrying API request in {api_retry_delay:.1f} seconds...")
                        await asyncio.sleep(api_retry_delay)
                        api_retry_delay *= 1.5
                    else:
                        logging.error(f"API request failed after {max_api_retries} attempts")
                        self.record_failure()
                        raise

            # Check for 429 rate limit error before raising
            if response.status_code == 429:
                try:
                    response_data = response.json()
                except Exception:
                    response_data = response.text

                self.handle_429_error(response_data, dict(response.headers))
                response.raise_for_status()

            # Log error details for non-2xx responses before raising
            if response.status_code >= 400:
                try:
                    error_body = response.json()
                    logging.error(f"KiroProviderHandler: API error response: {json.dumps(error_body, indent=2)}")
                except Exception:
                    logging.error(f"KiroProviderHandler: API error response (text): {response.text}")

            response.raise_for_status()

            # Parse AWS Event Stream format response
            logging.info(f"KiroProviderHandler: Parsing AWS Event Stream response")

            from .parsers import AwsEventStreamParser

            parser = AwsEventStreamParser()
            parser.feed(response.content)

            # Extract content and tool calls
            content = parser.get_content()
            tool_calls = parser.get_tool_calls()

            if AISBF_DEBUG:
                logging.info(f"KiroProviderHandler: Parsed content length: {len(content)}")
                logging.info(f"KiroProviderHandler: Parsed tool calls: {len(tool_calls)}")
                if tool_calls:
                    logging.info(f"KiroProviderHandler: Tool calls: {json.dumps(tool_calls, indent=2)}")

            logging.info(f"KiroProviderHandler: Response parsed successfully")

            # Build OpenAI-format response
            openai_response = self._build_openai_response(model, content, tool_calls)

            if AISBF_DEBUG:
                logging.info(f"=== FINAL KIRO RESPONSE DICT ===")
                logging.info(f"Final response: {json.dumps(openai_response, indent=2, default=str)}")
                logging.info(f"=== END FINAL KIRO RESPONSE DICT ===")

            self.record_success()
            return openai_response

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException) as e:
            logging.error(f"KiroProviderHandler: Timeout error after retries: {type(e).__name__}")
            logging.debug(f"KiroProviderHandler: Timeout details", exc_info=True)
            self.record_failure()
            raise Exception(f"Kiro API timeout after retries: {type(e).__name__}")
        except Exception as e:
            logging.error(f"KiroProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    def _build_openai_response(self, model: str, content: str, tool_calls: List[Dict]) -> Dict:
        """Build OpenAI-format response from parsed Kiro data."""
        finish_reason = "tool_calls" if tool_calls else "stop"

        openai_response = {
            "id": f"kiro-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"{self.provider_id}/{model}",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content if not tool_calls else None
                },
                "finish_reason": finish_reason
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }

        if tool_calls:
            openai_response["choices"][0]["message"]["tool_calls"] = tool_calls
            logging.info(f"KiroProviderHandler: Response includes {len(tool_calls)} tool calls")

        return openai_response

    async def _handle_streaming_request(self, kiro_api_url: str, payload: dict, headers: dict, model: str):
        """Handle streaming request to Kiro API."""
        logger = logging.getLogger(__name__)
        logger.info(f"KiroProviderHandler: Starting streaming request")

        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as streaming_client:
            async with streaming_client.stream("POST", kiro_api_url, json=payload, headers=headers) as response:
                logger.info(f"KiroProviderHandler: Streaming response status: {response.status_code}")

                if response.status_code >= 400:
                    error_text = await response.aread()
                    logger.error(f"KiroProviderHandler: Streaming error: {error_text}")
                    raise Exception(f"Kiro API error: {response.status_code}")

                from .parsers import AwsEventStreamParser
                parser = AwsEventStreamParser()

                completion_id = f"kiro-{int(time.time())}"
                created_time = int(time.time())

                first_chunk = True
                accumulated_content = ""

                async for chunk in response.aiter_bytes():
                    if not chunk:
                        continue

                    parser.feed(chunk)

                    current_content = parser.get_content()

                    delta_content = current_content[len(accumulated_content):]
                    accumulated_content = current_content

                    if delta_content:
                        delta = {}
                        delta["content"] = delta_content

                        if first_chunk:
                            delta["role"] = "assistant"
                            first_chunk = False

                        openai_chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": f"{self.provider_id}/{model}",
                            "choices": [{
                                "index": 0,
                                "delta": delta,
                                "finish_reason": None
                            }]
                        }

                        yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n".encode('utf-8')

                logger.info(f"KiroProviderHandler: Streaming completed")

                final_tool_calls = parser.get_tool_calls()
                finish_reason = "tool_calls" if final_tool_calls else "stop"

                logger.info(f"KiroProviderHandler: Final tool calls count: {len(final_tool_calls)}")

                if final_tool_calls:
                    indexed_tool_calls = []
                    for idx, tc in enumerate(final_tool_calls):
                        func = tc.get("function") or {}
                        tool_name = func.get("name") or ""
                        tool_args = func.get("arguments") or "{}"

                        logger.debug(f"Tool call [{idx}] '{tool_name}': id={tc.get('id')}, args_length={len(tool_args)}")

                        indexed_tc = {
                            "index": idx,
                            "id": tc.get("id"),
                            "type": tc.get("type", "function"),
                            "function": {
                                "name": tool_name,
                                "arguments": tool_args
                            }
                        }
                        indexed_tool_calls.append(indexed_tc)

                    tool_calls_chunk = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created_time,
                        "model": f"{self.provider_id}/{model}",
                        "choices": [{
                            "index": 0,
                            "delta": {"tool_calls": indexed_tool_calls},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(tool_calls_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                    # Yield control to event loop to ensure chunk is flushed to client
                    await asyncio.sleep(0)

                final_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": f"{self.provider_id}/{model}",
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": finish_reason
                    }],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0
                    }
                }

                yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode('utf-8')
                # Yield control to event loop to ensure chunk is flushed to client
                await asyncio.sleep(0)
                yield b"data: [DONE]\n\n"
                # Final flush to ensure all buffered data reaches the client
                await asyncio.sleep(0)

    # Model caching is now handled by the base class using the unified cache system
    # _get_models_cache_path(), _save_models_cache(), _load_models_cache() are inherited from BaseProviderHandler

    async def get_models(self) -> List[Model]:
        """Return list of available models using fallback strategy."""
        try:
            logging.info("=" * 80)
            logging.info("KiroProviderHandler: Starting model list retrieval")
            logging.info("=" * 80)

            await self.apply_rate_limit()

            # Try nexlab endpoint first
            try:
                logging.info("KiroProviderHandler: [1/4] Attempting nexlab endpoint...")

                nexlab_endpoint = 'http://lisa.nexlab.net:5000/kiro/models'
                logging.info(f"KiroProviderHandler: Calling nexlab endpoint: {nexlab_endpoint}")

                nexlab_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))

                try:
                    nexlab_response = await nexlab_client.get(nexlab_endpoint)
                    logging.info(f"KiroProviderHandler: Nexlab response status: {nexlab_response.status_code}")

                    if nexlab_response.status_code == 200:
                        nexlab_data = nexlab_response.json()
                        logging.info(f"KiroProviderHandler: ✓ Nexlab API call successful!")

                        if AISBF_DEBUG:
                            response_str = str(nexlab_data)
                            if len(response_str) > 1024:
                                response_str = response_str[:1024] + f" ... [TRUNCATED, total length: {len(response_str)} chars]"
                            logging.info(f"KiroProviderHandler: Nexlab response: {response_str}")

                        models_list = nexlab_data if isinstance(nexlab_data, list) else nexlab_data.get('data', nexlab_data.get('models', []))

                        models = []
                        for model_data in models_list:
                            if isinstance(model_data, str):
                                models.append(Model(id=model_data, name=model_data, provider_id=self.provider_id))
                            elif isinstance(model_data, dict):
                                model_id = model_data.get('model_id') or model_data.get('id') or model_data.get('model', '')
                                display_name = model_data.get('model_name') or model_data.get('name') or model_data.get('display_name') or model_id

                                top_provider = model_data.get('top_provider', {})
                                context_size = (
                                    model_data.get('context_window_tokens') or
                                    model_data.get('context_window') or
                                    model_data.get('context_length') or
                                    model_data.get('context_size') or
                                    model_data.get('max_tokens') or
                                    (top_provider.get('context_length') if isinstance(top_provider, dict) else None)
                                )

                                pricing = model_data.get('pricing')
                                description = model_data.get('description')
                                supported_parameters = model_data.get('supported_parameters')

                                rate_multiplier = model_data.get('rate_multiplier')
                                rate_unit = model_data.get('rate_unit')
                                if rate_multiplier or rate_unit:
                                    if not pricing:
                                        pricing = {}
                                    if rate_multiplier:
                                        pricing['rate_multiplier'] = float(rate_multiplier) if isinstance(rate_multiplier, (int, float, str)) else None
                                    if rate_unit:
                                        pricing['rate_unit'] = rate_unit

                                if isinstance(top_provider, dict):
                                    top_provider_data = {
                                        'context_length': top_provider.get('context_length'),
                                        'max_completion_tokens': top_provider.get('max_completion_tokens'),
                                        'is_moderated': top_provider.get('is_moderated')
                                    }
                                else:
                                    top_provider_data = None

                                if model_id:
                                    models.append(Model(
                                        id=model_id,
                                        name=display_name,
                                        provider_id=self.provider_id,
                                        context_size=context_size,
                                        context_length=context_size,
                                        description=description,
                                        pricing=pricing,
                                        top_provider=top_provider_data,
                                        supported_parameters=supported_parameters
                                    ))

                        if models:
                            for model in models:
                                logging.info(f"KiroProviderHandler:   - {model.id} ({model.name})")

                            self._save_models_cache(models)

                            logging.info("=" * 80)
                            logging.info(f"KiroProviderHandler: ✓ SUCCESS - Returning {len(models)} models from nexlab endpoint")
                            logging.info(f"KiroProviderHandler: Source: Dynamic API retrieval (Nexlab)")
                            logging.info("=" * 80)
                            return models
                        else:
                            logging.warning("KiroProviderHandler: ✗ Nexlab endpoint returned empty model list")
                    else:
                        logging.warning(f"KiroProviderHandler: ✗ Nexlab API call failed with status {nexlab_response.status_code}")
                        try:
                            error_body = nexlab_response.json()
                            logging.warning(f"KiroProviderHandler: Nexlab error response: {error_body}")
                        except:
                            logging.warning(f"KiroProviderHandler: Nexlab error response (text): {nexlab_response.text[:200]}")
                finally:
                    await nexlab_client.aclose()

            except Exception as nexlab_error:
                logging.warning(f"KiroProviderHandler: ✗ Exception during nexlab API call")
                logging.warning(f"KiroProviderHandler: Error type: {type(nexlab_error).__name__}")
                logging.warning(f"KiroProviderHandler: Error message: {str(nexlab_error)}")
                if AISBF_DEBUG:
                    logging.warning(f"KiroProviderHandler: Full traceback:", exc_info=True)

            # Try to load from cache
            logging.info("-" * 80)
            logging.info("KiroProviderHandler: [2/4] Attempting to load from cache...")

            cached_models = self._load_models_cache()
            if cached_models:
                for model in cached_models:
                    logging.info(f"KiroProviderHandler:   - {model.id} ({model.name})")

                logging.info("=" * 80)
                logging.info(f"KiroProviderHandler: ✓ Returning {len(cached_models)} models from cache")
                logging.info(f"KiroProviderHandler: Source: Cached model list")
                logging.info("=" * 80)
                return cached_models

            # Try to fetch models from AWS Q API
            try:
                logging.info("-" * 80)
                logging.info("KiroProviderHandler: [3/4] Attempting to fetch from AWS Q API...")

                if not self.auth_manager:
                    raise Exception("Auth manager not initialized")

                access_token = await self.auth_manager.get_access_token()
                profile_arn = self.auth_manager.profile_arn

                effective_profile_arn = profile_arn or ""
                if effective_profile_arn:
                    logging.info(f"KiroProviderHandler: Using profileArn for models API")
                else:
                    logging.info(f"KiroProviderHandler: No profileArn available for models API")

                headers = self.auth_manager.get_auth_headers(access_token)
                headers['Content-Type'] = 'application/x-amz-json-1.0'
                headers['x-amz-target'] = 'AmazonCodeWhispererService.ListAvailableModels'

                base_url = f"https://q.{self.region}.amazonaws.com/"

                all_models = []
                next_token = None
                page_num = 0

                while True:
                    page_num += 1
                    logging.info(f"KiroProviderHandler: Fetching page {page_num}...")

                    request_body = {
                        "origin": "CLI"
                    }

                    if effective_profile_arn:
                        request_body["profileArn"] = effective_profile_arn

                    if next_token:
                        request_body["nextToken"] = next_token

                    logging.info(f"KiroProviderHandler: Calling {base_url} with AWS JSON 1.0 protocol")

                    if AISBF_DEBUG:
                        logging.info(f"KiroProviderHandler: Request body: {json.dumps(request_body, indent=2)}")

                    response = await self.client.post(
                        base_url,
                        json=request_body,
                        headers=headers
                    )

                    logging.info(f"KiroProviderHandler: API response status: {response.status_code}")

                    if response.status_code != 200:
                        logging.warning(f"KiroProviderHandler: ✗ API call failed with status {response.status_code}")
                        try:
                            error_body = response.json()
                            logging.warning(f"KiroProviderHandler: Error response: {error_body}")
                        except:
                            logging.warning(f"KiroProviderHandler: Error response (text): {response.text[:200]}")
                        break

                    response_data = response.json()

                    if AISBF_DEBUG:
                        response_str = json.dumps(response_data, indent=2)
                        if len(response_str) > 1024:
                            response_str = response_str[:1024] + f"\n... [TRUNCATED, total length: {len(response_str)} chars]"
                        logging.info(f"KiroProviderHandler: Response data: {response_str}")

                    models_list = response_data.get('models', [])

                    for model_data in models_list:
                        model_id = model_data.get('modelId', model_data.get('id', ''))
                        model_name = model_data.get('modelName', model_data.get('name', model_id))

                        context_size = (
                            model_data.get('contextWindow') or
                            model_data.get('context_window') or
                            model_data.get('contextLength') or
                            model_data.get('context_length') or
                            model_data.get('max_context_length') or
                            model_data.get('maxTokens') or
                            model_data.get('max_tokens')
                        )

                        pricing = model_data.get('pricing')
                        description = model_data.get('description')
                        supported_parameters = model_data.get('supported_parameters')

                        prompt_token_price = model_data.get('promptTokenPrice') or model_data.get('prompt_token_price')
                        completion_token_price = model_data.get('completionTokenPrice') or model_data.get('completion_token_price')
                        if prompt_token_price or completion_token_price:
                            if not pricing:
                                pricing = {}
                            if prompt_token_price:
                                try:
                                    pricing['prompt'] = float(prompt_token_price)
                                except (ValueError, TypeError):
                                    pricing['prompt'] = prompt_token_price
                            if completion_token_price:
                                try:
                                    pricing['completion'] = float(completion_token_price)
                                except (ValueError, TypeError):
                                    pricing['completion'] = completion_token_price

                        top_provider = model_data.get('topProvider') or model_data.get('top_provider')
                        if isinstance(top_provider, dict):
                            top_provider_data = {
                                'context_length': top_provider.get('context_length') or top_provider.get('contextLength'),
                                'max_completion_tokens': top_provider.get('max_completion_tokens') or top_provider.get('maxCompletionTokens'),
                                'is_moderated': top_provider.get('is_moderated') or top_provider.get('isModerated')
                            }
                        else:
                            top_provider_data = None

                        if model_id:
                            all_models.append(Model(
                                id=model_id,
                                name=model_name,
                                provider_id=self.provider_id,
                                context_size=context_size,
                                context_length=context_size,
                                description=description,
                                pricing=pricing,
                                top_provider=top_provider_data,
                                supported_parameters=supported_parameters
                            ))
                            logging.info(f"KiroProviderHandler:   - {model_id} ({model_name})")

                    next_token = response_data.get('nextToken')
                    if not next_token:
                        logging.info(f"KiroProviderHandler: No more pages (total pages: {page_num})")
                        break

                    logging.info(f"KiroProviderHandler: Found nextToken, fetching next page...")

                if all_models:
                    logging.info(f"KiroProviderHandler: ✓ API call successful!")
                    logging.info(f"KiroProviderHandler: Retrieved {len(all_models)} models across {page_num} page(s)")

                    self._save_models_cache(all_models)

                    logging.info("=" * 80)
                    logging.info(f"KiroProviderHandler: ✓ SUCCESS - Returning {len(all_models)} models from API")
                    logging.info(f"KiroProviderHandler: Source: Dynamic API retrieval (AWS Q)")
                    logging.info("=" * 80)
                    return all_models
                else:
                    logging.warning("KiroProviderHandler: ✗ API returned empty model list")

            except Exception as api_error:
                logging.warning(f"KiroProviderHandler: ✗ Exception during AWS Q API call")
                logging.warning(f"KiroProviderHandler: Error type: {type(api_error).__name__}")
                logging.warning(f"KiroProviderHandler: Error message: {str(api_error)}")
                if AISBF_DEBUG:
                    logging.warning(f"KiroProviderHandler: Full traceback:", exc_info=True)

            # Final fallback to static list
            logging.info("-" * 80)
            logging.info("KiroProviderHandler: [4/4] Using static fallback model list")
            static_models = [
                Model(id="anthropic.claude-3-5-sonnet-20241022-v2:0", name="Claude 3.5 Sonnet v2", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="anthropic.claude-3-5-haiku-20241022-v1:0", name="Claude 3.5 Haiku", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="anthropic.claude-3-5-sonnet-20240620-v1:0", name="Claude 3.5 Sonnet v1", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="anthropic.claude-sonnet-3-5-v2", name="Claude 3.5 Sonnet v2 (alias)", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-sonnet-4-5", name="Claude 3.5 Sonnet v2 (short)", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-haiku-4-5", name="Claude 3.5 Haiku (short)", provider_id=self.provider_id, context_size=200000, context_length=200000),
            ]

            for model in static_models:
                logging.info(f"KiroProviderHandler:   - {model.id} ({model.name})")

            logging.info("=" * 80)
            logging.info(f"KiroProviderHandler: ✓ Returning {len(static_models)} models from static list")
            logging.info(f"KiroProviderHandler: Source: Static fallback configuration")
            logging.info("=" * 80)

            return static_models
        except Exception as e:
            logging.error("=" * 80)
            logging.error(f"KiroProviderHandler: ✗ FATAL ERROR getting models: {str(e)}")
            logging.error("=" * 80)
            logging.error(f"KiroProviderHandler: Error details:", exc_info=True)
            raise e
