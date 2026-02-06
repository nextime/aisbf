"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Request handlers for AISBF.

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

Request handlers for AISBF.
"""
import asyncio
import re
from typing import Dict, List, Optional
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from .models import ChatCompletionRequest, ChatCompletionResponse
from .providers import get_provider_handler
from .config import config

class RequestHandler:
    def __init__(self):
        self.config = config

    async def handle_chat_completion(self, request: Request, provider_id: str, request_data: Dict) -> Dict:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== RequestHandler.handle_chat_completion START ===")
        logger.info(f"Provider ID: {provider_id}")
        logger.info(f"Request data: {request_data}")
        
        provider_config = self.config.get_provider(provider_id)
        logger.info(f"Provider config: {provider_config}")
        logger.info(f"Provider type: {provider_config.type}")
        logger.info(f"Provider endpoint: {provider_config.endpoint}")
        logger.info(f"API key required: {provider_config.api_key_required}")

        if provider_config.api_key_required:
            api_key = request_data.get('api_key') or request.headers.get('Authorization', '').replace('Bearer ', '')
            logger.info(f"API key from request: {'***' if api_key else 'None'}")
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None
            logger.info("No API key required for this provider")

        logger.info(f"Getting provider handler for {provider_id}")
        handler = get_provider_handler(provider_id, api_key)
        logger.info(f"Provider handler obtained: {handler.__class__.__name__}")

        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="Provider temporarily unavailable")

        try:
            logger.info(f"Model requested: {request_data.get('model')}")
            logger.info(f"Messages count: {len(request_data.get('messages', []))}")
            logger.info(f"Max tokens: {request_data.get('max_tokens')}")
            logger.info(f"Temperature: {request_data.get('temperature', 1.0)}")
            logger.info(f"Stream: {request_data.get('stream', False)}")
            
            # Apply rate limiting
            logger.info("Applying rate limiting...")
            await handler.apply_rate_limit()
            logger.info("Rate limiting applied")

            logger.info(f"Sending request to provider handler...")
            response = await handler.handle_request(
                model=request_data['model'],
                messages=request_data['messages'],
                max_tokens=request_data.get('max_tokens'),
                temperature=request_data.get('temperature', 1.0),
                stream=request_data.get('stream', False)
            )
            logger.info(f"Response received from provider")
            handler.record_success()
            logger.info(f"=== RequestHandler.handle_chat_completion END ===")
            return response
        except Exception as e:
            handler.record_failure()
            raise HTTPException(status_code=500, detail=str(e))

    async def handle_streaming_chat_completion(self, request: Request, provider_id: str, request_data: Dict):
        provider_config = self.config.get_provider(provider_id)

        if provider_config.api_key_required:
            api_key = request_data.get('api_key') or request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None

        handler = get_provider_handler(provider_id, api_key)

        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="Provider temporarily unavailable")

        async def stream_generator():
            try:
                # Apply rate limiting
                await handler.apply_rate_limit()

                response = await handler.handle_request(
                    model=request_data['model'],
                    messages=request_data['messages'],
                    max_tokens=request_data.get('max_tokens'),
                    temperature=request_data.get('temperature', 1.0),
                    stream=True
                )
                for chunk in response:
                    yield f"data: {chunk}\n\n".encode('utf-8')
                handler.record_success()
            except Exception as e:
                handler.record_failure()
                yield f"data: {str(e)}\n\n".encode('utf-8')

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    async def handle_model_list(self, request: Request, provider_id: str) -> List[Dict]:
        provider_config = self.config.get_provider(provider_id)

        if provider_config.api_key_required:
            api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
            if not api_key:
                raise HTTPException(status_code=401, detail="API key required")
        else:
            api_key = None

        handler = get_provider_handler(provider_id, api_key)
        try:
            # Apply rate limiting
            await handler.apply_rate_limit()

            models = await handler.get_models()
            return [model.dict() for model in models]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

class RotationHandler:
    def __init__(self):
        self.config = config

    async def handle_rotation_request(self, rotation_id: str, request_data: Dict) -> Dict:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== RotationHandler.handle_rotation_request START ===")
        logger.info(f"Rotation ID: {rotation_id}")
        
        rotation_config = self.config.get_rotation(rotation_id)
        if not rotation_config:
            logger.error(f"Rotation {rotation_id} not found")
            raise HTTPException(status_code=400, detail=f"Rotation {rotation_id} not found")

        logger.info(f"Rotation config: {rotation_config}")
        providers = rotation_config.providers
        logger.info(f"Number of providers in rotation: {len(providers)}")
        
        weighted_models = []

        for provider in providers:
            logger.info(f"Processing provider: {provider['provider_id']}")
            for model in provider['models']:
                logger.info(f"  Model: {model['name']}, weight: {model['weight']}")
                weighted_models.extend([model] * model['weight'])

        logger.info(f"Total weighted models: {len(weighted_models)}")
        if not weighted_models:
            logger.error("No models available in rotation")
            raise HTTPException(status_code=400, detail="No models available in rotation")

        import random
        selected_model = random.choice(weighted_models)
        logger.info(f"Selected model: {selected_model}")

        provider_id = selected_model['provider_id']
        api_key = selected_model.get('api_key')
        model_name = selected_model['name']
        
        logger.info(f"Selected provider_id: {provider_id}")
        logger.info(f"Selected model_name: {model_name}")
        logger.info(f"API key present: {bool(api_key)}")

        logger.info(f"Getting provider handler for {provider_id}")
        handler = get_provider_handler(provider_id, api_key)
        logger.info(f"Provider handler obtained: {handler.__class__.__name__}")

        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="All providers temporarily unavailable")

        try:
            logger.info(f"Model requested: {model_name}")
            logger.info(f"Messages count: {len(request_data.get('messages', []))}")
            logger.info(f"Max tokens: {request_data.get('max_tokens')}")
            logger.info(f"Temperature: {request_data.get('temperature', 1.0)}")
            logger.info(f"Stream: {request_data.get('stream', False)}")
            
            # Apply rate limiting with model-specific rate limit if available
            rate_limit = selected_model.get('rate_limit')
            logger.info(f"Model-specific rate limit: {rate_limit}")
            logger.info("Applying rate limiting...")
            await handler.apply_rate_limit(rate_limit)
            logger.info("Rate limiting applied")

            logger.info(f"Sending request to provider handler...")
            response = await handler.handle_request(
                model=model_name,
                messages=request_data['messages'],
                max_tokens=request_data.get('max_tokens'),
                temperature=request_data.get('temperature', 1.0),
                stream=request_data.get('stream', False)
            )
            logger.info(f"Response received from provider")
            handler.record_success()
            logger.info(f"=== RotationHandler.handle_rotation_request END ===")
            return response
        except Exception as e:
            handler.record_failure()
            raise HTTPException(status_code=500, detail=str(e))

    async def handle_rotation_model_list(self, rotation_id: str) -> List[Dict]:
        rotation_config = self.config.get_rotation(rotation_id)
        if not rotation_config:
            raise HTTPException(status_code=400, detail=f"Rotation {rotation_id} not found")

        all_models = []
        for provider in rotation_config.providers:
            for model in provider['models']:
                all_models.append({
                    "id": f"{provider['provider_id']}/{model['name']}",
                    "name": model['name'],
                    "provider_id": provider['provider_id'],
                    "weight": model['weight'],
                    "rate_limit": model.get('rate_limit')
                })

        return all_models

class AutoselectHandler:
    def __init__(self):
        self.config = config
        self._skill_file_content = None

    def _get_skill_file_content(self) -> str:
        """Load the autoselect.md skill file content"""
        if self._skill_file_content is None:
            # Try installed locations first
            installed_dirs = [
                Path('/usr/share/aisbf'),
                Path.home() / '.local' / 'share' / 'aisbf',
            ]
            
            for installed_dir in installed_dirs:
                skill_file = installed_dir / 'autoselect.md'
                if skill_file.exists():
                    with open(skill_file) as f:
                        self._skill_file_content = f.read()
                    return self._skill_file_content
            
            # Fallback to source tree config directory
            source_dir = Path(__file__).parent.parent / 'config'
            skill_file = source_dir / 'autoselect.md'
            if skill_file.exists():
                with open(skill_file) as f:
                    self._skill_file_content = f.read()
                return self._skill_file_content
            
            raise FileNotFoundError("Could not find autoselect.md skill file")
        
        return self._skill_file_content

    def _build_autoselect_prompt(self, user_prompt: str, autoselect_config) -> str:
        """Build the prompt for model selection"""
        skill_content = self._get_skill_file_content()
        
        # Build the available models list
        models_list = ""
        for model_info in autoselect_config.available_models:
            models_list += f"<model><model_id>{model_info.model_id}</model_id><model_description>{model_info.description}</model_description></model>\n"
        
        # Build the complete prompt
        prompt = f"""{skill_content}

