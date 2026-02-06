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
from aisbf.handlers import RequestHandler, RotationHandler, AutoselectHandler
from aisbf.config import config
import time
import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

def setup_logging():
    """Setup logging with rotating file handlers"""
    # Determine log directory based on user
    if os.geteuid() == 0:
        # Running as root - use /var/log/aisbf
        log_dir = Path('/var/log/aisbf')
    else:
        # Running as user - use ~/.local/var/log/aisbf
        log_dir = Path.home() / '.local' / 'var' / 'log' / 'aisbf'
    
    # Create log directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup rotating file handler for general logs
    log_file = log_dir / 'aisbf.log'
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=50*1024*1024,  # 50 MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    
    # Setup rotating file handler for error logs
    error_log_file = log_dir / 'aisbf_error.log'
    error_handler = RotatingFileHandler(
        error_log_file,
        maxBytes=50*1024*1024,  # 50 MB
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    
    # Setup console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)
    
    # Redirect stderr to error log
    sys.stderr = open(log_dir / 'aisbf_stderr.log', 'a')
    
    return logging.getLogger(__name__)

# Configure logging
logger = setup_logging()

# Initialize handlers
request_handler = RequestHandler()
rotation_handler = RotationHandler()
autoselect_handler = AutoselectHandler()

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
    logger.info(f"=== CHAT COMPLETION REQUEST START ===")
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Provider ID: {provider_id}")
    logger.info(f"Request headers: {dict(request.headers)}")
    logger.info(f"Request body: {body}")
    logger.info(f"Available providers: {list(config.providers.keys())}")
    logger.info(f"Available rotations: {list(config.rotations.keys())}")
    logger.info(f"Available autoselect: {list(config.autoselect.keys())}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    logger.debug(f"Request body: {body}")

    body_dict = body.model_dump()

    # Check if it's an autoselect
    if provider_id in config.autoselect:
        logger.debug("Handling autoselect request")
        try:
            if body.stream:
                logger.debug("Handling streaming autoselect request")
                return await autoselect_handler.handle_autoselect_streaming_request(provider_id, body_dict)
            else:
                logger.debug("Handling non-streaming autoselect request")
                result = await autoselect_handler.handle_autoselect_request(provider_id, body_dict)
                logger.debug(f"Autoselect response result: {result}")
                return result
        except Exception as e:
            logger.error(f"Error handling autoselect: {str(e)}", exc_info=True)
            raise

    # Check if it's a rotation
    if provider_id in config.rotations:
        logger.info(f"Provider ID '{provider_id}' found in rotations")
        logger.debug("Handling rotation request")
        return await rotation_handler.handle_rotation_request(provider_id, body_dict)

    # Check if it's a provider
    if provider_id not in config.providers:
        logger.error(f"Provider ID '{provider_id}' not found in providers")
        logger.error(f"Available providers: {list(config.providers.keys())}")
        logger.error(f"Available rotations: {list(config.rotations.keys())}")
        logger.error(f"Available autoselect: {list(config.autoselect.keys())}")
        raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")
    
    logger.info(f"Provider ID '{provider_id}' found in providers")

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

    # Check if it's an autoselect
    if provider_id in config.autoselect:
        logger.debug("Handling autoselect model list request")
        try:
            result = await autoselect_handler.handle_autoselect_model_list(provider_id)
            logger.debug(f"Autoselect models result: {result}")
            return result
        except Exception as e:
            logger.error(f"Error handling autoselect model list: {str(e)}", exc_info=True)
            raise

    # Check if it's a rotation
    if provider_id in config.rotations:
        logger.info(f"Provider ID '{provider_id}' found in rotations")
        logger.debug("Handling rotation model list request")
        return await rotation_handler.handle_rotation_model_list(provider_id)

    # Check if it's a provider
    if provider_id not in config.providers:
        logger.error(f"Provider ID '{provider_id}' not found in providers")
        logger.error(f"Available providers: {list(config.providers.keys())}")
        logger.error(f"Available rotations: {list(config.rotations.keys())}")
        logger.error(f"Available autoselect: {list(config.autoselect.keys())}")
        raise HTTPException(status_code=400, detail=f"Provider {provider_id} not found")
    
    logger.info(f"Provider ID '{provider_id}' found in providers")

    provider_config = config.get_provider(provider_id)

    try:
        logger.debug("Handling model list request")
        result = await request_handler.handle_model_list(request, provider_id)
        logger.debug(f"Models result: {result}")
        return result
    except Exception as e:
        logger.error(f"Error handling list_models: {str(e)}", exc_info=True)
        raise

@app.post("/api/{provider_id}")
async def catch_all_post(provider_id: str, request: Request):
    """Catch-all for POST requests to help debug routing issues"""
    logger.info(f"=== CATCH-ALL POST REQUEST ===")
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Provider ID: {provider_id}")
    logger.info(f"Request headers: {dict(request.headers)}")
    logger.info(f"Available providers: {list(config.providers.keys())}")
    logger.info(f"Available rotations: {list(config.rotations.keys())}")
    logger.info(f"Available autoselect: {list(config.autoselect.keys())}")
    
    error_msg = f"""
    Invalid endpoint: {request.url.path}
    
    The correct endpoint format is: /api/{{provider_id}}/chat/completions
    
    Available providers: {list(config.providers.keys())}
    Available rotations: {list(config.rotations.keys())}
    Available autoselect: {list(config.autoselect.keys())}
    
    Example: POST /api/ollama/chat/completions
    """
    logger.error(error_msg)
    raise HTTPException(status_code=404, detail=error_msg.strip())

def main():
    """Main entry point for the AISBF server"""
    import uvicorn
    logger.info("Starting AI Proxy Server on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
