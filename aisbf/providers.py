"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Provider handlers for AISBF.

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

Provider handlers for AISBF.
"""
import httpx
import asyncio
import time
import os
from typing import Dict, List, Optional, Union
from google import genai
from openai import OpenAI
from anthropic import Anthropic
from pydantic import BaseModel
from .models import Provider, Model, ErrorTracking
from .config import config
from .utils import count_messages_tokens

# Check if debug mode is enabled
AISBF_DEBUG = os.environ.get('AISBF_DEBUG', '').lower() in ('true', '1', 'yes')

class BaseProviderHandler:
    def __init__(self, provider_id: str, api_key: Optional[str] = None):
        self.provider_id = provider_id
        self.api_key = api_key
        self.error_tracking = config.error_tracking[provider_id]
        self.last_request_time = 0
        self.rate_limit = config.providers[provider_id].rate_limit
        # Add model-level rate limit tracking
        self.model_last_request_time = {}  # {model_name: timestamp}
        # Token usage tracking for rate limits
        self.token_usage = {}  # {model_name: {"TPM": [], "TPH": [], "TPD": []}}
    
    def parse_429_response(self, response_data: Union[Dict, str], headers: Dict = None) -> Optional[int]:
        """
        Parse 429 rate limit response to extract wait time in seconds.
        
        Checks multiple sources:
        1. Retry-After header (seconds or HTTP date)
        2. X-RateLimit-Reset header (Unix timestamp)
        3. Response body fields (retry_after, reset_time, etc.)
        
        Returns:
            Wait time in seconds, or None if cannot be determined
        """
        import logging
        import re
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone
        
        logger = logging.getLogger(__name__)
        logger.info("=== PARSING 429 RATE LIMIT RESPONSE ===")
        
        wait_seconds = None
        
        # Check Retry-After header
        if headers:
            retry_after = headers.get('Retry-After') or headers.get('retry-after')
            if retry_after:
                logger.info(f"Found Retry-After header: {retry_after}")
                try:
                    # Try parsing as integer (seconds)
                    wait_seconds = int(retry_after)
                    logger.info(f"Parsed Retry-After as seconds: {wait_seconds}")
                except ValueError:
                    # Try parsing as HTTP date
                    try:
                        retry_date = parsedate_to_datetime(retry_after)
                        now = datetime.now(timezone.utc)
                        wait_seconds = int((retry_date - now).total_seconds())
                        logger.info(f"Parsed Retry-After as date, wait seconds: {wait_seconds}")
                    except Exception as e:
                        logger.warning(f"Failed to parse Retry-After header: {e}")
            
            # Check X-RateLimit-Reset header (Unix timestamp)
            if not wait_seconds:
                reset_time = headers.get('X-RateLimit-Reset') or headers.get('x-ratelimit-reset')
                if reset_time:
                    logger.info(f"Found X-RateLimit-Reset header: {reset_time}")
                    try:
                        reset_timestamp = int(reset_time)
                        now_timestamp = int(time.time())
                        wait_seconds = reset_timestamp - now_timestamp
                        logger.info(f"Calculated wait from reset timestamp: {wait_seconds} seconds")
                    except Exception as e:
                        logger.warning(f"Failed to parse X-RateLimit-Reset header: {e}")
        
        # Check response body
        if not wait_seconds and isinstance(response_data, dict):
            logger.info(f"Checking response body for rate limit info: {response_data}")
            
            # Common field names for retry/reset time
            retry_fields = [
                'retry_after', 'retryAfter', 'retry_after_seconds',
                'wait_seconds', 'waitSeconds', 'retry_in'
            ]
            reset_fields = [
                'reset_time', 'resetTime', 'reset_at', 'resetAt',
                'reset_timestamp', 'resetTimestamp'
            ]
            
            # Check retry fields (direct seconds)
            for field in retry_fields:
                if field in response_data:
                    try:
                        wait_seconds = int(response_data[field])
                        logger.info(f"Found {field} in response body: {wait_seconds} seconds")
                        break
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse {field}: {e}")
            
            # Check reset fields (timestamp)
            if not wait_seconds:
                for field in reset_fields:
                    if field in response_data:
                        try:
                            reset_timestamp = int(response_data[field])
                            now_timestamp = int(time.time())
                            wait_seconds = reset_timestamp - now_timestamp
                            logger.info(f"Found {field} in response body, calculated wait: {wait_seconds} seconds")
                            break
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Failed to parse {field}: {e}")
            
            # Check for error message with time information
            if not wait_seconds:
                error_msg = response_data.get('error', {})
                if isinstance(error_msg, dict):
                    message = error_msg.get('message', '')
                elif isinstance(error_msg, str):
                    message = error_msg
                else:
                    message = response_data.get('message', '')
                
                if message:
                    logger.info(f"Checking error message for time info: {message}")
                    # Look for patterns like "try again in X seconds/minutes/hours"
                    patterns = [
                        r'try again in (\d+)\s*(second|minute|hour|day)s?',
                        r'retry after (\d+)\s*(second|minute|hour|day)s?',
                        r'wait (\d+)\s*(second|minute|hour|day)s?',
                        r'available in (\d+)\s*(second|minute|hour|day)s?',
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, message, re.IGNORECASE)
                        if match:
                            value = int(match.group(1))
                            unit = match.group(2).lower()
                            
                            # Convert to seconds
                            multipliers = {
                                'second': 1,
                                'minute': 60,
                                'hour': 3600,
                                'day': 86400
                            }
                            wait_seconds = value * multipliers.get(unit, 1)
                            logger.info(f"Extracted wait time from message: {value} {unit}(s) = {wait_seconds} seconds")
                            break
        
        # Ensure wait_seconds is positive and reasonable
        if wait_seconds:
            if wait_seconds < 0:
                logger.warning(f"Calculated negative wait time: {wait_seconds}, setting to 60 seconds")
                wait_seconds = 60
            elif wait_seconds > 86400:  # More than 1 day
                logger.warning(f"Calculated very long wait time: {wait_seconds}, capping at 1 day")
                wait_seconds = 86400
            
            logger.info(f"Final parsed wait time: {wait_seconds} seconds")
        else:
            logger.warning("Could not determine wait time from 429 response, using default 60 seconds")
            wait_seconds = 60
        
        logger.info("=== END PARSING 429 RATE LIMIT RESPONSE ===")
        return wait_seconds
    
    def handle_429_error(self, response_data: Union[Dict, str] = None, headers: Dict = None):
        """
        Handle 429 rate limit error by parsing the response and disabling provider
        for the appropriate duration.
        
        Args:
            response_data: Response body (dict or string)
            headers: Response headers
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.error("=== 429 RATE LIMIT ERROR DETECTED ===")
        logger.error(f"Provider: {self.provider_id}")
        
        # Parse the response to get wait time
        wait_seconds = self.parse_429_response(response_data, headers)
        
        # Disable provider for the calculated duration
        self.error_tracking['disabled_until'] = time.time() + wait_seconds
        
        logger.error(f"!!! PROVIDER DISABLED DUE TO RATE LIMIT !!!")
        logger.error(f"Provider: {self.provider_id}")
        logger.error(f"Reason: 429 Too Many Requests")
        logger.error(f"Disabled for: {wait_seconds} seconds ({wait_seconds / 60:.1f} minutes)")
        logger.error(f"Disabled until: {self.error_tracking['disabled_until']}")
        logger.error(f"Provider will be automatically re-enabled after cooldown")
        logger.error("=== END 429 RATE LIMIT ERROR ===")

    def is_rate_limited(self) -> bool:
        if self.error_tracking['disabled_until'] and self.error_tracking['disabled_until'] > time.time():
            return True
        return False
    
    def _get_model_config(self, model: str) -> Optional[Dict]:
        """Get model configuration from provider config"""
        provider_config = config.providers.get(self.provider_id)
        if provider_config and hasattr(provider_config, 'models') and provider_config.models:
            for model_config in provider_config.models:
                if model_config.get('name') == model:
                    return model_config
        return None
    
    def _check_token_rate_limit(self, model: str, token_count: int) -> bool:
        """
        Check if a request would exceed token rate limits.
        
        Returns True if any rate limit would be exceeded, False otherwise.
        """
        model_config = self._get_model_config(model)
        if not model_config:
            return False
        
        import logging
        logger = logging.getLogger(__name__)
        
        current_time = time.time()
        
        # Check TPM (tokens per minute)
        if model_config.get('rate_limit_TPM'):
            tpm = model_config['rate_limit_TPM']
            # Get tokens used in the last minute
            tokens_used_tpm = self.token_usage.get(model, {}).get('TPM', [])
            # Filter to only include requests from the last 60 seconds
            one_minute_ago = current_time - 60
            recent_tokens_tpm = [t for t in tokens_used_tpm if t > one_minute_ago]
            total_tpm = sum(recent_tokens_tpm)
            
            if total_tpm + token_count > tpm:
                logger.warning(f"TPM limit would be exceeded: {total_tpm + token_count}/{tpm}")
                return True
        
        # Check TPH (tokens per hour)
        if model_config.get('rate_limit_TPH'):
            tph = model_config['rate_limit_TPH']
            # Get tokens used in the last hour
            tokens_used_tph = self.token_usage.get(model, {}).get('TPH', [])
            # Filter to only include requests from the last 3600 seconds
            one_hour_ago = current_time - 3600
            recent_tokens_tph = [t for t in tokens_used_tph if t > one_hour_ago]
            total_tph = sum(recent_tokens_tph)
            
            if total_tph + token_count > tph:
                logger.warning(f"TPH limit would be exceeded: {total_tph + token_count}/{tph}")
                return True
        
        # Check TPD (tokens per day)
        if model_config.get('rate_limit_TPD'):
            tpd = model_config['rate_limit_TPD']
            # Get tokens used in the last day
            tokens_used_tpd = self.token_usage.get(model, {}).get('TPD', [])
            # Filter to only include requests from the last 86400 seconds
            one_day_ago = current_time - 86400
            recent_tokens_tpd = [t for t in tokens_used_tpd if t > one_day_ago]
            total_tpd = sum(recent_tokens_tpd)
            
            if total_tpd + token_count > tpd:
                logger.warning(f"TPD limit would be exceeded: {total_tpd + token_count}/{tpd}")
                return True
        
        return False
    
    def _record_token_usage(self, model: str, token_count: int):
        """Record token usage for rate limit tracking"""
        import logging
        logger = logging.getLogger(__name__)
        
        if model not in self.token_usage:
            self.token_usage[model] = {"TPM": [], "TPH": [], "TPD": []}
        
        current_time = time.time()
        
        # Record for all three time windows
        self.token_usage[model]["TPM"].append((current_time, token_count))
        self.token_usage[model]["TPH"].append((current_time, token_count))
        self.token_usage[model]["TPD"].append((current_time, token_count))
        
        logger.debug(f"Recorded token usage for model {model}: {token_count} tokens")
    
    def _disable_provider_for_duration(self, duration: str):
        """
        Disable provider for a specific duration.
        
        Args:
            duration: "1m" (1 minute), "1h" (1 hour), or "1d" (1 day)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        duration_map = {
            "1m": 60,
            "1h": 3600,
            "1d": 86400
        }
        
        if duration not in duration_map:
            logger.error(f"Invalid duration: {duration}")
            return
        
        disable_seconds = duration_map[duration]
        self.error_tracking['disabled_until'] = time.time() + disable_seconds
        
        logger.error(f"!!! PROVIDER DISABLED !!!")
        logger.error(f"Provider: {self.provider_id}")
        logger.error(f"Reason: Token rate limit exceeded")
        logger.error(f"Disabled for: {duration}")
        logger.error(f"Disabled until: {self.error_tracking['disabled_until']}")
        logger.error(f"Provider will be automatically re-enabled after cooldown")

    async def apply_rate_limit(self, rate_limit: Optional[float] = None):
        """Apply rate limiting by waiting if necessary"""
        if rate_limit is None:
            rate_limit = self.rate_limit

        if rate_limit and rate_limit > 0:
            current_time = time.time()
            time_since_last_request = current_time - self.last_request_time
            required_wait = rate_limit - time_since_last_request

            if required_wait > 0:
                await asyncio.sleep(required_wait)

            self.last_request_time = time.time()

    async def apply_model_rate_limit(self, model: str, rate_limit: Optional[float] = None):
        """Apply rate limiting for a specific model"""
        if rate_limit is None:
            rate_limit = self.rate_limit

        if rate_limit and rate_limit > 0:
            current_time = time.time()
            last_time = self.model_last_request_time.get(model, 0)
            time_since_last_request = current_time - last_time
            required_wait = rate_limit - time_since_last_request

            if required_wait > 0:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Model-level rate limiting: waiting {required_wait:.2f}s for model {model}")
                await asyncio.sleep(required_wait)

            self.model_last_request_time[model] = time.time()

    def record_failure(self):
        import logging
        logger = logging.getLogger(__name__)
        
        self.error_tracking['failures'] += 1
        self.error_tracking['last_failure'] = time.time()
        
        failure_count = self.error_tracking['failures']
        logger.warning(f"=== PROVIDER FAILURE RECORDED ===")
        logger.warning(f"Provider: {self.provider_id}")
        logger.warning(f"Failure count: {failure_count}/3")
        logger.warning(f"Last failure time: {self.error_tracking['last_failure']}")
        
        if self.error_tracking['failures'] >= 3:
            # Get cooldown period from provider config, default to 300 seconds (5 minutes)
            provider_config = config.providers.get(self.provider_id)
            cooldown_seconds = 300  # System default
            
            if provider_config and hasattr(provider_config, 'default_error_cooldown') and provider_config.default_error_cooldown is not None:
                cooldown_seconds = provider_config.default_error_cooldown
                logger.info(f"Using provider-configured cooldown: {cooldown_seconds} seconds")
            else:
                logger.info(f"Using system default cooldown: {cooldown_seconds} seconds")
            
            self.error_tracking['disabled_until'] = time.time() + cooldown_seconds
            disabled_until_time = self.error_tracking['disabled_until']
            cooldown_remaining = int(disabled_until_time - time.time())
            logger.error(f"!!! PROVIDER DISABLED !!!")
            logger.error(f"Provider: {self.provider_id}")
            logger.error(f"Reason: 3 consecutive failures reached")
            logger.error(f"Disabled until: {disabled_until_time}")
            logger.error(f"Cooldown period: {cooldown_remaining} seconds ({cooldown_seconds / 60:.1f} minutes)")
            logger.error(f"Provider will be automatically re-enabled after cooldown")
        else:
            remaining_failures = 3 - failure_count
            logger.warning(f"Provider still active. {remaining_failures} more failure(s) will disable it")
        logger.warning(f"=== END FAILURE RECORDING ===")

    def record_success(self):
        import logging
        logger = logging.getLogger(__name__)
        
        was_disabled = self.error_tracking['disabled_until'] is not None
        previous_failures = self.error_tracking['failures']
        
        self.error_tracking['failures'] = 0
        self.error_tracking['disabled_until'] = None
        
        logger.info(f"=== PROVIDER SUCCESS RECORDED ===")
        logger.info(f"Provider: {self.provider_id}")
        logger.info(f"Previous failure count: {previous_failures}")
        logger.info(f"Failure count reset to: 0")
        
        if was_disabled:
            logger.info(f"!!! PROVIDER RE-ENABLED !!!")
            logger.info(f"Provider: {self.provider_id}")
            logger.info(f"Reason: Successful request after cooldown period")
            logger.info(f"Provider is now active and available for requests")
        else:
            logger.info(f"Provider remains active")
        logger.info(f"=== END SUCCESS RECORDING ===")

class GoogleProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: str):
        super().__init__(provider_id, api_key)
        # Initialize google-genai library
        from google import genai
        self.client = genai.Client(api_key=api_key)

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            logging.info(f"GoogleProviderHandler: Handling request for model {model}")
            logging.info(f"GoogleProviderHandler: Stream: {stream}")
            if AISBF_DEBUG:
                logging.info(f"GoogleProviderHandler: Messages: {messages}")
            else:
                logging.info(f"GoogleProviderHandler: Messages count: {len(messages)}")
            
            if tools:
                logging.info(f"GoogleProviderHandler: Tools provided: {len(tools)} tools")
                if AISBF_DEBUG:
                    logging.info(f"GoogleProviderHandler: Tools: {tools}")
            if tool_choice:
                logging.info(f"GoogleProviderHandler: Tool choice: {tool_choice}")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Build content from messages
            content = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

            # Build config with only non-None values
            config = {"temperature": temperature}
            if max_tokens is not None:
                config["max_output_tokens"] = max_tokens

            # Convert OpenAI tools to Google's function calling format
            google_tools = None
            if tools:
                function_declarations = []
                for tool in tools:
                    if tool.get("type") == "function":
                        function = tool.get("function", {})
                        # Use Google's SDK types for proper validation
                        from google.genai import types as genai_types
                        function_declaration = genai_types.FunctionDeclaration(
                            name=function.get("name"),
                            description=function.get("description", ""),
                            parameters=function.get("parameters", {})
                        )
                        function_declarations.append(function_declaration)
                        logging.info(f"GoogleProviderHandler: Converted tool to Google format: {function_declaration}")
                
                if function_declarations:
                    # Google API expects tools to be a Tool object with function_declarations
                    from google.genai import types as genai_types
                    google_tools = genai_types.Tool(function_declarations=function_declarations)
                    logging.info(f"GoogleProviderHandler: Added {len(function_declarations)} tools to google_tools")
                    
                    # Add tools to config for both streaming and non-streaming
                    config["tools"] = google_tools
                    logging.info(f"GoogleProviderHandler: Added tools to config")

            # Handle streaming request
            if stream:
                logging.info(f"GoogleProviderHandler: Using streaming API")
                # Create a new client instance for streaming to ensure it stays open
                from google import genai
                stream_client = genai.Client(api_key=self.api_key)
                
                # We need to iterate over the streaming response immediately without yielding control
                # to ensure the client stays alive
                chunks = []
                
                for chunk in stream_client.models.generate_content_stream(
                    model=model,
                    contents=content,
                    config=config
                ):
                    chunks.append(chunk)
                
                logging.info(f"GoogleProviderHandler: Streaming response received (total chunks: {len(chunks)})")
                self.record_success()
                
                # Now yield chunks asynchronously - yield raw chunk objects
                # The handlers.py will handle the conversion to OpenAI format
                async def async_generator():
                    for chunk in chunks:
                        yield chunk
                
                return async_generator()
            else:
                # Non-streaming request
                # Generate content using the google-genai client
                response = self.client.models.generate_content(
                    model=model,
                    contents=content,
                    config=config
                )

                logging.info(f"GoogleProviderHandler: Response received: {response}")
                self.record_success()

                # Dump raw response if AISBF_DEBUG is enabled
                if AISBF_DEBUG:
                    logging.info(f"=== RAW GOOGLE RESPONSE ===")
                    logging.info(f"Raw response type: {type(response)}")
                    logging.info(f"Raw response: {response}")
                    logging.info(f"Raw response dir: {dir(response)}")
                    logging.info(f"=== END RAW GOOGLE RESPONSE ===")

                # Extract content from the nested response structure
                # The response has candidates[0].content.parts
                response_text = ""
                tool_calls = None
                finish_reason = "stop"
            
                logging.info(f"=== GOOGLE RESPONSE PARSING START ===")
                logging.info(f"Response type: {type(response)}")
                logging.info(f"Response attributes: {dir(response)}")
                
                try:
                    # Check if response has candidates
                    if hasattr(response, 'candidates'):
                        logging.info(f"Response has 'candidates' attribute")
                        logging.info(f"Candidates: {response.candidates}")
                        logging.info(f"Candidates type: {type(response.candidates)}")
                        logging.info(f"Candidates length: {len(response.candidates) if hasattr(response.candidates, '__len__') else 'N/A'}")
                        
                        if response.candidates:
                            logging.info(f"Candidates is not empty, getting first candidate")
                            candidate = response.candidates[0]
                            logging.info(f"Candidate type: {type(candidate)}")
                            logging.info(f"Candidate attributes: {dir(candidate)}")
                            
                            # Extract finish reason
                            if hasattr(candidate, 'finish_reason'):
                                logging.info(f"Candidate has 'finish_reason' attribute")
                                logging.info(f"Finish reason: {candidate.finish_reason}")
                                # Map Google finish reasons to OpenAI format
                                finish_reason_map = {
                                    'STOP': 'stop',
                                    'MAX_TOKENS': 'length',
                                    'SAFETY': 'content_filter',
                                    'RECITATION': 'content_filter',
                                    'OTHER': 'stop'
                                }
                                google_finish_reason = str(candidate.finish_reason)
                                finish_reason = finish_reason_map.get(google_finish_reason, 'stop')
                                logging.info(f"Mapped finish reason: {finish_reason}")
                            else:
                                logging.warning(f"Candidate does NOT have 'finish_reason' attribute")
                            
                            # Extract content
                            if hasattr(candidate, 'content'):
                                logging.info(f"Candidate has 'content' attribute")
                                logging.info(f"Content: {candidate.content}")
                                logging.info(f"Content type: {type(candidate.content)}")
                                logging.info(f"Content attributes: {dir(candidate.content)}")
                                
                                if candidate.content:
                                    logging.info(f"Content is not empty")
                                    
                                    if hasattr(candidate.content, 'parts'):
                                        logging.info(f"Content has 'parts' attribute")
                                        logging.info(f"Parts: {candidate.content.parts}")
                                        logging.info(f"Parts type: {type(candidate.content.parts)}")
                                        logging.info(f"Parts length: {len(candidate.content.parts) if hasattr(candidate.content.parts, '__len__') else 'N/A'}")
                                        
                                        if candidate.content.parts:
                                            logging.info(f"Parts is not empty, processing all parts")
                                            
                                            # Process all parts to extract text and tool calls
                                            text_parts = []
                                            openai_tool_calls = []
                                            call_id = 0
                                            
                                            for idx, part in enumerate(candidate.content.parts):
                                                logging.info(f"Processing part {idx}")
                                                logging.info(f"Part type: {type(part)}")
                                                logging.info(f"Part attributes: {dir(part)}")
                                                
                                                # Check for text content
                                                if hasattr(part, 'text') and part.text:
                                                    logging.info(f"Part {idx} has 'text' attribute")
                                                    text_parts.append(part.text)
                                                    logging.info(f"Part {idx} text length: {len(part.text)}")
                                                
                                                # Check for function calls (Google's format)
                                                if hasattr(part, 'function_call') and part.function_call:
                                                    logging.info(f"Part {idx} has 'function_call' attribute")
                                                    logging.info(f"Function call: {part.function_call}")
                                                    
                                                    # Convert Google function call to OpenAI format
                                                    try:
                                                        function_call = part.function_call
                                                        openai_tool_call = {
                                                            "id": f"call_{call_id}",
                                                            "type": "function",
                                                            "function": {
                                                                "name": function_call.name,
                                                                "arguments": function_call.args if hasattr(function_call, 'args') else {}
                                                            }
                                                        }
                                                        openai_tool_calls.append(openai_tool_call)
                                                        call_id += 1
                                                        logging.info(f"Converted function call to OpenAI format: {openai_tool_call}")
                                                    except Exception as e:
                                                        logging.error(f"Error converting function call: {e}", exc_info=True)
                                                
                                                # Check for function response (tool output)
                                                if hasattr(part, 'function_response') and part.function_response:
                                                    logging.info(f"Part {idx} has 'function_response' attribute")
                                                    logging.info(f"Function response: {part.function_response}")
                                                    # Function responses are typically handled in the request, not response
                                                    # But we log them for debugging
                                            
                                            # Combine all text parts
                                            response_text = "\n".join(text_parts)
                                            logging.info(f"Combined text length: {len(response_text)}")
                                            logging.info(f"Combined text (first 200 chars): {response_text[:200] if response_text else 'None'}")
                                            
                                            # Check if response_text contains JSON that looks like a tool call
                                            # Some models return tool calls as text content instead of using function_call attribute
                                            if response_text and not openai_tool_calls:
                                                import json
                                                import re

                                                # Pattern for Google model tool intent text
                                                # Examples: "Let's execite the read", "I need to use the read tool", "Using the read tool"
                                                google_tool_intent_patterns = [
                                                    r"(?:^|\n)\s*(?:Let(?:'s|s us)?)\s*(?:execite|execute|use|call)\s*(?:the\s+)?(\w+)\s*(?:tool)?",
                                                    r"(?:^|\n)\s*(?:I(?:'m| am)?|We(?:'re| are)?)\s*(?:going to |just )?(?:execite|execut(?:e|ed)?|use|call)\s*(?:the\s+)?(\w+)\s*(?:tool)?",
                                                    r"(?:^|\n)\s*(?:I(?:'m| am)?|We(?:'re| are)?)\s*(?:going to |just )?read\s+(?:the\s+)?file[s]?",
                                                    r"(?:^|\n)\s*Using\s+(?:the\s+)?(\w+)\s*(?:tool)?",
                                                ]
                                                for pattern in google_tool_intent_patterns:
                                                    tool_intent_match = re.search(pattern, response_text, re.IGNORECASE)
                                                    if tool_intent_match:
                                                        tool_name = tool_intent_match.group(1).lower() if tool_intent_match.lastindex else ''
                                                        # Map common verbs/nouns to tool names
                                                        if tool_name in ['read', 'file', 'files', 'execite', '']:
                                                            tool_name = 'read'
                                                        elif tool_name in ['write', 'create']:
                                                            tool_name = 'write'
                                                        elif tool_name in ['exec', 'command', 'shell', 'run']:
                                                            tool_name = 'exec'
                                                        elif tool_name in ['edit', 'modify']:
                                                            tool_name = 'edit'
                                                        elif tool_name in ['search', 'find']:
                                                            tool_name = 'web_search'
                                                        elif tool_name in ['browser', 'browse', 'navigate']:
                                                            tool_name = 'browser'

                                                        logging.warning(f"Google model indicated intent to use '{tool_name}' tool (matched pattern: {pattern})")

                                                        # Try to extract parameters from the response
                                                        params = {}

                                                        # Look for file path patterns
                                                        path_patterns = [
                                                            r"['\"]([^'\"]+\.md)['\"]",
                                                            r"(?:file|path)s?\s*[:=]\s*['\"]([^'\"]+)['\"]",
                                                            r"(?:path|file)\s*[:=]\s*['\"]([^'\"]+)['\"]",
                                                            r"(?:open|read)\s+['\"]([^'\"]+)['\"]",
                                                        ]
                                                        for pp in path_patterns:
                                                            path_match = re.search(pp, response_text, re.IGNORECASE)
                                                            if path_match:
                                                                params['path'] = path_match.group(1)
                                                                break

                                                        # Look for line range patterns
                                                        offset_match = re.search(r'(?:offset|start|line\s*#?)\s*[:=]?\s*(\d+)', response_text, re.IGNORECASE)
                                                        if offset_match:
                                                            params['offset'] = int(offset_match.group(1))

                                                        limit_match = re.search(r'(?:limit|lines?|count)\s*[:=]?\s*(\d+)', response_text, re.IGNORECASE)
                                                        if limit_match:
                                                            params['limit'] = int(limit_match.group(1))

                                                        # Look for command patterns (for exec tool)
                                                        if tool_name == 'exec':
                                                            cmd_patterns = [
                                                                r"(?:command|cmd|run)\s*[:=]?\s*['\"]([^'\"]+)['\"]",
                                                                r"(?:run|execute)\s+(?:command\s+)?(['\"]([^'\"]+)['\"]|\S+)",
                                                            ]
                                                            for cp in cmd_patterns:
                                                                cmd_match = re.search(cp, response_text, re.IGNORECASE)
                                                                if cmd_match:
                                                                    params['command'] = cmd_match.group(1) or cmd_match.group(2)
                                                                    break

                                                        if params:
                                                            openai_tool_calls.append({
                                                                "id": f"call_{call_id}",
                                                                "type": "function",
                                                                "function": {
                                                                    "name": tool_name,
                                                                    "arguments": json.dumps(params)
                                                                }
                                                            })
                                                            call_id += 1
                                                            logging.info(f"Converted Google tool intent to OpenAI format: {openai_tool_calls[-1]}")
                                                            # Don't clear response_text - let the text be returned alongside
                                                        break
                                            # Check if response_text contains JSON that looks like a tool call
                                            # Some models return tool calls as text content instead of using function_call attribute
                                            if response_text and not openai_tool_calls:
                                                import json
                                                import re
                                                
                                                # Pattern 0: "assistant: [...]" wrapping everything (nested format)
                                                # The entire response is wrapped in assistant: [{'type': 'text', 'text': 'tool: {...}...'}]
                                                outer_assistant_pattern = r"^assistant:\s*(\[.*\])\s*$"
                                                outer_assistant_match = re.match(outer_assistant_pattern, response_text.strip(), re.DOTALL)
                                                
                                                if outer_assistant_match:
                                                    try:
                                                        outer_content = json.loads(outer_assistant_match.group(1))
                                                        if isinstance(outer_content, list) and len(outer_content) > 0:
                                                            for item in outer_content:
                                                                if isinstance(item, dict) and item.get('type') == 'text':
                                                                    inner_text = item.get('text', '')
                                                                    # Now parse the inner text for tool calls
                                                                    inner_tool_pattern = r'tool:\s*(\{.*?\})\s*(?:assistant:\s*(\[.*\]))?\s*$'
                                                                    inner_tool_match = re.search(inner_tool_pattern, inner_text, re.DOTALL)
                                                                    
                                                                    if inner_tool_match:
                                                                        tool_json_str = inner_tool_match.group(1)
                                                                        # Parse the tool JSON - handle multi-line content
                                                                        try:
                                                                            # Extract JSON using a more robust method
                                                                            tool_start = inner_text.find('tool:')
                                                                            if tool_start != -1:
                                                                                json_start = inner_text.find('{', tool_start)
                                                                                brace_count = 0
                                                                                json_end = json_start
                                                                                for i, c in enumerate(inner_text[json_start:], json_start):
                                                                                    if c == '{':
                                                                                        brace_count += 1
                                                                                    elif c == '}':
                                                                                        brace_count -= 1
                                                                                        if brace_count == 0:
                                                                                            json_end = i + 1
                                                                                            break
                                                                                tool_json_str = inner_text[json_start:json_end]
                                                                                parsed_tool = json.loads(tool_json_str)
                                                                                
                                                                                # Convert to OpenAI tool_calls format
                                                                                openai_tool_call = {
                                                                                    "id": f"call_{call_id}",
                                                                                    "type": "function",
                                                                                    "function": {
                                                                                        "name": parsed_tool.get('action', parsed_tool.get('name', 'unknown')),
                                                                                        "arguments": json.dumps({k: v for k, v in parsed_tool.items() if k not in ['action', 'name']})
                                                                                    }
                                                                                }
                                                                                openai_tool_calls.append(openai_tool_call)
                                                                                call_id += 1
                                                                                logging.info(f"Converted nested 'tool:' format to OpenAI tool_calls: {openai_tool_call}")
                                                                                
                                                                                # Extract the final assistant text if present
                                                                                if inner_tool_match.group(2):
                                                                                    try:
                                                                                        final_assistant = json.loads(inner_tool_match.group(2))
                                                                                        if isinstance(final_assistant, list) and len(final_assistant) > 0:
                                                                                            for final_item in final_assistant:
                                                                                                if isinstance(final_item, dict) and final_item.get('type') == 'text':
                                                                                                    response_text = final_item.get('text', '')
                                                                                                    break
                                                                                            else:
                                                                                                response_text = ""
                                                                                        else:
                                                                                            response_text = ""
                                                                                    except json.JSONDecodeError:
                                                                                        response_text = ""
                                                                                else:
                                                                                    response_text = ""
                                                                        except (json.JSONDecodeError, Exception) as e:
                                                                            logging.debug(f"Failed to parse nested tool JSON: {e}")
                                                                    break
                                                    except (json.JSONDecodeError, Exception) as e:
                                                        logging.debug(f"Failed to parse outer assistant format: {e}")
                                                
                                                # Pattern 1: "tool: {...}" format (not nested)
                                                elif not openai_tool_calls:
                                                    tool_pattern = r'tool:\s*(\{[^}]*\})'
                                                    tool_match = re.search(tool_pattern, response_text, re.DOTALL)
                                                    try:
                                                        tool_json_str = tool_match.group(1)
                                                        parsed_json = json.loads(tool_json_str)
                                                        logging.info(f"Detected 'tool:' format in text content: {parsed_json}")
                                                        
                                                        # Convert to OpenAI tool_calls format
                                                        openai_tool_call = {
                                                            "id": f"call_{call_id}",
                                                            "type": "function",
                                                            "function": {
                                                                "name": parsed_json.get('action', parsed_json.get('name', 'unknown')),
                                                                "arguments": json.dumps({k: v for k, v in parsed_json.items() if k not in ['action', 'name']})
                                                            }
                                                        }
                                                        openai_tool_calls.append(openai_tool_call)
                                                        call_id += 1
                                                        logging.info(f"Converted 'tool:' format to OpenAI tool_calls: {openai_tool_call}")
                                                        
                                                        # Extract any assistant text after the tool call
                                                        assistant_pattern = r"assistant:\s*(\[.*\])"
                                                        assistant_match = re.search(assistant_pattern, response_text, re.DOTALL)
                                                        if assistant_match:
                                                            try:
                                                                assistant_content = json.loads(assistant_match.group(1))
                                                                # Extract text from the assistant content
                                                                if isinstance(assistant_content, list) and len(assistant_content) > 0:
                                                                    for item in assistant_content:
                                                                        if isinstance(item, dict) and item.get('type') == 'text':
                                                                            response_text = item.get('text', '')
                                                                            break
                                                                    else:
                                                                        response_text = ""
                                                                else:
                                                                    response_text = ""
                                                            except json.JSONDecodeError:
                                                                response_text = ""
                                                        else:
                                                            # Clear response_text since we're using tool_calls instead
                                                            response_text = ""
                                                    except (json.JSONDecodeError, Exception) as e:
                                                        logging.debug(f"Failed to parse 'tool:' format: {e}")
                                                
                                                elif content_assistant_match:
                                                    # Handle "content": "..." } assistant: [...] format
                                                    try:
                                                        tool_content = content_assistant_match.group(1)
                                                        assistant_json_str = content_assistant_match.group(2)
                                                        
                                                        logging.info(f"Detected 'content/assistant:' format - tool content length: {len(tool_content)}")
                                                        
                                                        # The content is the tool argument - treat as a write action
                                                        openai_tool_call = {
                                                            "id": f"call_{call_id}",
                                                            "type": "function",
                                                            "function": {
                                                                "name": "write",
                                                                "arguments": json.dumps({"content": tool_content})
                                                            }
                                                        }
                                                        openai_tool_calls.append(openai_tool_call)
                                                        call_id += 1
                                                        logging.info(f"Converted 'content/assistant:' format to OpenAI tool_calls")
                                                        
                                                        # Extract assistant text
                                                        try:
                                                            assistant_content = json.loads(assistant_json_str)
                                                            if isinstance(assistant_content, list) and len(assistant_content) > 0:
                                                                for item in assistant_content:
                                                                    if isinstance(item, dict) and item.get('type') == 'text':
                                                                        response_text = item.get('text', '')
                                                                        break
                                                                else:
                                                                    response_text = ""
                                                            else:
                                                                response_text = ""
                                                        except json.JSONDecodeError:
                                                            response_text = ""
                                                    except Exception as e:
                                                        logging.debug(f"Failed to parse 'content/assistant:' format: {e}")
                                                
                                                # Fall back to original JSON parsing if no special format found
                                                elif not openai_tool_calls:
                                                    try:
                                                        # Try to parse as JSON
                                                        parsed_json = json.loads(response_text.strip())
                                                        if isinstance(parsed_json, dict):
                                                            # Check if it looks like a tool call
                                                            if 'action' in parsed_json or 'function' in parsed_json or 'name' in parsed_json:
                                                                # This appears to be a tool call in JSON format
                                                                # Convert to OpenAI tool_calls format
                                                                if 'action' in parsed_json:
                                                                    # Google-style tool call
                                                                    openai_tool_call = {
                                                                        "id": f"call_{call_id}",
                                                                        "type": "function",
                                                                        "function": {
                                                                            "name": parsed_json.get('action', 'unknown'),
                                                                            "arguments": json.dumps({k: v for k, v in parsed_json.items() if k != 'action'})
                                                                        }
                                                                    }
                                                                    openai_tool_calls.append(openai_tool_call)
                                                                    call_id += 1
                                                                    logging.info(f"Detected tool call in text content: {parsed_json}")
                                                                    # Clear response_text since we're using tool_calls instead
                                                                    response_text = ""
                                                                elif 'function' in parsed_json or 'name' in parsed_json:
                                                                    # OpenAI-style tool call
                                                                    openai_tool_call = {
                                                                        "id": f"call_{call_id}",
                                                                        "type": "function",
                                                                        "function": {
                                                                            "name": parsed_json.get('name', parsed_json.get('function', 'unknown')),
                                                                            "arguments": json.dumps(parsed_json.get('arguments', parsed_json.get('parameters', {})))
                                                                        }
                                                                    }
                                                                    openai_tool_calls.append(openai_tool_call)
                                                                    call_id += 1
                                                                    logging.info(f"Detected tool call in text content: {parsed_json}")
                                                                    # Clear response_text since we're using tool_calls instead
                                                                    response_text = ""
                                                    except (json.JSONDecodeError, Exception) as e:
                                                        logging.debug(f"Response text is not valid JSON: {e}")
                                            
                                            # Set tool_calls if we have any
                                            if openai_tool_calls:
                                                tool_calls = openai_tool_calls
                                                logging.info(f"Total tool calls: {len(tool_calls)}")
                                                for tc in tool_calls:
                                                    logging.info(f"  - {tc}")
                                            else:
                                                logging.info(f"No tool calls found")
                                        else:
                                            logging.error(f"Parts is empty")
                                    else:
                                        logging.error(f"Content does NOT have 'parts' attribute")
                                else:
                                    logging.error(f"Content is empty")
                            else:
                                logging.error(f"Candidate does NOT have 'content' attribute")
                        else:
                            logging.error(f"Candidates is empty")
                    else:
                        logging.error(f"Response does NOT have 'candidates' attribute")
                    
                    logging.info(f"Final response_text length: {len(response_text)}")
                    logging.info(f"Final response_text (first 200 chars): {response_text[:200] if response_text else 'None'}")
                    logging.info(f"Final tool_calls: {tool_calls}")
                    logging.info(f"Final finish_reason: {finish_reason}")
                except Exception as e:
                    logging.error(f"GoogleProviderHandler: Exception during response parsing: {e}", exc_info=True)
                    response_text = ""
                
                logging.info(f"=== GOOGLE RESPONSE PARSING END ===")

                # Extract usage metadata from the response
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0
                
                try:
                    if hasattr(response, 'usage_metadata') and response.usage_metadata:
                        usage_metadata = response.usage_metadata
                        prompt_tokens = getattr(usage_metadata, 'prompt_token_count', 0)
                        completion_tokens = getattr(usage_metadata, 'candidates_token_count', 0)
                        total_tokens = getattr(usage_metadata, 'total_token_count', 0)
                        logging.info(f"GoogleProviderHandler: Usage metadata - prompt: {prompt_tokens}, completion: {completion_tokens}, total: {total_tokens}")
                except Exception as e:
                    logging.warning(f"GoogleProviderHandler: Could not extract usage metadata: {e}")

                # Build the OpenAI-style response
                openai_response = {
                    "id": f"google-{model}-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": f"{self.provider_id}/{model}",
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response_text if response_text else None
                        },
                        "finish_reason": finish_reason
                    }],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens
                    }
                }
                
                # Add tool_calls to the message if present
                if tool_calls:
                    openai_response["choices"][0]["message"]["tool_calls"] = tool_calls
                    # If there are tool calls, content should be None (OpenAI convention)
                    openai_response["choices"][0]["message"]["content"] = None
                    logging.info(f"Added tool_calls to response message")
                
                # Log the final response structure
                logging.info(f"=== FINAL OPENAI RESPONSE STRUCTURE ===")
                logging.info(f"Response type: {type(openai_response)}")
                logging.info(f"Response keys: {openai_response.keys()}")
                logging.info(f"Response id: {openai_response['id']}")
                logging.info(f"Response object: {openai_response['object']}")
                logging.info(f"Response created: {openai_response['created']}")
                logging.info(f"Response model: {openai_response['model']}")
                logging.info(f"Response choices count: {len(openai_response['choices'])}")
                logging.info(f"Response choices[0] index: {openai_response['choices'][0]['index']}")
                logging.info(f"Response choices[0] message role: {openai_response['choices'][0]['message']['role']}")
                logging.info(f"Response choices[0] message content length: {len(openai_response['choices'][0]['message']['content'])}")
                logging.info(f"Response choices[0] message content (first 200 chars): {openai_response['choices'][0]['message']['content'][:200]}")
                logging.info(f"Response choices[0] finish_reason: {openai_response['choices'][0]['finish_reason']}")
                logging.info(f"Response usage: {openai_response['usage']}")
                logging.info(f"=== END FINAL OPENAI RESPONSE STRUCTURE ===")
                
                # Return the response dict directly without Pydantic validation
                # Pydantic validation might be causing serialization issues
                logging.info(f"GoogleProviderHandler: Returning response dict (no validation)")
                logging.info(f"Response dict keys: {openai_response.keys()}")
                
                # Dump final response if AISBF_DEBUG is enabled
                if AISBF_DEBUG:
                    logging.info(f"=== FINAL GOOGLE RESPONSE DICT ===")
                    logging.info(f"Final response: {openai_response}")
                    logging.info(f"=== END FINAL GOOGLE RESPONSE DICT ===")
                
                return openai_response
        except Exception as e:
            import logging
            logging.error(f"GoogleProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        try:
            import logging
            logging.info("GoogleProviderHandler: Getting models list")

            # Apply rate limiting
            await self.apply_rate_limit()

            # List models using the google-genai client
            models = self.client.models.list()
            logging.info(f"GoogleProviderHandler: Models received: {models}")

            # Convert to our Model format
            result = []
            for model in models:
                result.append(Model(
                    id=model.name,
                    name=model.display_name or model.name,
                    provider_id=self.provider_id
                ))

            return result
        except Exception as e:
            import logging
            logging.error(f"GoogleProviderHandler: Error getting models: {str(e)}", exc_info=True)
            raise e

class OpenAIProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: str):
        super().__init__(provider_id, api_key)
        self.client = OpenAI(base_url=config.providers[provider_id].endpoint, api_key=api_key)

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            logging.info(f"OpenAIProviderHandler: Handling request for model {model}")
            if AISBF_DEBUG:
                logging.info(f"OpenAIProviderHandler: Messages: {messages}")
            else:
                logging.info(f"OpenAIProviderHandler: Messages count: {len(messages)}")
            if AISBF_DEBUG:
                logging.info(f"OpenAIProviderHandler: Tools: {tools}")
                logging.info(f"OpenAIProviderHandler: Tool choice: {tool_choice}")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Build request parameters
            request_params = {
                "model": model,
                "messages": [],
                "temperature": temperature,
                "stream": stream
            }
            
            # Only add max_tokens if it's not None
            if max_tokens is not None:
                request_params["max_tokens"] = max_tokens
            
            # Build messages with all fields (including tool_calls and tool_call_id)
            for msg in messages:
                message = {"role": msg["role"]}
                
                # For tool role, tool_call_id is required
                if msg["role"] == "tool":
                    if "tool_call_id" in msg and msg["tool_call_id"] is not None:
                        message["tool_call_id"] = msg["tool_call_id"]
                    else:
                        # Skip tool messages without tool_call_id
                        logger.warning(f"Skipping tool message without tool_call_id: {msg}")
                        continue
                
                if "content" in msg and msg["content"] is not None:
                    message["content"] = msg["content"]
                if "tool_calls" in msg and msg["tool_calls"] is not None:
                    message["tool_calls"] = msg["tool_calls"]
                if "name" in msg and msg["name"] is not None:
                    message["name"] = msg["name"]
                request_params["messages"].append(message)
            
            # Add tools and tool_choice if provided
            if tools is not None:
                request_params["tools"] = tools
            if tool_choice is not None:
                request_params["tool_choice"] = tool_choice

            response = self.client.chat.completions.create(**request_params)
            logging.info(f"OpenAIProviderHandler: Response received: {response}")
            self.record_success()
            
            # Dump raw response if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== RAW OPENAI RESPONSE ===")
                logging.info(f"Raw response type: {type(response)}")
                logging.info(f"Raw response: {response}")
                logging.info(f"=== END RAW OPENAI RESPONSE ===")
            
            # Return raw response without any parsing or modification
            # For streaming: return the Stream object as-is
            # For non-streaming: return the response object as-is
            logging.info(f"OpenAIProviderHandler: Returning raw response without parsing")
            return response
        except Exception as e:
            import logging
            logging.error(f"OpenAIProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        try:
            import logging
            logging.info("OpenAIProviderHandler: Getting models list")

            # Apply rate limiting
            await self.apply_rate_limit()

            models = self.client.models.list()
            logging.info(f"OpenAIProviderHandler: Models received: {models}")

            return [Model(id=model.id, name=model.id, provider_id=self.provider_id) for model in models]
        except Exception as e:
            import logging
            logging.error(f"OpenAIProviderHandler: Error getting models: {str(e)}", exc_info=True)
            raise e

class AnthropicProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: str):
        super().__init__(provider_id, api_key)
        self.client = Anthropic(api_key=api_key)

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Dict:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            logging.info(f"AnthropicProviderHandler: Handling request for model {model}")
            if AISBF_DEBUG:
                logging.info(f"AnthropicProviderHandler: Messages: {messages}")
            else:
                logging.info(f"AnthropicProviderHandler: Messages count: {len(messages)}")

            # Apply rate limiting
            await self.apply_rate_limit()

            response = self.client.messages.create(
                model=model,
                messages=[{"role": msg["role"], "content": msg["content"]} for msg in messages],
                max_tokens=max_tokens,
                temperature=temperature
            )
            logging.info(f"AnthropicProviderHandler: Response received: {response}")
            self.record_success()
            
            # Dump raw response if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== RAW ANTHROPIC RESPONSE ===")
                logging.info(f"Raw response type: {type(response)}")
                logging.info(f"Raw response: {response}")
                logging.info(f"Raw response dir: {dir(response)}")
                logging.info(f"=== END RAW ANTHROPIC RESPONSE ===")
            
            logging.info(f"=== ANTHROPIC RESPONSE PARSING START ===")
            logging.info(f"Response type: {type(response)}")
            logging.info(f"Response attributes: {dir(response)}")
            
            # Translate Anthropic response to OpenAI format
            # Anthropic returns content as an array of blocks
            content_text = ""
            tool_calls = None
            
            try:
                if hasattr(response, 'content') and response.content:
                    logging.info(f"Response has 'content' attribute")
                    logging.info(f"Content blocks: {response.content}")
                    logging.info(f"Content blocks count: {len(response.content)}")
                    
                    text_parts = []
                    openai_tool_calls = []
                    call_id = 0
                    
                    # Process all content blocks
                    for idx, block in enumerate(response.content):
                        logging.info(f"Processing block {idx}")
                        logging.info(f"Block type: {type(block)}")
                        logging.info(f"Block attributes: {dir(block)}")
                        
                        # Check for text blocks
                        if hasattr(block, 'text') and block.text:
                            logging.info(f"Block {idx} has 'text' attribute")
                            text_parts.append(block.text)
                            logging.info(f"Block {idx} text length: {len(block.text)}")
                        
                        # Check for tool_use blocks (Anthropic's function calling format)
                        if hasattr(block, 'type') and block.type == 'tool_use':
                            logging.info(f"Block {idx} is a tool_use block")
                            logging.info(f"Tool use block: {block}")
                            
                            try:
                                # Convert Anthropic tool_use to OpenAI tool_calls format
                                openai_tool_call = {
                                    "id": f"call_{call_id}",
                                    "type": "function",
                                    "function": {
                                        "name": block.name if hasattr(block, 'name') else "",
                                        "arguments": block.input if hasattr(block, 'input') else {}
                                    }
                                }
                                openai_tool_calls.append(openai_tool_call)
                                call_id += 1
                                logging.info(f"Converted tool_use to OpenAI format: {openai_tool_call}")
                            except Exception as e:
                                logging.error(f"Error converting tool_use: {e}", exc_info=True)
                    
                    # Combine all text parts
                    content_text = "\n".join(text_parts)
                    logging.info(f"Combined text length: {len(content_text)}")
                    logging.info(f"Combined text (first 200 chars): {content_text[:200] if content_text else 'None'}")
                    
                    # Set tool_calls if we have any
                    if openai_tool_calls:
                        tool_calls = openai_tool_calls
                        logging.info(f"Total tool calls: {len(tool_calls)}")
                        for tc in tool_calls:
                            logging.info(f"  - {tc}")
                    else:
                        logging.info(f"No tool calls found")
                else:
                    logging.warning(f"Response does NOT have 'content' attribute or content is empty")
                
                # Map Anthropic stop_reason to OpenAI finish_reason
                stop_reason_map = {
                    'end_turn': 'stop',
                    'max_tokens': 'length',
                    'stop_sequence': 'stop',
                    'tool_use': 'tool_calls'
                }
                stop_reason = getattr(response, 'stop_reason', 'stop')
                finish_reason = stop_reason_map.get(stop_reason, 'stop')
                logging.info(f"Anthropic stop_reason: {stop_reason}")
                logging.info(f"Mapped finish_reason: {finish_reason}")
                
            except Exception as e:
                logging.error(f"AnthropicProviderHandler: Exception during response parsing: {e}", exc_info=True)
                content_text = ""
            
            logging.info(f"=== ANTHROPIC RESPONSE PARSING END ===")
            
            # Build OpenAI-style response
            openai_response = {
                "id": f"anthropic-{model}-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": f"{self.provider_id}/{model}",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content_text if content_text else None
                    },
                    "finish_reason": finish_reason
                }],
                "usage": {
                    "prompt_tokens": getattr(response, "usage", {}).get("input_tokens", 0),
                    "completion_tokens": getattr(response, "usage", {}).get("output_tokens", 0),
                    "total_tokens": getattr(response, "usage", {}).get("input_tokens", 0) + getattr(response, "usage", {}).get("output_tokens", 0)
                }
            }
            
            # Add tool_calls to the message if present
            if tool_calls:
                openai_response["choices"][0]["message"]["tool_calls"] = tool_calls
                # If there are tool calls, content should be None (OpenAI convention)
                openai_response["choices"][0]["message"]["content"] = None
                logging.info(f"Added tool_calls to response message")
            
            logging.info(f"=== FINAL ANTHROPIC RESPONSE STRUCTURE ===")
            logging.info(f"Response id: {openai_response['id']}")
            logging.info(f"Response model: {openai_response['model']}")
            logging.info(f"Response choices[0] message content: {openai_response['choices'][0]['message']['content']}")
            logging.info(f"Response choices[0] message tool_calls: {openai_response['choices'][0]['message'].get('tool_calls')}")
            logging.info(f"Response choices[0] finish_reason: {openai_response['choices'][0]['finish_reason']}")
            logging.info(f"Response usage: {openai_response['usage']}")
            logging.info(f"=== END FINAL ANTHROPIC RESPONSE STRUCTURE ===")
            
            # Return the response dict directly without Pydantic validation
            # Pydantic validation might be causing serialization issues
            logging.info(f"AnthropicProviderHandler: Returning response dict (no validation)")
            logging.info(f"Response dict keys: {openai_response.keys()}")
            
            # Dump final response dict if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== FINAL ANTHROPIC RESPONSE DICT ===")
                logging.info(f"Final response: {openai_response}")
                logging.info(f"=== END FINAL ANTHROPIC RESPONSE DICT ===")
            
            return openai_response
        except Exception as e:
            import logging
            logging.error(f"AnthropicProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        # Anthropic doesn't have a models list endpoint, so we'll return a static list
        return [
            Model(id="claude-3-haiku-20240307", name="Claude 3 Haiku", provider_id=self.provider_id),
            Model(id="claude-3-sonnet-20240229", name="Claude 3 Sonnet", provider_id=self.provider_id),
            Model(id="claude-3-opus-20240229", name="Claude 3 Opus", provider_id=self.provider_id)
        ]

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
        
        # Initialize KiroAuthManager with credentials from config
        self.auth_manager = None
        self._init_auth_manager()
        
        # HTTP client for making requests
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
        
    def _init_auth_manager(self):
        """Initialize KiroAuthManager with credentials from config"""
        try:
            from .kiro_auth import KiroAuthManager
            
            # Get Kiro-specific configuration from provider config
            kiro_config = getattr(self.provider_config, 'kiro_config', None)
            
            if not kiro_config:
                import logging
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
            
            import logging
            logging.info(f"KiroProviderHandler: Auth manager initialized for region {region}")
            
        except Exception as e:
            import logging
            logging.error(f"Failed to initialize KiroAuthManager: {e}")
            self.auth_manager = None

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Union[Dict, object]:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            import json
            import uuid
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

            # Get access token and profile ARN
            access_token = await self.auth_manager.get_access_token()
            profile_arn = self.auth_manager.profile_arn
            
            if not profile_arn:
                raise Exception("Profile ARN not available. Please configure Kiro credentials.")
            
            # Use full kiro-gateway conversion pipeline
            from .kiro_converters_openai import build_kiro_payload_from_dict
            
            conversation_id = str(uuid.uuid4())
            
            # Build Kiro API payload using full conversion pipeline
            # This handles ALL features: tools, images, message merging, role normalization, etc.
            payload = build_kiro_payload_from_dict(
                model=model,
                messages=messages,
                tools=tools,
                conversation_id=conversation_id,
                profile_arn=profile_arn
            )
            
            if AISBF_DEBUG:
                logging.info(f"KiroProviderHandler: Kiro payload: {json.dumps(payload, indent=2)}")
            
            # Make request to Kiro API
            headers = self.auth_manager.get_auth_headers(access_token)
            headers["Content-Type"] = "application/json"
            
            kiro_api_url = f"https://q.{self.region}.amazonaws.com/generateAssistantResponse"
            
            logging.info(f"KiroProviderHandler: Sending request to {kiro_api_url}")
            
            response = await self.client.post(
                kiro_api_url,
                json=payload,
                headers=headers
            )
            
            # Check for 429 rate limit error before raising
            if response.status_code == 429:
                try:
                    response_data = response.json()
                except Exception:
                    response_data = response.text
                
                # Handle 429 error with intelligent parsing
                self.handle_429_error(response_data, dict(response.headers))
                
                # Re-raise the error after handling
                response.raise_for_status()
            
            response.raise_for_status()
            response_data = response.json()
            
            if AISBF_DEBUG:
                logging.info(f"KiroProviderHandler: Raw Kiro response: {json.dumps(response_data, indent=2)}")
            
            logging.info(f"KiroProviderHandler: Response received")
            
            # Parse Kiro response and convert to OpenAI format
            openai_response = self._parse_kiro_response(response_data, model)
            
            self.record_success()
            return openai_response
            
        except Exception as e:
            import logging
            logging.error(f"KiroProviderHandler: Error: {str(e)}", exc_info=True)
            self.record_failure()
            raise e

    def _parse_kiro_response(self, kiro_response: Dict, model: str) -> Dict:
        """
        Parse Kiro API response and convert to OpenAI format.
        
        Handles:
        - Text content
        - Tool calls (toolUses)
        - Finish reasons
        - Usage statistics
        """
        import logging
        import json
        
        # Extract assistant message content
        assistant_content = ""
        tool_calls = None
        finish_reason = "stop"
        
        # Kiro response structure varies, try different paths
        if "message" in kiro_response:
            assistant_content = kiro_response["message"]
        elif "content" in kiro_response:
            assistant_content = kiro_response["content"]
        elif "conversationState" in kiro_response:
            conv_state = kiro_response["conversationState"]
            if "currentMessage" in conv_state:
                current_msg = conv_state["currentMessage"]
                if "assistantResponseMessage" in current_msg:
                    assistant_msg = current_msg["assistantResponseMessage"]
                    assistant_content = assistant_msg.get("content", "")
                    
                    # Check for tool uses
                    if "toolUses" in assistant_msg:
                        tool_uses = assistant_msg["toolUses"]
                        tool_calls = []
                        for idx, tool_use in enumerate(tool_uses):
                            tool_call = {
                                "id": tool_use.get("toolUseId", f"call_{idx}"),
                                "type": "function",
                                "function": {
                                    "name": tool_use.get("name", ""),
                                    "arguments": json.dumps(tool_use.get("input", {}))
                                }
                            }
                            tool_calls.append(tool_call)
                        
                        if tool_calls:
                            finish_reason = "tool_calls"
                            logging.info(f"KiroProviderHandler: Parsed {len(tool_calls)} tool calls from response")
        
        # Build OpenAI-style response
        openai_response = {
            "id": f"kiro-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": f"{self.provider_id}/{model}",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": assistant_content if not tool_calls else None
                },
                "finish_reason": finish_reason
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        }
        
        # Add tool_calls if present
        if tool_calls:
            openai_response["choices"][0]["message"]["tool_calls"] = tool_calls
        
        return openai_response

    async def get_models(self) -> List[Model]:
        try:
            import logging
            logging.info("KiroProviderHandler: Getting models list")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Return static list of Claude models available through Kiro
            return [
                Model(id="anthropic.claude-3-5-sonnet-20241022-v2:0", name="Claude 3.5 Sonnet v2", provider_id=self.provider_id),
                Model(id="anthropic.claude-3-5-haiku-20241022-v1:0", name="Claude 3.5 Haiku", provider_id=self.provider_id),
                Model(id="anthropic.claude-3-5-sonnet-20240620-v1:0", name="Claude 3.5 Sonnet v1", provider_id=self.provider_id),
                Model(id="anthropic.claude-sonnet-3-5-v2", name="Claude 3.5 Sonnet v2 (alias)", provider_id=self.provider_id),
                Model(id="claude-sonnet-4-5", name="Claude 3.5 Sonnet v2 (short)", provider_id=self.provider_id),
                Model(id="claude-haiku-4-5", name="Claude 3.5 Haiku (short)", provider_id=self.provider_id),
            ]
        except Exception as e:
            import logging
            logging.error(f"KiroProviderHandler: Error getting models: {str(e)}", exc_info=True)
            raise e

class OllamaProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: Optional[str] = None):
        super().__init__(provider_id, api_key)
        # Increase timeout for Ollama requests (especially for cloud models)
        # Using separate timeouts for connect, read, write, and pool
        timeout = httpx.Timeout(
            connect=60.0,      # 60 seconds to establish connection
            read=300.0,         # 5 minutes to read response
            write=60.0,         # 60 seconds to write request
            pool=60.0           # 60 seconds for pool acquisition
        )
        self.client = httpx.AsyncClient(base_url=config.providers[provider_id].endpoint, timeout=timeout)

    async def handle_request(self, model: str, messages: List[Dict], max_tokens: Optional[int] = None,
                           temperature: Optional[float] = 1.0, stream: Optional[bool] = False,
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Dict:
        """
        Handle request for Ollama provider.
        Note: Ollama doesn't support tools/tool_choice, so these parameters are accepted but ignored.
        """
        import logging
        import json
        logger = logging.getLogger(__name__)
        logger.info(f"=== OllamaProviderHandler.handle_request START ===")
        logger.info(f"Provider ID: {self.provider_id}")
        logger.info(f"Endpoint: {self.client.base_url}")
        logger.info(f"Model: {model}")
        logger.info(f"Messages count: {len(messages)}")
        logger.info(f"Max tokens: {max_tokens}")
        logger.info(f"Temperature: {temperature}")
        logger.info(f"Stream: {stream}")
        logger.info(f"API key provided: {bool(self.api_key)}")
        
        if self.is_rate_limited():
            logger.error("Provider is rate limited")
            raise Exception("Provider rate limited")

        try:
            # Test connection first
            logger.info("Testing Ollama connection...")
            try:
                health_response = await self.client.get("/api/tags", timeout=10.0)
                logger.info(f"Ollama health check passed: {health_response.status_code}")
                logger.info(f"Available models: {health_response.json().get('models', [])}")
            except Exception as e:
                logger.error(f"Ollama health check failed: {str(e)}")
                logger.error(f"Cannot connect to Ollama at {self.client.base_url}")
                logger.error(f"Please ensure Ollama is running and accessible")
                raise Exception(f"Cannot connect to Ollama at {self.client.base_url}: {str(e)}")
            
            # Apply rate limiting
            logger.info("Applying rate limiting...")
            await self.apply_rate_limit()
            logger.info("Rate limiting applied")

            prompt = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
            logger.info(f"Prompt length: {len(prompt)} characters")
            
            # Build options with only non-None values
            options = {"temperature": temperature}
            if max_tokens is not None:
                options["num_predict"] = max_tokens
            
            request_data = {
                "model": model,
                "prompt": prompt,
                "options": options,
                "stream": False  # Explicitly disable streaming for non-streaming requests
            }
            
            # Add API key to headers if provided (for Ollama cloud models)
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                logger.info("API key added to request headers for Ollama cloud")
            
            logger.info(f"Sending POST request to {self.client.base_url}/api/generate")
            logger.info(f"Request data: {request_data}")
            logger.info(f"Request headers: {headers}")
            logger.info(f"Client timeout: {self.client.timeout}")
            
            response = await self.client.post("/api/generate", json=request_data, headers=headers)
            logger.info(f"Response status code: {response.status_code}")
            logger.info(f"Response content type: {response.headers.get('content-type')}")
            logger.info(f"Response content length: {len(response.content)} bytes")
            logger.info(f"Raw response content (first 500 chars): {response.text[:500]}")
            
            # Check for 429 rate limit error before raising
            if response.status_code == 429:
                try:
                    response_data = response.json()
                except Exception:
                    response_data = response.text
                
                # Handle 429 error with intelligent parsing
                self.handle_429_error(response_data, dict(response.headers))
                
                # Re-raise the error after handling
                response.raise_for_status()
            
            response.raise_for_status()
            
            # Ollama may return multiple JSON objects, parse them all
            content = response.text
            logger.info(f"Attempting to parse response as JSON...")
            
            try:
                # Try parsing as single JSON first
                response_json = response.json()
                logger.info(f"Response parsed as single JSON: {response_json}")
            except json.JSONDecodeError as e:
                # If that fails, try parsing multiple JSON objects
                logger.warning(f"Failed to parse as single JSON: {e}")
                logger.info(f"Attempting to parse as multiple JSON objects...")
                
                # Parse multiple JSON objects (one per line)
                responses = []
                for line in content.strip().split('\n'):
                    if line.strip():
                        try:
                            obj = json.loads(line)
                            responses.append(obj)
                        except json.JSONDecodeError as line_error:
                            logger.error(f"Failed to parse line: {line}")
                            logger.error(f"Error: {line_error}")
                
                if not responses:
                    raise Exception("No valid JSON objects found in response")
                
                # Combine responses - take the last complete response
                # Ollama sends multiple chunks, we want the final one
                response_json = responses[-1]
                logger.info(f"Parsed {len(responses)} JSON objects, using last one: {response_json}")
            
            logger.info(f"Final response: {response_json}")
            self.record_success()
            
            # Dump raw response if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== RAW OLLAMA RESPONSE ===")
                logging.info(f"Raw response JSON: {response_json}")
                logging.info(f"=== END RAW OLLAMA RESPONSE ===")
            
            logger.info(f"=== OllamaProviderHandler.handle_request END ===")
            
            # Convert Ollama response to OpenAI-style format
            openai_response = {
                "id": f"ollama-{model}-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": f"{self.provider_id}/{model}",
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_json.get("response", "")
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": response_json.get("prompt_eval_count", 0),
                    "completion_tokens": response_json.get("eval_count", 0),
                    "total_tokens": response_json.get("prompt_eval_count", 0) + response_json.get("eval_count", 0)
                }
            }
            
            # Dump final response dict if AISBF_DEBUG is enabled
            if AISBF_DEBUG:
                logging.info(f"=== FINAL OLLAMA RESPONSE DICT ===")
                logging.info(f"Final response: {openai_response}")
                logging.info(f"=== END FINAL OLLAMA RESPONSE DICT ===")
            
            return openai_response
        except Exception as e:
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        # Apply rate limiting
        await self.apply_rate_limit()

        response = await self.client.get("/api/tags")
        response.raise_for_status()
        models = response.json().get('models', [])
        return [Model(id=model, name=model, provider_id=self.provider_id) for model in models]

PROVIDER_HANDLERS = {
    'google': GoogleProviderHandler,
    'openai': OpenAIProviderHandler,
    'anthropic': AnthropicProviderHandler,
    'ollama': OllamaProviderHandler,
    'kiro': KiroProviderHandler
}

def get_provider_handler(provider_id: str, api_key: Optional[str] = None) -> BaseProviderHandler:
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"=== get_provider_handler START ===")
    logger.info(f"Provider ID: {provider_id}")
    logger.info(f"API key provided: {bool(api_key)}")
    
    provider_config = config.get_provider(provider_id)
    logger.info(f"Provider config: {provider_config}")
    logger.info(f"Provider type: {provider_config.type}")
    logger.info(f"Provider endpoint: {provider_config.endpoint}")
    
    handler_class = PROVIDER_HANDLERS.get(provider_config.type)
    logger.info(f"Handler class: {handler_class.__name__ if handler_class else 'None'}")
    logger.info(f"Available handler types: {list(PROVIDER_HANDLERS.keys())}")
    
    if not handler_class:
        logger.error(f"Unsupported provider type: {provider_config.type}")
        raise ValueError(f"Unsupported provider type: {provider_config.type}")
    
    # All handlers now accept api_key as optional parameter
    logger.info(f"Creating handler with provider_id and optional api_key")
    handler = handler_class(provider_id, api_key)
    
    logger.info(f"Handler created: {handler.__class__.__name__}")
    logger.info(f"=== get_provider_handler END ===")
    return handler
