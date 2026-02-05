"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

Main application for AISBF.

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

Main application for AISBF.
"""
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from aisbf.models import ChatCompletionRequest, ChatCompletionResponse
from aisbf.handlers import RequestHandler, RotationHandler
from aisbf.config import config
import time
import logging
from datetime import datetime, timedelta
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize handlers
request_handler = RequestHandler()
rotation_handler = RotationHandler()

app = FastAPI(title="AI Proxy Server")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "AI Proxy Server is running", "providers": list(config.providers.keys())}

@app.post("/api/{provider_id}/chat/completions")
async def chat_completions(provider_id: str, request: Request, body: ChatCompletionRequest):
    logger.debug(f"Received chat_completions request for provider: {provider_id}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    logger.debug(f"Request body: {body}")
    
    body_dict = body.model_dump()

    # Check if it's a rotation
    if provider_id in config.rotations:
        logger.debug("Handling rotation request")
        return await rotation_handler.handle_rotation_request(provider_id, body_dict)
    
    # Check if it's a provider
    if provider_id not in config.providers:
        logger.error(f"Provider {provider_id} not found")
        raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")

    provider_config = config.get_provider(provider_id)
    logger.debug(f"Provider config: {provider_config}")

    try:
        if body.stream:
            logger.debug("Handling streaming chat completion")
            return await request_handler.handle_streaming_chat_completion(request, provider_id, body_dict)
        else:
            logger.debug("Handling non-streaming chat completion")
            result = await request_handler.handle_chat_completion(request, provider_id, body_dict)
            logger.debug(f"Response result: {result}")
            return result
    except Exception as e:
        logger.error(f"Error handling chat_completions: {str(e)}", exc_info=True)
        raise

@app.get("/api/{provider_id}/models")
async def list_models(request: Request, provider_id: str):
    logger.debug(f"Received list_models request for provider: {provider_id}")
    
    # Check if it's a rotation
    if provider_id in config.rotations:
        logger.debug("Handling rotation model list request")
        return await rotation_handler.handle_rotation_model_list(provider_id)
    
    # Check if it's a provider
    if provider_id not in config.providers:
        logger.error(f"Provider {provider_id} not found")
        raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")

    provider_config = config.get_provider(provider_id)

    try:
        logger.debug("Handling model list request")
        result = await request_handler.handle_model_list(request, provider_id)
        logger.debug(f"Models result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error handling list_models: {str(e)}", exc_info=True)
        raise

def main():
    """Main entry point for the AISBF server"""
    import uvicorn
    logger.info("Starting AI Proxy Server on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
