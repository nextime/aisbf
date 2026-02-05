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
from typing import Dict, List, Optional
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from .models import ChatCompletionRequest, ChatCompletionResponse
from .providers import get_provider_handler
from .config import config

class RequestHandler:
    def __init__(self):
        self.config = config

    async def handle_chat_completion(self, request: Request, provider_id: str, request_data: Dict) -> Dict:
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

        try:
            # Apply rate limiting
            await handler.apply_rate_limit()

            response = await handler.handle_request(
                model=request_data['model'],
                messages=request_data['messages'],
                max_tokens=request_data.get('max_tokens'),
                temperature=request_data.get('temperature', 1.0),
                stream=request_data.get('stream', False)
            )
            handler.record_success()
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
        rotation_config = self.config.get_rotation(rotation_id)
        if not rotation_config:
            raise HTTPException(status_code=400, detail=f"Rotation {rotation_id} not found")

        providers = rotation_config.providers
        weighted_models = []

        for provider in providers:
            for model in provider['models']:
                weighted_models.extend([model] * model['weight'])

        if not weighted_models:
            raise HTTPException(status_code=400, detail="No models available in rotation")

        import random
        selected_model = random.choice(weighted_models)

        provider_id = selected_model['provider_id']
        api_key = selected_model.get('api_key')
        model_name = selected_model['name']

        handler = get_provider_handler(provider_id, api_key)

        if handler.is_rate_limited():
            raise HTTPException(status_code=503, detail="All providers temporarily unavailable")

        try:
            # Apply rate limiting with model-specific rate limit if available
            rate_limit = selected_model.get('rate_limit')
            await handler.apply_rate_limit(rate_limit)

            response = await handler.handle_request(
                model=model_name,
                messages=request_data['messages'],
                max_tokens=request_data.get('max_tokens'),
                temperature=request_data.get('temperature', 1.0),
                stream=request_data.get('stream', False)
            )
            handler.record_success()
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
