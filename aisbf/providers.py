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

# Check if debug mode is enabled
AISBF_DEBUG = os.environ.get('AISBF_DEBUG', '').lower() in ('true', '1', 'yes')

class BaseProviderHandler:
    def __init__(self, provider_id: str, api_key: Optional[str] = None):
        self.provider_id = provider_id
        self.api_key = api_key
        self.error_tracking = config.error_tracking[provider_id]
        self.last_request_time = 0
        self.rate_limit = config.providers[provider_id].rate_limit

    def is_rate_limited(self) -> bool:
        if self.error_tracking['disabled_until'] and self.error_tracking['disabled_until'] > time.time():
            return True
        return False

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
            self.error_tracking['disabled_until'] = time.time() + 300  # 5 minutes
            disabled_until_time = self.error_tracking['disabled_until']
            cooldown_remaining = int(disabled_until_time - time.time())
            logger.error(f"!!! PROVIDER DISABLED !!!")
            logger.error(f"Provider: {self.provider_id}")
            logger.error(f"Reason: 3 consecutive failures reached")
            logger.error(f"Disabled until: {disabled_until_time}")
            logger.error(f"Cooldown period: {cooldown_remaining} seconds (5 minutes)")
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
                           tools: Optional[List[Dict]] = None, tool_choice: Optional[Union[str, Dict]] = None) -> Dict:
        if self.is_rate_limited():
            raise Exception("Provider rate limited")

        try:
            import logging
            logging.info(f"GoogleProviderHandler: Handling request for model {model}")
            if AISBF_DEBUG:
                logging.info(f"GoogleProviderHandler: Messages: {messages}")
            else:
                logging.info(f"GoogleProviderHandler: Messages count: {len(messages)}")

            # Apply rate limiting
            await self.apply_rate_limit()

            # Build content from messages
            content = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

            # Build config with only non-None values
            config = {"temperature": temperature}
            if max_tokens is not None:
                config["max_output_tokens"] = max_tokens

            # Generate content using the google-genai client
            response = self.client.models.generate_content(
                model=model,
                contents=content,
                config=config
            )

            logging.info(f"GoogleProviderHandler: Response received: {response}")
            self.record_success()

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
                "model": model,
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
            
            # Validate the response structure using Pydantic model
            try:
                from .models import ChatCompletionResponse
                validated_response = ChatCompletionResponse(**openai_response)
                logging.info(f"Response validated successfully against ChatCompletionResponse model")
                logging.info(f"Validated response type: {type(validated_response)}")
                # Return as dict for JSON serialization
                response_dict = validated_response.model_dump()
            except Exception as e:
                logging.error(f"Response validation failed: {e}", exc_info=True)
                logging.error(f"Returning unvalidated response")
                response_dict = openai_response
            
            # Wrap in JSONResponse for proper serialization
            from fastapi.responses import JSONResponse
            logging.info(f"GoogleProviderHandler: Returning JSONResponse")
            return JSONResponse(content=response_dict)
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
            
            # Return Stream object directly for streaming, otherwise dump to dict
            if stream:
                return response
            return response.model_dump()
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
                "model": model,
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
            
            # Validate the response structure using Pydantic model
            try:
                from .models import ChatCompletionResponse
                validated_response = ChatCompletionResponse(**openai_response)
                logging.info(f"Response validated successfully against ChatCompletionResponse model")
                logging.info(f"Validated response type: {type(validated_response)}")
                # Return as dict for JSON serialization
                response_dict = validated_response.model_dump()
            except Exception as e:
                logging.error(f"Response validation failed: {e}", exc_info=True)
                logging.error(f"Returning unvalidated response")
                response_dict = openai_response
            
            # Wrap in JSONResponse for proper serialization
            from fastapi.responses import JSONResponse
            logging.info(f"AnthropicProviderHandler: Returning JSONResponse")
            return JSONResponse(content=response_dict)
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
            logger.info(f"=== OllamaProviderHandler.handle_request END ===")
            
            # Convert Ollama response to OpenAI-style format
            return {
                "id": f"ollama-{model}-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
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
    'ollama': OllamaProviderHandler
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
