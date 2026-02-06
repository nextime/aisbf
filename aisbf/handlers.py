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
                    # Convert chunk to dict and serialize as JSON
                    chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
                    import json
                    yield f"data: {json.dumps(chunk_dict)}\n\n".encode('utf-8')
                handler.record_success()
            except Exception as e:
                handler.record_failure()
                import json
                error_dict = {"error": str(e)}
                yield f"data: {json.dumps(error_dict)}\n\n".encode('utf-8')

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

        logger.info(f"Rotation config loaded successfully")
        providers = rotation_config.providers
        logger.info(f"Number of providers in rotation: {len(providers)}")
        
        # Collect all available models with their weights
        available_models = []
        skipped_providers = []
        total_models_considered = 0

        logger.info(f"=== MODEL SELECTION PROCESS START ===")
        logger.info(f"Scanning providers for available models...")
        
        for provider in providers:
            provider_id = provider['provider_id']
            logger.info(f"")
            logger.info(f"--- Processing provider: {provider_id} ---")
            
            # Check if provider exists in configuration
            provider_config = self.config.get_provider(provider_id)
            if not provider_config:
                logger.error(f"  [ERROR] Provider {provider_id} not found in providers configuration")
                logger.error(f"  Available providers: {list(self.config.providers.keys())}")
                logger.error(f"  Skipping this provider")
                skipped_providers.append(provider_id)
                continue
            
            # Check if provider is rate limited/deactivated
            provider_handler = get_provider_handler(provider_id, provider.get('api_key'))
            if provider_handler.is_rate_limited():
                logger.warning(f"  [SKIPPED] Provider {provider_id} is rate limited/deactivated")
                logger.warning(f"  Reason: Provider has exceeded failure threshold or is in cooldown period")
                skipped_providers.append(provider_id)
                continue
            
            logger.info(f"  [AVAILABLE] Provider {provider_id} is active and ready")
            
            models_in_provider = len(provider['models'])
            total_models_considered += models_in_provider
            logger.info(f"  Found {models_in_provider} model(s) in this provider")
            
            for model in provider['models']:
                model_name = model['name']
                model_weight = model['weight']
                model_rate_limit = model.get('rate_limit', 'N/A')
                
                logger.info(f"    - Model: {model_name}")
                logger.info(f"      Weight (Priority): {model_weight}")
                logger.info(f"      Rate Limit: {model_rate_limit}")
                
                # Add provider_id and api_key to model for later use
                model_with_provider = model.copy()
                model_with_provider['provider_id'] = provider_id
                model_with_provider['api_key'] = provider.get('api_key')
                available_models.append(model_with_provider)

        logger.info(f"")
        logger.info(f"=== MODEL SELECTION SUMMARY ===")
        logger.info(f"Total providers scanned: {len(providers)}")
        logger.info(f"Providers skipped (rate limited): {len(skipped_providers)}")
        if skipped_providers:
            logger.info(f"Skipped providers: {', '.join(skipped_providers)}")
        logger.info(f"Total models considered: {total_models_considered}")
        logger.info(f"Total models available: {len(available_models)}")
        
        if not available_models:
            logger.error("No models available in rotation (all providers may be rate limited)")
            logger.error("All providers in this rotation are currently deactivated")
            raise HTTPException(status_code=503, detail="No models available in rotation (all providers may be rate limited)")

        # Sort models by weight in descending order (higher weight = higher priority)
        available_models.sort(key=lambda m: m['weight'], reverse=True)
        
        logger.info(f"")
        logger.info(f"=== PRIORITY-BASED SELECTION ===")
        logger.info(f"Models sorted by weight (descending priority):")
        for idx, model in enumerate(available_models, 1):
            logger.info(f"  {idx}. {model['name']} (provider: {model['provider_id']}, weight: {model['weight']})")

        # Find the highest weight
        highest_weight = available_models[0]['weight']
        logger.info(f"")
        logger.info(f"Highest priority weight: {highest_weight}")

        # Filter models with the highest weight
        highest_weight_models = [m for m in available_models if m['weight'] == highest_weight]
        logger.info(f"Models with highest priority ({highest_weight}): {len(highest_weight_models)}")
        for model in highest_weight_models:
            logger.info(f"  - {model['name']} (provider: {model['provider_id']})")

        # If multiple models have the same highest weight, randomly select among them
        import random
        if len(highest_weight_models) > 1:
            logger.info(f"Multiple models with same highest priority - performing random selection")
            selected_model = random.choice(highest_weight_models)
            logger.info(f"Randomly selected from {len(highest_weight_models)} candidates")
        else:
            selected_model = highest_weight_models[0]
            logger.info(f"Single model with highest priority - deterministic selection")
        
        logger.info(f"")
        logger.info(f"=== FINAL SELECTION ===")
        logger.info(f"Selected model: {selected_model['name']}")
        logger.info(f"Selected provider: {selected_model['provider_id']}")
        logger.info(f"Model weight (priority): {selected_model['weight']}")
        logger.info(f"Model rate limit: {selected_model.get('rate_limit', 'N/A')}")
        logger.info(f"=== MODEL SELECTION PROCESS END ===")

        # Retry logic: Try up to 2 times with different models
        max_retries = 2
        tried_models = []
        last_error = None
        successful_model = None
        
        for attempt in range(max_retries):
            logger.info(f"")
            logger.info(f"=== ATTEMPT {attempt + 1}/{max_retries} ===")
            
            # Select a model that hasn't been tried yet
            remaining_models = [m for m in available_models if m not in tried_models]
            
            if not remaining_models:
                logger.error(f"No more models available to try")
                logger.error(f"All {len(available_models)} models have been attempted")
                break
            
            # Sort remaining models by weight and select the best one
            remaining_models.sort(key=lambda m: m['weight'], reverse=True)
            current_model = remaining_models[0]
            tried_models.append(current_model)
            
            logger.info(f"Trying model: {current_model['name']} (provider: {current_model['provider_id']})")
            logger.info(f"Attempt {attempt + 1} of {max_retries}")
            
            provider_id = current_model['provider_id']
            api_key = current_model.get('api_key')
            model_name = current_model['name']
            
            logger.info(f"Getting provider handler for {provider_id}")
            handler = get_provider_handler(provider_id, api_key)
            logger.info(f"Provider handler obtained: {handler.__class__.__name__}")

            if handler.is_rate_limited():
                logger.warning(f"Provider {provider_id} is rate limited, skipping to next model")
                continue
            
            try:
                logger.info(f"Model requested: {model_name}")
                logger.info(f"Messages count: {len(request_data.get('messages', []))}")
                logger.info(f"Max tokens: {request_data.get('max_tokens')}")
                logger.info(f"Temperature: {request_data.get('temperature', 1.0)}")
                logger.info(f"Stream: {request_data.get('stream', False)}")
                
                # Apply rate limiting with model-specific rate limit if available
                rate_limit = current_model.get('rate_limit')
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
                
                # Update successful_model to the one that worked
                successful_model = current_model
                
                logger.info(f"=== RotationHandler.handle_rotation_request END ===")
                logger.info(f"Request succeeded on attempt {attempt + 1}")
                logger.info(f"Successfully used model: {successful_model['name']} (provider: {successful_model['provider_id']})")
                return response
            except Exception as e:
                last_error = str(e)
                handler.record_failure()
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
                logger.error(f"Error type: {type(e).__name__}")
                logger.error(f"Will try next model...")
                continue
        
        # All retries exhausted
        logger.error(f"")
        logger.error(f"=== ALL RETRIES EXHAUSTED ===")
        logger.error(f"Attempted {len(tried_models)} different model(s): {[m['name'] for m in tried_models]}")
        logger.error(f"Last error: {last_error}")
        logger.error(f"Max retries ({max_retries}) reached without success")
        raise HTTPException(
            status_code=503,
            detail=f"All providers in rotation failed after {max_retries} attempts. Last error: {last_error}"
        )

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
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== AUTOSELECT MODEL SELECTION START ===")
        logger.info(f"Using 'general' rotation for model selection")
        
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
        
        logger.info(f"Selection request parameters:")
        logger.info(f"  Temperature: 0.1 (low for deterministic selection)")
        logger.info(f"  Max tokens: 100 (short response expected)")
        logger.info(f"  Stream: False")
        
        # Use the fallback rotation for the selection
        try:
            logger.info(f"Sending selection request to rotation handler...")
            response = await rotation_handler.handle_rotation_request("general", selection_request)
            logger.info(f"Selection response received")
            
            content = response.get('choices', [{}])[0].get('message', {}).get('content', '')
            logger.info(f"Raw response content: {content[:200]}..." if len(content) > 200 else f"Raw response content: {content}")
            
            model_id = self._extract_model_selection(content)
            
            if model_id:
                logger.info(f"=== AUTOSELECT MODEL SELECTION SUCCESS ===")
                logger.info(f"Selected model ID: {model_id}")
            else:
                logger.warning(f"=== AUTOSELECT MODEL SELECTION FAILED ===")
                logger.warning(f"Could not extract model ID from response")
                logger.warning(f"Response content: {content}")
            
            return model_id
        except Exception as e:
            logger.error(f"=== AUTOSELECT MODEL SELECTION ERROR ===")
            logger.error(f"Error during model selection: {str(e)}")
            logger.error(f"Will use fallback model")
            # If selection fails, we'll handle it in the main handler
            return None

    async def handle_autoselect_request(self, autoselect_id: str, request_data: Dict) -> Dict:
        """Handle an autoselect request"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== AUTOSELECT REQUEST START ===")
        logger.info(f"Autoselect ID: {autoselect_id}")
        
        autoselect_config = self.config.get_autoselect(autoselect_id)
        if not autoselect_config:
            logger.error(f"Autoselect {autoselect_id} not found")
            raise HTTPException(status_code=400, detail=f"Autoselect {autoselect_id} not found")

        logger.info(f"Autoselect config loaded")
        logger.info(f"Available models for selection: {len(autoselect_config.available_models)}")
        for model_info in autoselect_config.available_models:
            logger.info(f"  - {model_info.model_id}: {model_info.description}")
        logger.info(f"Fallback model: {autoselect_config.fallback}")

        # Extract the user prompt from the request
        user_messages = request_data.get('messages', [])
        if not user_messages:
            logger.error("No messages provided")
            raise HTTPException(status_code=400, detail="No messages provided")
        
        logger.info(f"User messages count: {len(user_messages)}")
        
        # Build a string representation of the user prompt
        user_prompt = ""
        for msg in user_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                # Handle complex content (e.g., with images)
                content = str(content)
            user_prompt += f"{role}: {content}\n"

        logger.info(f"User prompt length: {len(user_prompt)} characters")
        logger.info(f"User prompt preview: {user_prompt[:200]}..." if len(user_prompt) > 200 else f"User prompt: {user_prompt}")

        # Build the autoselect prompt
        logger.info(f"Building autoselect prompt...")
        autoselect_prompt = self._build_autoselect_prompt(user_prompt, autoselect_config)
        logger.info(f"Autoselect prompt built (length: {len(autoselect_prompt)} characters)")

        # Get the model selection
        logger.info(f"Requesting model selection from AI...")
        selected_model_id = await self._get_model_selection(autoselect_prompt)

        # Validate the selected model
        logger.info(f"=== MODEL VALIDATION ===")
        if not selected_model_id:
            # Fallback to the configured fallback model
            logger.warning(f"No model ID returned from selection")
            logger.warning(f"Using fallback model: {autoselect_config.fallback}")
            selected_model_id = autoselect_config.fallback
        else:
            # Check if the selected model is in the available models list
            available_ids = [m.model_id for m in autoselect_config.available_models]
            if selected_model_id not in available_ids:
                logger.warning(f"Selected model '{selected_model_id}' not in available models list")
                logger.warning(f"Available models: {available_ids}")
                logger.warning(f"Using fallback model: {autoselect_config.fallback}")
                selected_model_id = autoselect_config.fallback
            else:
                logger.info(f"Selected model '{selected_model_id}' is valid and available")

        logger.info(f"=== FINAL MODEL CHOICE ===")
        logger.info(f"Selected model ID: {selected_model_id}")
        logger.info(f"Selection method: {'AI-selected' if selected_model_id != autoselect_config.fallback else 'Fallback'}")

        # Now proxy the actual request to the selected rotation
        logger.info(f"Proxying request to rotation: {selected_model_id}")
        rotation_handler = RotationHandler()
        response = await rotation_handler.handle_rotation_request(selected_model_id, request_data)
        logger.info(f"=== AUTOSELECT REQUEST END ===")
        return response

    async def handle_autoselect_streaming_request(self, autoselect_id: str, request_data: Dict):
        """Handle an autoselect streaming request"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"=== AUTOSELECT STREAMING REQUEST START ===")
        logger.info(f"Autoselect ID: {autoselect_id}")
        
        autoselect_config = self.config.get_autoselect(autoselect_id)
        if not autoselect_config:
            logger.error(f"Autoselect {autoselect_id} not found")
            raise HTTPException(status_code=400, detail=f"Autoselect {autoselect_id} not found")

        logger.info(f"Autoselect config loaded")
        logger.info(f"Available models for selection: {len(autoselect_config.available_models)}")
        for model_info in autoselect_config.available_models:
            logger.info(f"  - {model_info.model_id}: {model_info.description}")
        logger.info(f"Fallback model: {autoselect_config.fallback}")

        # Extract the user prompt from the request
        user_messages = request_data.get('messages', [])
        if not user_messages:
            logger.error("No messages provided")
            raise HTTPException(status_code=400, detail="No messages provided")
        
        logger.info(f"User messages count: {len(user_messages)}")
        
        # Build a string representation of the user prompt
        user_prompt = ""
        for msg in user_messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                content = str(content)
            user_prompt += f"{role}: {content}\n"

        logger.info(f"User prompt length: {len(user_prompt)} characters")
        logger.info(f"User prompt preview: {user_prompt[:200]}..." if len(user_prompt) > 200 else f"User prompt: {user_prompt}")

        # Build the autoselect prompt
        logger.info(f"Building autoselect prompt...")
        autoselect_prompt = self._build_autoselect_prompt(user_prompt, autoselect_config)
        logger.info(f"Autoselect prompt built (length: {len(autoselect_prompt)} characters)")

        # Get the model selection
        logger.info(f"Requesting model selection from AI...")
        selected_model_id = await self._get_model_selection(autoselect_prompt)

        # Validate the selected model
        logger.info(f"=== MODEL VALIDATION ===")
        if not selected_model_id:
            logger.warning(f"No model ID returned from selection")
            logger.warning(f"Using fallback model: {autoselect_config.fallback}")
            selected_model_id = autoselect_config.fallback
        else:
            available_ids = [m.model_id for m in autoselect_config.available_models]
            if selected_model_id not in available_ids:
                logger.warning(f"Selected model '{selected_model_id}' not in available models list")
                logger.warning(f"Available models: {available_ids}")
                logger.warning(f"Using fallback model: {autoselect_config.fallback}")
                selected_model_id = autoselect_config.fallback
            else:
                logger.info(f"Selected model '{selected_model_id}' is valid and available")

        logger.info(f"=== FINAL MODEL CHOICE ===")
        logger.info(f"Selected model ID: {selected_model_id}")
        logger.info(f"Selection method: {'AI-selected' if selected_model_id != autoselect_config.fallback else 'Fallback'}")
        logger.info(f"Request mode: Streaming")

        # Now proxy the actual streaming request to the selected rotation
        logger.info(f"Proxying streaming request to rotation: {selected_model_id}")
        rotation_handler = RotationHandler()
        
        async def stream_generator():
            try:
                response = await rotation_handler.handle_rotation_request(
                    selected_model_id,
                    {**request_data, "stream": True}
                )
                for chunk in response:
                    # Convert chunk to dict and serialize as JSON
                    chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
                    import json
                    yield f"data: {json.dumps(chunk_dict)}\n\n".encode('utf-8')
            except Exception as e:
                logger.error(f"Error in streaming response: {str(e)}")
                import json
                error_dict = {"error": str(e)}
                yield f"data: {json.dumps(error_dict)}\n\n".encode('utf-8')

        logger.info(f"=== AUTOSELECT STREAMING REQUEST END ===")
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
