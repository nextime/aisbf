"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Anthropic provider handler (API key-based).

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
import time
from typing import Dict, List, Optional, Union
from anthropic import Anthropic
from ..models import Model
from ..config import config
from ..utils import count_messages_tokens
from .base import BaseProviderHandler, AnthropicFormatConverter, AISBF_DEBUG


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

            # Check if native caching is enabled for this provider
            provider_config = config.providers.get(self.provider_id)
            enable_native_caching = getattr(provider_config, 'enable_native_caching', False)
            min_cacheable_tokens = getattr(provider_config, 'min_cacheable_tokens', 1000)

            logging.info(f"AnthropicProviderHandler: Native caching enabled: {enable_native_caching}")
            if enable_native_caching:
                logging.info(f"AnthropicProviderHandler: Min cacheable tokens: {min_cacheable_tokens}")

            # Convert OpenAI messages to Anthropic format
            system_message = None
            anthropic_messages = []
            
            for msg in messages:
                role = msg.get('role')
                content = msg.get('content')
                
                if role == 'system':
                    system_message = content
                    logging.info(f"AnthropicProviderHandler: Extracted system message ({len(content) if content else 0} chars)")
                
                elif role == 'tool':
                    tool_call_id = msg.get('tool_call_id', msg.get('name', 'unknown'))
                    tool_result_block = {
                        'type': 'tool_result',
                        'tool_use_id': tool_call_id,
                        'content': content or ""
                    }
                    
                    if anthropic_messages and anthropic_messages[-1]['role'] == 'user':
                        last_content = anthropic_messages[-1]['content']
                        if isinstance(last_content, str):
                            anthropic_messages[-1]['content'] = [
                                {'type': 'text', 'text': last_content},
                                tool_result_block
                            ]
                        elif isinstance(last_content, list):
                            anthropic_messages[-1]['content'].append(tool_result_block)
                        logging.info(f"AnthropicProviderHandler: Appended tool_result to existing user message")
                    else:
                        anthropic_messages.append({
                            'role': 'user',
                            'content': [tool_result_block]
                        })
                        logging.info(f"AnthropicProviderHandler: Created new user message with tool_result")
                
                elif role == 'assistant':
                    tool_calls = msg.get('tool_calls')
                    
                    if tool_calls:
                        content_blocks = []
                        
                        if content and isinstance(content, str) and content.strip():
                            content_blocks.append({'type': 'text', 'text': content})
                        elif content and isinstance(content, list):
                            content_blocks.extend(content)
                        
                        import json as _json
                        for tc in tool_calls:
                            tool_id = tc.get('id', f"toolu_{len(content_blocks)}")
                            function = tc.get('function', {})
                            tool_name = function.get('name', '')
                            arguments = function.get('arguments', {})
                            if isinstance(arguments, str):
                                try:
                                    arguments = _json.loads(arguments)
                                except _json.JSONDecodeError:
                                    logging.warning(f"AnthropicProviderHandler: Failed to parse tool arguments: {arguments}")
                                    arguments = {}
                            
                            content_blocks.append({
                                'type': 'tool_use',
                                'id': tool_id,
                                'name': tool_name,
                                'input': arguments
                            })
                            logging.info(f"AnthropicProviderHandler: Converted tool_call to tool_use: {tool_name}")
                        
                        if content_blocks:
                            anthropic_messages.append({
                                'role': 'assistant',
                                'content': content_blocks
                            })
                    else:
                        if content is not None:
                            anthropic_messages.append({
                                'role': 'assistant',
                                'content': content
                            })
                        else:
                            logging.info(f"AnthropicProviderHandler: Skipping assistant message with None content")
                
                elif role == 'user':
                    if isinstance(content, list):
                        content_blocks = []
                        for block in content:
                            if isinstance(block, dict):
                                block_type = block.get('type', '')
                                if block_type == 'text':
                                    content_blocks.append(block)
                                elif block_type == 'image_url':
                                    image_url_obj = block.get('image_url', {})
                                    url = image_url_obj.get('url', '') if isinstance(image_url_obj, dict) else ''
                                    if url.startswith('data:'):
                                        try:
                                            header, data = url.split(',', 1)
                                            media_type = header.split(';')[0].replace('data:', '')
                                            content_blocks.append({
                                                'type': 'image',
                                                'source': {
                                                    'type': 'base64',
                                                    'media_type': media_type,
                                                    'data': data
                                                }
                                            })
                                        except (ValueError, IndexError) as e:
                                            logging.warning(f"AnthropicProviderHandler: Failed to parse data URL: {e}")
                                    elif url.startswith(('http://', 'https://')):
                                        content_blocks.append({
                                            'type': 'image',
                                            'source': {
                                                'type': 'url',
                                                'url': url
                                            }
                                        })
                                else:
                                    content_blocks.append(block)
                            elif isinstance(block, str):
                                content_blocks.append({'type': 'text', 'text': block})
                        
                        anthropic_messages.append({
                            'role': 'user',
                            'content': content_blocks if content_blocks else content or ""
                        })
                    else:
                        anthropic_messages.append({
                            'role': 'user',
                            'content': content or ""
                        })
                
                else:
                    logging.warning(f"AnthropicProviderHandler: Unknown message role '{role}', treating as user")
                    anthropic_messages.append({
                        'role': 'user',
                        'content': content or ""
                    })
            
            logging.info(f"AnthropicProviderHandler: Converted {len(messages)} OpenAI messages to {len(anthropic_messages)} Anthropic messages")
            if system_message:
                logging.info(f"AnthropicProviderHandler: System message extracted ({len(system_message)} chars)")
            
            # Apply cache_control if native caching is enabled
            if enable_native_caching:
                cumulative_tokens = 0
                for i, msg in enumerate(anthropic_messages):
                    message_tokens = count_messages_tokens([{'role': msg['role'], 'content': msg['content'] if isinstance(msg['content'], str) else str(msg['content'])}], model)
                    cumulative_tokens += message_tokens
                    
                    if i < len(anthropic_messages) - 2 and cumulative_tokens >= min_cacheable_tokens:
                        content = msg.get('content')
                        if isinstance(content, str) and content.strip():
                            msg['content'] = [
                                {
                                    'type': 'text',
                                    'text': content,
                                    'cache_control': {'type': 'ephemeral'}
                                }
                            ]
                        elif isinstance(content, list) and content:
                            content[-1]['cache_control'] = {'type': 'ephemeral'}
                        logging.info(f"AnthropicProviderHandler: Applied cache_control to message {i} ({message_tokens} tokens, cumulative: {cumulative_tokens})")
                
                # Also apply cache_control to system message if present
                if system_message:
                    system_message_param = [{
                        'type': 'text',
                        'text': system_message,
                        'cache_control': {'type': 'ephemeral'}
                    }]
                else:
                    system_message_param = None
            else:
                system_message_param = system_message
            
            # Convert OpenAI tools to Anthropic format
            anthropic_tools = None
            if tools:
                anthropic_tools = []
                for tool in tools:
                    if tool.get("type") == "function":
                        function = tool.get("function", {})
                        anthropic_tools.append({
                            "name": function.get("name", ""),
                            "description": function.get("description", ""),
                            "input_schema": function.get("parameters", {})
                        })
                        logging.info(f"AnthropicProviderHandler: Converted tool to Anthropic format: {function.get('name')}")
                if not anthropic_tools:
                    anthropic_tools = None
            
            # Convert OpenAI tool_choice to Anthropic format
            anthropic_tool_choice = None
            if tool_choice and anthropic_tools:
                if isinstance(tool_choice, str):
                    if tool_choice == "auto":
                        anthropic_tool_choice = {"type": "auto"}
                    elif tool_choice == "required":
                        anthropic_tool_choice = {"type": "any"}
                    elif tool_choice == "none":
                        anthropic_tool_choice = None
                elif isinstance(tool_choice, dict):
                    if tool_choice.get("type") == "function":
                        func_name = tool_choice.get("function", {}).get("name")
                        if func_name:
                            anthropic_tool_choice = {"type": "tool", "name": func_name}
            
            # Build API call parameters
            api_params = {
                'model': model,
                'messages': anthropic_messages,
                'max_tokens': max_tokens or 4096,
                'temperature': temperature,
            }
            
            if system_message_param:
                api_params['system'] = system_message_param
            
            if anthropic_tools:
                api_params['tools'] = anthropic_tools
            
            if anthropic_tool_choice:
                api_params['tool_choice'] = anthropic_tool_choice
            
            if AISBF_DEBUG:
                import json as _json
                logging.info(f"=== ANTHROPIC API REQUEST PAYLOAD ===")
                debug_params = dict(api_params)
                logging.info(f"Request keys: {list(debug_params.keys())}")
                logging.info(f"Model: {debug_params.get('model')}")
                logging.info(f"Messages count: {len(debug_params.get('messages', []))}")
                logging.info(f"Tools count: {len(debug_params.get('tools', []) or [])}")
                logging.info(f"Tool choice: {debug_params.get('tool_choice')}")
                logging.info(f"System: {'present' if debug_params.get('system') else 'none'}")
                logging.info(f"Full payload: {_json.dumps(debug_params, indent=2, default=str)}")
                logging.info(f"=== END ANTHROPIC API REQUEST PAYLOAD ===")
            
            response = self.client.messages.create(**api_params)
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
                    
                    for idx, block in enumerate(response.content):
                        logging.info(f"Processing block {idx}")
                        logging.info(f"Block type: {type(block)}")
                        logging.info(f"Block attributes: {dir(block)}")
                        
                        if hasattr(block, 'text') and block.text:
                            logging.info(f"Block {idx} has 'text' attribute")
                            text_parts.append(block.text)
                            logging.info(f"Block {idx} text length: {len(block.text)}")
                        
                        if hasattr(block, 'type') and block.type == 'tool_use':
                            logging.info(f"Block {idx} is a tool_use block")
                            logging.info(f"Tool use block: {block}")
                            
                            try:
                                import json as _json_tc
                                raw_input = block.input if hasattr(block, 'input') else {}
                                arguments_str = _json_tc.dumps(raw_input) if isinstance(raw_input, dict) else str(raw_input)
                                openai_tool_call = {
                                    "id": block.id if hasattr(block, 'id') else f"call_{call_id}",
                                    "type": "function",
                                    "function": {
                                        "name": block.name if hasattr(block, 'name') else "",
                                        "arguments": arguments_str
                                    }
                                }
                                openai_tool_calls.append(openai_tool_call)
                                call_id += 1
                                logging.info(f"Converted tool_use to OpenAI format: {openai_tool_call}")
                            except Exception as e:
                                logging.error(f"Error converting tool_use: {e}", exc_info=True)
                    
                    content_text = "\n".join(text_parts)
                    logging.info(f"Combined text length: {len(content_text)}")
                    logging.info(f"Combined text (first 200 chars): {content_text[:200] if content_text else 'None'}")
                    
                    if openai_tool_calls:
                        tool_calls = openai_tool_calls
                        logging.info(f"Total tool calls: {len(tool_calls)}")
                        for tc in tool_calls:
                            logging.info(f"  - {tc}")
                    else:
                        logging.info(f"No tool calls found")
                else:
                    logging.warning(f"Response does NOT have 'content' attribute or content is empty")
                
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
                    "prompt_tokens": getattr(getattr(response, "usage", None), "input_tokens", 0) or 0,
                    "completion_tokens": getattr(getattr(response, "usage", None), "output_tokens", 0) or 0,
                    "total_tokens": (getattr(getattr(response, "usage", None), "input_tokens", 0) or 0) + (getattr(getattr(response, "usage", None), "output_tokens", 0) or 0)
                }
            }
            
            if tool_calls:
                openai_response["choices"][0]["message"]["tool_calls"] = tool_calls
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
            
            logging.info(f"AnthropicProviderHandler: Returning response dict (no validation)")
            logging.info(f"Response dict keys: {openai_response.keys()}")
            
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
        """
        Return list of available Anthropic models.
        """
        try:
            import logging
            logging.info("=" * 80)
            logging.info("AnthropicProviderHandler: Starting model list retrieval")
            logging.info("=" * 80)

            await self.apply_rate_limit()

            try:
                logging.info("AnthropicProviderHandler: Attempting to fetch models from API...")
                logging.info("AnthropicProviderHandler: Note: Anthropic doesn't currently provide a public models endpoint")
                logging.info("AnthropicProviderHandler: Checking if endpoint is now available...")
                
                response = self.client.models.list()
                if response:
                    logging.info(f"AnthropicProviderHandler: ✓ API call successful!")
                    logging.info(f"AnthropicProviderHandler: Retrieved models from API")
                    
                    models = [Model(id=model.id, name=model.id, provider_id=self.provider_id) for model in response]
                    
                    for model in models:
                        logging.info(f"AnthropicProviderHandler:   - {model.id}")
                    
                    logging.info("=" * 80)
                    logging.info(f"AnthropicProviderHandler: ✓ SUCCESS - Returning {len(models)} models from API")
                    logging.info(f"AnthropicProviderHandler: Source: Dynamic API retrieval")
                    logging.info("=" * 80)
                    return models
            except AttributeError as attr_error:
                logging.info(f"AnthropicProviderHandler: ✗ API endpoint not available")
                logging.info(f"AnthropicProviderHandler: Error: {type(attr_error).__name__} - {str(attr_error)}")
                logging.info("AnthropicProviderHandler: Reason: Anthropic SDK doesn't expose models.list() method")
                logging.info("AnthropicProviderHandler: Action: Falling back to static list")
            except Exception as api_error:
                logging.warning(f"AnthropicProviderHandler: ✗ Exception during API call")
                logging.warning(f"AnthropicProviderHandler: Error type: {type(api_error).__name__}")
                logging.warning(f"AnthropicProviderHandler: Error message: {str(api_error)}")
                logging.warning("AnthropicProviderHandler: Action: Falling back to static list")
                if AISBF_DEBUG:
                    logging.warning(f"AnthropicProviderHandler: Full traceback:", exc_info=True)
            
            logging.info("-" * 80)
            logging.info("AnthropicProviderHandler: Using static fallback model list")
            logging.info("AnthropicProviderHandler: Note: This is the expected behavior for Anthropic provider")
            
            static_models = [
                Model(id="claude-3-7-sonnet-20250219", name="Claude 3.7 Sonnet", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-5-sonnet-20241022", name="Claude 3.5 Sonnet", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-opus-20240229", name="Claude 3 Opus", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-haiku-20240307", name="Claude 3 Haiku", provider_id=self.provider_id, context_size=200000, context_length=200000),
                Model(id="claude-3-sonnet-20240229", name="Claude 3 Sonnet", provider_id=self.provider_id, context_size=200000, context_length=200000),
            ]
            
            for model in static_models:
                logging.info(f"AnthropicProviderHandler:   - {model.id} ({model.name})")
            
            logging.info("=" * 80)
            logging.info(f"AnthropicProviderHandler: ✓ Returning {len(static_models)} models from static list")
            logging.info(f"AnthropicProviderHandler: Source: Static fallback configuration")
            logging.info("=" * 80)
            
            return static_models
        except Exception as e:
            import logging
            logging.error("=" * 80)
            logging.error(f"AnthropicProviderHandler: ✗ FATAL ERROR getting models: {str(e)}")
            logging.error("=" * 80)
            logging.error(f"AnthropicProviderHandler: Error details:", exc_info=True)
            raise e