<aisbf_user_prompt>{user_prompt}</aisbf_user_prompt>
<aisbf_autoselect_list>
{models_list}
</aisbf_autoselect_list>
<aisbf_autoselect_fallback>{autoselect_config.fallback}</aisbf_autoselect_fallback>
"""
        return prompt

    def _extract_model_selection(self, response: str) -> Optional[str]:
        """Extract the model_id from the autoselection response"""
        match = re.search(r'<aisbf_model_autoselection>(.*?)</aisbf_model_autoselection>', response, re.DOTALL)
        if match:
            return match.group(1).strip()
        return None

    async def _get_model_selection(self, prompt: str) -> str:
        """Send the autoselect prompt to a model and get the selection"""
        # Use the first available provider/model for the selection
        # This is a simple implementation - could be enhanced to use a specific selection model
        rotation_handler = RotationHandler()
        
        # Create a minimal request for model selection
        selection_request = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,  # Low temperature for more deterministic selection
            "max_tokens": 100,   # We only need a short response
            "stream": False
        }
        
        # Use the fallback rotation for the selection
        try:
            response = await rotation_handler.handle_rotation_request("general", selection_request)
            content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
            model_id = self._extract_model_selection(content)
            return model_id
        except Exception as e:
            # If selection fails, we'll handle it in the main handler
            return None

    async def handle_autoselect_request(self, autoselect_id: str, request_data: Dict) -> Dict:
        """Handle an autoselect request"""
        autoselect_config = self.config.get_autoselect(autoselect_id)
        if not autoselect_config:
            raise HTTPException(status_code=400, detail=f"Autoselect {autoselect_id} not found")

        # Extract the user prompt from the request
        user_messages = request_data.get('messages', [])
        if not user_messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        # Build a string representation of the user prompt
        user_prompt = ""
        for msg in user_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                # Handle complex content (e.g., with images)
                content = str(content)
            user_prompt += f"{role}: {content}\n"

        # Build the autoselect prompt
        autoselect_prompt = self._build_autoselect_prompt(user_prompt, autoselect_config)

        # Get the model selection
        selected_model_id = await self._get_model_selection(autoselect_prompt)

        # Validate the selected model
        if not selected_model_id:
            # Fallback to the configured fallback model
            selected_model_id = autoselect_config.fallback
        else:
            # Check if the selected model is in the available models list
            available_ids = [m.model_id for m in autoselect_config.available_models]
            if selected_model_id not in available_ids:
                selected_model_id = autoselect_config.fallback

        # Now proxy the actual request to the selected rotation
        rotation_handler = RotationHandler()
        return await rotation_handler.handle_rotation_request(selected_model_id, request_data)

    async def handle_autoselect_streaming_request(self, autoselect_id: str, request_data: Dict):
        """Handle an autoselect streaming request"""
        autoselect_config = self.config.get_autoselect(autoselect_id)
        if not autoselect_config:
            raise HTTPException(status_code=400, detail=f"Autoselect {autoselect_id} not found")

        # Extract the user prompt from the request
        user_messages = request_data.get('messages', [])
        if not user_messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        # Build a string representation of the user prompt
        user_prompt = ""
        for msg in user_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                content = str(content)
            user_prompt += f"{role}: {content}\n"

        # Build the autoselect prompt
        autoselect_prompt = self._build_autoselect_prompt(user_prompt, autoselect_config)

        # Get the model selection
        selected_model_id = await self._get_model_selection(autoselect_prompt)

        # Validate the selected model
        if not selected_model_id:
            selected_model_id = autoselect_config.fallback
        else:
            available_ids = [m.model_id for m in autoselect_config.available_models]
            if selected_model_id not in available_ids:
                selected_model_id = autoselect_config.fallback

        # Now proxy the actual streaming request to the selected rotation
        rotation_handler = RotationHandler()
        
        async def stream_generator():
            try:
                response = await rotation_handler.handle_rotation_request(
                    selected_model_id,
                    {**request_data, "stream": True}
                )
                for chunk in response:
                    yield f"data: {chunk}\n\n".encode('utf-8')
            except Exception as e:
                yield f"data: {str(e)}\n\n".encode('utf-8')

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    async def handle_autoselect_model_list(self, autoselect_id: str) -> List[Dict]:
        """List available models for an autoselect endpoint"""
        autoselect_config = self.config.get_autoselect(autoselect_id)
        if not autoselect_config:
            raise HTTPException(status_code=400, detail=f"Autoselect {autoselect_id} not found")

        # Return the available models that can be selected
        return [
            {
                "id": model_info.model_id,
                "name": model_info.model_id,
                "description": model_info.description
            }
            for model_info in autoselect_config.available_models
        ]
