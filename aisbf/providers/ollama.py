"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Ollama provider handler.

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
import time
from typing import Dict, List, Optional, Union
from ..models import Model
from ..config import config
from .base import BaseProviderHandler, AISBF_DEBUG


class OllamaProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: Optional[str] = None):
        super().__init__(provider_id, api_key)
        timeout = httpx.Timeout(
            connect=60.0,
            read=300.0,
            write=60.0,
            pool=60.0
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
            logger.info("Testing Ollama connection...")
            try:
                health_response = await self.client.get("/api/tags", timeout=10.0)
                logger.info(f"Ollama health check passed: {health_response.status_code}")
                models = health_response.json().get('models', [])
                if AISBF_DEBUG:
                    response_str = str(models)
                    if len(response_str) > 1024:
                        response_str = response_str[:1024] + f" ... [TRUNCATED, total length: {len(response_str)} chars]"
                    logger.info(f"Available models: {response_str}")
                else:
                    logger.info(f"Available models: {len(models)} models")
            except Exception as e:
                logger.error(f"Ollama health check failed: {str(e)}")
                logger.error(f"Cannot connect to Ollama at {self.client.base_url}")
                logger.error(f"Please ensure Ollama is running and accessible")
                raise Exception(f"Cannot connect to Ollama at {self.client.base_url}: {str(e)}")
            
            logger.info("Applying rate limiting...")
            await self.apply_rate_limit()
            logger.info("Rate limiting applied")

            prompt = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])
            logger.info(f"Prompt length: {len(prompt)} characters")
            
            options = {"temperature": temperature}
            if max_tokens is not None:
                options["num_predict"] = max_tokens
            
            request_data = {
                "model": model,
                "prompt": prompt,
                "options": options,
                "stream": False
            }
            
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
            
            if response.status_code == 429:
                try:
                    response_data = response.json()
                except Exception:
                    response_data = response.text
                
                self.handle_429_error(response_data, dict(response.headers))
                
                response.raise_for_status()
            
            response.raise_for_status()
            
            content = response.text
            logger.info(f"Attempting to parse response as JSON...")
            
            try:
                response_json = response.json()
                logger.info(f"Response parsed as single JSON: {response_json}")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse as single JSON: {e}")
                logger.info(f"Attempting to parse as multiple JSON objects...")
                
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
                
                response_json = responses[-1]
                logger.info(f"Parsed {len(responses)} JSON objects, using last one: {response_json}")
            
            logger.info(f"Final response: {response_json}")
            self.record_success()
            
            if AISBF_DEBUG:
                logging.info(f"=== RAW OLLAMA RESPONSE ===")
                logging.info(f"Raw response JSON: {response_json}")
                logging.info(f"=== END RAW OLLAMA RESPONSE ===")
            
            logger.info(f"=== OllamaProviderHandler.handle_request END ===")
            
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
            
            if AISBF_DEBUG:
                logging.info(f"=== FINAL OLLAMA RESPONSE DICT ===")
                logging.info(f"Final response: {openai_response}")
                logging.info(f"=== END FINAL OLLAMA RESPONSE DICT ===")
            
            return openai_response
        except Exception as e:
            self.record_failure()
            raise e

    async def get_models(self) -> List[Model]:
        await self.apply_rate_limit()

        response = await self.client.get("/api/tags")
        response.raise_for_status()
        models = response.json().get('models', [])
        return [Model(id=model, name=model, provider_id=self.provider_id) for model in models]
