"""
Copyright (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Google (Gemini) provider handler.

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
from google import genai
from ..models import Model
from ..config import config
from ..utils import count_messages_tokens
from .base import BaseProviderHandler, AISBF_DEBUG


class GoogleProviderHandler(BaseProviderHandler):
    def __init__(self, provider_id: str, api_key: str):
        super().__init__(provider_id, api_key)
        # Initialize google-genai library
        from google import genai
        self.client = genai.Client(api_key=api_key)
        # Cache storage for Google Context Caching
        self._cached_content_refs = {}  # {cache_key: (cached_content_name, expiry_time)}

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

            # Check if native caching is enabled for this provider
            provider_config = config.providers.get(self.provider_id)
            enable_native_caching = getattr(provider_config, 'enable_native_caching', False)
            cache_ttl = getattr(provider_config, 'cache_ttl', None)
            min_cacheable_tokens = getattr(provider_config, 'min_cacheable_tokens', 1000)

            logging.info(f"GoogleProviderHandler: Native caching enabled: {enable_native_caching}")
            
            # Initialize cached_content_name for this request (will be set if we use caching)
            cached_content_name = None
            
            if enable_native_caching:
                logging.info(f"GoogleProviderHandler: Cache TTL: {cache_ttl} seconds, min_cacheable_tokens: {min_cacheable_tokens}")
                
                # Calculate total token count to determine if caching is beneficial
                total_tokens = count_messages_tokens(messages, model)
                logging.info(f"GoogleProviderHandler: Total message tokens: {total_tokens}")
                
                # Only use caching if total tokens exceed minimum threshold
                if total_tokens >= min_cacheable_tokens:
                    # Generate a cache key based on system message and early conversation
                    cache_key = self._generate_cache_key(messages, model)
                    
                    logging.info(f"GoogleProviderHandler: Generated cache_key: {cache_key}")
                    
                    # Check if we have a valid cached content
                    if cache_key in self._cached_content_refs:
                        cached_content_name, expiry_time = self._cached_content_refs[cache_key]
                        current_time = time.time()
                        
                        if current_time < expiry_time:
                            logging.info(f"GoogleProviderHandler: Using cached content: {cached_content_name} (expires in {expiry_time - current_time:.0f}s)")
                        else:
                            # Cache expired, remove it
                            logging.info(f"GoogleProviderHandler: Cache expired, removing: {cached_content_name}")
                            del self._cached_content_refs[cache_key]
                            cached_content_name = None
                    else:
                        logging.info(f"GoogleProviderHandler: No cached content found for cache_key")
                    
                    # If no cached content, and we have a TTL, mark to create cache after first request
                    if cached_content_name is None and cache_ttl:
                        self._pending_cache_key = (cache_key, cache_ttl, messages)
                        logging.info(f"GoogleProviderHandler: Will create cached content after first request")
                    else:
                        self._pending_cache_key = None
                else:
                    logging.info(f"GoogleProviderHandler: Total tokens ({total_tokens}) below min_cacheable_tokens ({min_cacheable_tokens}), skipping cache")
                    self._pending_cache_key = None
            else:
                self._pending_cache_key = None

            # Build content from messages
            content = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

            # Build config with only non-None values
            config_params = {"temperature": temperature}
            if max_tokens is not None:
                config_params["max_output_tokens"] = max_tokens

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
                    from google.genai import types as genai_types
                    google_tools = genai_types.Tool(function_declarations=function_declarations)
                    logging.info(f"GoogleProviderHandler: Added {len(function_declarations)} tools to google_tools")
                    
                    config_params["tools"] = google_tools
                    logging.info(f"GoogleProviderHandler: Added tools to config")

            # Handle streaming request
            if stream:
                logging.info(f"GoogleProviderHandler: Using streaming API")
                
                from google import genai
                stream_client = genai.Client(api_key=self.api_key)
                
                chunks = []
                
                for chunk in stream_client.models.generate_content_stream(
                    model=model,
                    contents=content,
                    config=config_params
                ):
                    chunks.append(chunk)
                
                logging.info(f"GoogleProviderHandler: Streaming response received (total chunks: {len(chunks)})")
                self.record_success()
                
                # After successful streaming response, create cached content if pending
                if hasattr(self, '_pending_cache_key') and self._pending_cache_key:
                    cache_key, cache_ttl, cache_messages = self._pending_cache_key
                    try:
                        new_cached_name = self._create_cached_content(cache_messages, model, cache_ttl)
                        if new_cached_name:
                            expiry_time = time.time() + cache_ttl
                            self._cached_content_refs[cache_key] = (new_cached_name, expiry_time)
                            logging.info(f"GoogleProviderHandler: Cached content stored (streaming): {new_cached_name}, expires in {cache_ttl}s")
                    except Exception as e:
                        logging.warning(f"GoogleProviderHandler: Failed to create cache after streaming: {e}")
                    self._pending_cache_key = None
                
                async def async_generator():
                    for chunk in chunks:
                        yield chunk
                
                return async_generator()
            else:
                # Non-streaming request
                use_cached = cached_content_name is not None
                
                if use_cached and cached_content_name:
                    last_msg_count = min(3, len(messages))
                    last_messages = messages[-last_msg_count:] if messages else []
                    content = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in last_messages])
                    logging.info(f"GoogleProviderHandler: Using cached content, sending last {last_msg_count} messages")
                else:
                    content = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in messages])

                config_params = {"temperature": temperature}
                if max_tokens is not None:
                    config_params["max_output_tokens"] = max_tokens

                google_tools = None
                if tools:
                    function_declarations = []
                    for tool in tools:
                        if tool.get("type") == "function":
                            function = tool.get("function", {})
                            from google.genai import types as genai_types
                            function_declaration = genai_types.FunctionDeclaration(
                                name=function.get("name"),
                                description=function.get("description", ""),
                                parameters=function.get("parameters", {})
                            )
                            function_declarations.append(function_declaration)
                            logging.info(f"GoogleProviderHandler: Converted tool to Google format: {function_declaration}")
                    
                    if function_declarations:
                        from google.genai import types as genai_types
                        google_tools = genai_types.Tool(function_declarations=function_declarations)
                        logging.info(f"GoogleProviderHandler: Added {len(function_declarations)} tools to google_tools")
                        
                        config_params["tools"] = google_tools
                        logging.info(f"GoogleProviderHandler: Added tools to config")

                if use_cached and cached_content_name:
                    try:
                        logging.info(f"GoogleProviderHandler: Making request with cached_content: {cached_content_name}")
                        response = self.client.models.generate_content(
                            model=model,
                            contents=content,
                            config=config_params,
                            cached_content=cached_content_name
                        )
                    except TypeError as e:
                        logging.warning(f"GoogleProviderHandler: cached_content param not supported, using regular request: {e}")
                        response = self.client.models.generate_content(
                            model=model,
                            contents=content,
                            config=config_params
                        )
                else:
                    response = self.client.models.generate_content(
                        model=model,
                        contents=content,
                        config=config_params
                    )

                logging.info(f"GoogleProviderHandler: Response received: {response}")
                self.record_success()
                
                # After successful response, create cached content if pending
                if hasattr(self, '_pending_cache_key') and self._pending_cache_key:
                    cache_key, cache_ttl, cache_messages = self._pending_cache_key
                    try:
                        new_cached_name = self._create_cached_content(cache_messages, model, cache_ttl)
                        if new_cached_name:
                            expiry_time = time.time() + cache_ttl
                            self._cached_content_refs[cache_key] = (new_cached_name, expiry_time)
                            logging.info(f"GoogleProviderHandler: Cached content stored: {new_cached_name}, expires in {cache_ttl}s")
                    except Exception as e:
                        logging.warning(f"GoogleProviderHandler: Failed to create cache after response: {e}")
                    self._pending_cache_key = None

                if AISBF_DEBUG:
                    logging.info(f"=== RAW GOOGLE RESPONSE ===")
                    logging.info(f"Raw response type: {type(response)}")
                    logging.info(f"Raw response: {response}")
                    logging.info(f"Raw response dir: {dir(response)}")
                    logging.info(f"=== END RAW GOOGLE RESPONSE ===")

                response_text = ""
                tool_calls = None
                finish_reason = "stop"
            
                logging.info(f"=== GOOGLE RESPONSE PARSING START ===")
                logging.info(f"Response type: {type(response)}")
                logging.info(f"Response attributes: {dir(response)}")
                
                try:
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
                            
                            if hasattr(candidate, 'finish_reason'):
                                logging.info(f"Candidate has 'finish_reason' attribute")
                                logging.info(f"Finish reason: {candidate.finish_reason}")
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
                                            
                                            text_parts = []
                                            openai_tool_calls = []
                                            call_id = 0
                                            
                                            for idx, part in enumerate(candidate.content.parts):
                                                logging.info(f"Processing part {idx}")
                                                logging.info(f"Part type: {type(part)}")
                                                logging.info(f"Part attributes: {dir(part)}")
                                                
                                                if hasattr(part, 'text') and part.text:
                                                    logging.info(f"Part {idx} has 'text' attribute")
                                                    text_parts.append(part.text)
                                                    logging.info(f"Part {idx} text length: {len(part.text)}")
                                                
                                                if hasattr(part, 'function_call') and part.function_call:
                                                    logging.info(f"Part {idx} has 'function_call' attribute")
                                                    logging.info(f"Function call: {part.function_call}")
                                                    
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
                                                
                                                if hasattr(part, 'function_response') and part.function_response:
                                                    logging.info(f"Part {idx} has 'function_response' attribute")
                                                    logging.info(f"Function response: {part.function_response}")
                                            
                                            response_text = "\n".join(text_parts)
                                            logging.info(f"Combined text length: {len(response_text)}")
                                            logging.info(f"Combined text (first 200 chars): {response_text[:200] if response_text else 'None'}")
                                            
                                            if response_text and not openai_tool_calls:
                                                import json
                                                import re

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

                                                        params = {}

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

                                                        offset_match = re.search(r'(?:offset|start|line\s*#?)\s*[:=]?\s*(\d+)', response_text, re.IGNORECASE)
                                                        if offset_match:
                                                            params['offset'] = int(offset_match.group(1))

                                                        limit_match = re.search(r'(?:limit|lines?|count)\s*[:=]?\s*(\d+)', response_text, re.IGNORECASE)
                                                        if limit_match:
                                                            params['limit'] = int(limit_match.group(1))

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
                                                        break
                                            if response_text and not openai_tool_calls:
                                                import json
                                                import re
                                                
                                                outer_assistant_pattern = r"^assistant:\s*(\[.*\])\s*$"
                                                outer_assistant_match = re.match(outer_assistant_pattern, response_text.strip(), re.DOTALL)
                                                
                                                if outer_assistant_match:
                                                    try:
                                                        outer_content = json.loads(outer_assistant_match.group(1))
                                                        if isinstance(outer_content, list) and len(outer_content) > 0:
                                                            for item in outer_content:
                                                                if isinstance(item, dict) and item.get('type') == 'text':
                                                                    inner_text = item.get('text', '')
                                                                    inner_tool_pattern = r'tool:\s*(\{.*?\})\s*(?:assistant:\s*(\[.*\]))?\s*$'
                                                                    inner_tool_match = re.search(inner_tool_pattern, inner_text, re.DOTALL)
                                                                    
                                                                    if inner_tool_match:
                                                                        tool_json_str = inner_tool_match.group(1)
                                                                        try:
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
                                                
                                                elif not openai_tool_calls:
                                                    tool_pattern = r'tool:\s*(\{[^}]*\})'
                                                    tool_match = re.search(tool_pattern, response_text, re.DOTALL)
                                                    try:
                                                        tool_json_str = tool_match.group(1)
                                                        parsed_json = json.loads(tool_json_str)
                                                        logging.info(f"Detected 'tool:' format in text content: {parsed_json}")
                                                        
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
                                                        
                                                        assistant_pattern = r"assistant:\s*(\[.*\])"
                                                        assistant_match = re.search(assistant_pattern, response_text, re.DOTALL)
                                                        if assistant_match:
                                                            try:
                                                                assistant_content = json.loads(assistant_match.group(1))
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
                                                            response_text = ""
                                                    except (json.JSONDecodeError, Exception) as e:
                                                        logging.debug(f"Failed to parse 'tool:' format: {e}")
                                                
                                                elif content_assistant_match:
                                                    try:
                                                        tool_content = content_assistant_match.group(1)
                                                        assistant_json_str = content_assistant_match.group(2)
                                                        
                                                        logging.info(f"Detected 'content/assistant:' format - tool content length: {len(tool_content)}")
                                                        
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
                                                
                                                elif not openai_tool_calls:
                                                    try:
                                                        parsed_json = json.loads(response_text.strip())
                                                        if isinstance(parsed_json, dict):
                                                            if 'action' in parsed_json or 'function' in parsed_json or 'name' in parsed_json:
                                                                if 'action' in parsed_json:
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
                                                                    response_text = ""
                                                                elif 'function' in parsed_json or 'name' in parsed_json:
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
                                                                    response_text = ""
                                                    except (json.JSONDecodeError, Exception) as e:
                                                        logging.debug(f"Response text is not valid JSON: {e}")
                                            
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
                
                if tool_calls:
                    openai_response["choices"][0]["message"]["tool_calls"] = tool_calls
                    openai_response["choices"][0]["message"]["content"] = None
                    logging.info(f"Added tool_calls to response message")
                
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
                
                logging.info(f"GoogleProviderHandler: Returning response dict (no validation)")
                logging.info(f"Response dict keys: {openai_response.keys()}")
                
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

            await self.apply_rate_limit()

            models = self.client.models.list()
            if AISBF_DEBUG:
                response_str = str(models)
                if len(response_str) > 1024:
                    response_str = response_str[:1024] + f" ... [TRUNCATED, total length: {len(response_str)} chars]"
                logging.info(f"GoogleProviderHandler: Models received: {response_str}")
            else:
                model_count = len(models) if isinstance(models, (list, dict)) else 'N/A'
                logging.info(f"GoogleProviderHandler: Models received: {model_count} models")

            result = []
            for model in models:
                context_size = None
                if hasattr(model, 'context_window') and model.context_window:
                    context_size = model.context_window
                elif hasattr(model, 'context_length') and model.context_length:
                    context_size = model.context_length
                elif hasattr(model, 'max_context_length') and model.max_context_length:
                    context_size = model.max_context_length
                
                result.append(Model(
                    id=model.name,
                    name=model.display_name or model.name,
                    provider_id=self.provider_id,
                    context_size=context_size,
                    context_length=context_size
                ))

            return result
        except Exception as e:
            import logging
            logging.error(f"GoogleProviderHandler: Error getting models: {str(e)}", exc_info=True)
            raise e

    def _generate_cache_key(self, messages: List[Dict], model: str) -> str:
        """Generate a cache key based on the early messages."""
        import hashlib
        import json
        
        cacheable_messages = []
        
        for i, msg in enumerate(messages):
            if msg.get('role') == 'system' or i < max(0, len(messages) - 3):
                cacheable_messages.append({
                    'role': msg.get('role'),
                    'content': msg.get('content', '')[:1000]
                })
        
        cache_data = json.dumps({
            'model': model,
            'messages': cacheable_messages
        }, sort_keys=True)
        
        return hashlib.sha256(cache_data.encode()).hexdigest()[:32]
    
    def _create_cached_content(self, messages: List[Dict], model: str, cache_ttl: int) -> Optional[str]:
        """Create a cached content object in Google API."""
        import logging
        
        try:
            cacheable_parts = []
            
            for i, msg in enumerate(messages):
                if msg.get('role') == 'system' or i < max(0, len(messages) - 3):
                    role = msg.get('role', 'user')
                    content = msg.get('content', '')
                    cacheable_parts.append(f"{role}: {content}")
            
            if not cacheable_parts:
                logging.info("GoogleProviderHandler: No cacheable content to create")
                return None
            
            cached_content_text = "\n\n".join(cacheable_parts)
            
            cache_name = f"cached_content_{int(time.time())}"
            
            logging.info(f"GoogleProviderHandler: Creating cached content: {cache_name}")
            logging.info(f"GoogleProviderHandler: Cached content length: {len(cached_content_text)} chars")
            
            from google.genai import types as genai_types
            
            try:
                cached_content = self.client.cached_contents.create(
                    model=model,
                    display_name=cache_name,
                    system_instruction=cached_content_text,
                    ttl=f"{cache_ttl}s"
                )
                
                logging.info(f"GoogleProviderHandler: Cached content created: {cached_content.name}")
                return cached_content.name
                
            except AttributeError as e:
                logging.info(f"GoogleProviderHandler: Cached content API not available in this SDK: {e}")
                return None
            except Exception as e:
                logging.warning(f"GoogleProviderHandler: Failed to create cached content: {e}")
                return None
                
        except Exception as e:
            logging.error(f"GoogleProviderHandler: Error creating cached content: {e}")
            return None
    
    def _use_cached_content_in_request(self, cached_content_name: str, model: str, 
                                         last_messages: List[Dict], max_tokens: Optional[int],
                                         temperature: float, tools: Optional[List[Dict]]) -> Union[Dict, object]:
        """Make a request using cached content."""
        import logging
        from google.genai import types as genai_types
        
        logging.info(f"GoogleProviderHandler: Using cached content: {cached_content_name}")
        
        content = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in last_messages])
        
        config_params = {"temperature": temperature}
        if max_tokens is not None:
            config_params["max_output_tokens"] = max_tokens
        if tools:
            function_declarations = []
            for tool in tools:
                if tool.get("type") == "function":
                    function = tool.get("function", {})
                    function_declaration = genai_types.FunctionDeclaration(
                        name=function.get("name"),
                        description=function.get("description", ""),
                        parameters=function.get("parameters", {})
                    )
                    function_declarations.append(function_declaration)
            
            if function_declarations:
                google_tools = genai_types.Tool(function_declarations=function_declarations)
                config_params["tools"] = google_tools
        
        response = self.client.models.generate_content(
            model=model,
            contents=content,
            config=config_params,
            cached_content=cached_content_name
        )
        
        return response
