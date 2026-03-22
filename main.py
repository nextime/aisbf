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
from fastapi.exceptions import RequestValidationError
from aisbf.models import ChatCompletionRequest, ChatCompletionResponse
from aisbf.handlers import RequestHandler, RotationHandler, AutoselectHandler
from aisbf.config import config
from aisbf.database import initialize_database
import time
import logging
import sys
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path
import json

def load_server_config():
    """Load server configuration from aisbf.json"""
    # Try user config first
    config_path = Path.home() / '.aisbf' / 'aisbf.json'
    
    if not config_path.exists():
        # Try installed locations
        installed_dirs = [
            Path('/usr/share/aisbf'),
            Path.home() / '.local' / 'share' / 'aisbf',
        ]
        
        for installed_dir in installed_dirs:
            test_path = installed_dir / 'aisbf.json'
            if test_path.exists():
                config_path = test_path
                break
        else:
            # Fallback to source tree config directory
            source_dir = Path(__file__).parent / 'config'
            test_path = source_dir / 'aisbf.json'
            if test_path.exists():
                config_path = test_path
    
    # Load config or use defaults
    if config_path.exists():
        try:
            with open(config_path) as f:
                config_data = json.load(f)
                server_config = config_data.get('server', {})
                return {
                    'host': server_config.get('host', '0.0.0.0'),
                    'port': server_config.get('port', 8000)
                }
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Error loading aisbf.json: {e}, using defaults")
    
    # Return defaults
    return {
        'host': '0.0.0.0',
        'port': 8000
    }

class BrokenPipeFilter(logging.Filter):
    """Filter to suppress BrokenPipeError logging errors"""
    def filter(self, record):
        # Filter out BrokenPipeError and related logging errors
        if record.getMessage().startswith('--- Logging error ---'):
            return False
        if 'BrokenPipeError' in record.getMessage():
            return False
        return True

class SafeStderr:
    """Safe stderr wrapper that handles BrokenPipeError gracefully"""
    def __init__(self, original_stderr, log_file_path):
        self.original_stderr = original_stderr
        self.log_file = None
        try:
            self.log_file = open(log_file_path, 'a')
        except Exception:
            pass
    
    def write(self, data):
        # Filter out BrokenPipeError and related logging errors
        if '--- Logging error ---' in data or 'BrokenPipeError' in data:
            return
        if self.log_file:
            try:
                self.log_file.write(data)
                self.log_file.flush()
            except (BrokenPipeError, OSError):
                pass
        else:
            try:
                self.original_stderr.write(data)
            except (BrokenPipeError, OSError):
                pass
    
    def flush(self):
        if self.log_file:
            try:
                self.log_file.flush()
            except (BrokenPipeError, OSError):
                pass
        else:
            try:
                self.original_stderr.flush()
            except (BrokenPipeError, OSError):
                pass

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
    
    # Check if debug mode is enabled
    AISBF_DEBUG = os.environ.get('AISBF_DEBUG', '').lower() in ('true', '1', 'yes')
    
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
    
    # Setup console handler - use DEBUG level if AISBF_DEBUG is enabled
    console_handler = logging.StreamHandler(sys.stdout)
    if AISBF_DEBUG:
        console_handler.setLevel(logging.DEBUG)
        print("=== AISBF DEBUG MODE ENABLED ===")
        print("All debug messages will be shown in console")
        print("Raw responses from providers will be logged")
        print("=== END AISBF DEBUG MODE ===")
    else:
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
    
    # Add BrokenPipeError filter to all handlers
    broken_pipe_filter = BrokenPipeFilter()
    file_handler.addFilter(broken_pipe_filter)
    error_handler.addFilter(broken_pipe_filter)
    console_handler.addFilter(broken_pipe_filter)
    
    # Redirect stderr to error log with error handling and BrokenPipeError filtering
    try:
        sys.stderr = SafeStderr(sys.stderr, log_dir / 'aisbf_stderr.log')
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Could not redirect stderr: {e}")
    
    return logging.getLogger(__name__)

# Configure logging
logger = setup_logging()

# Initialize handlers
request_handler = RequestHandler()
rotation_handler = RotationHandler()
autoselect_handler = AutoselectHandler()

app = FastAPI(title="AI Proxy Server")

# Exception handler for validation errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors and log details"""
    print(f"\n=== VALIDATION ERROR (422) ===")
    print(f"Request path: {request.url.path}")
    print(f"Request method: {request.method}")
    print(f"Request headers: {dict(request.headers)}")
    
    # Try to get raw body
    try:
        raw_body = await request.body()
        print(f"Raw request body: {raw_body.decode('utf-8')}")
    except Exception as e:
        print(f"Error reading raw body: {str(e)}")
    
    print(f"Validation error details: {exc.errors()}")
    print(f"=== END VALIDATION ERROR ===\n")
    
    logger.error(f"=== VALIDATION ERROR (422) ===")
    logger.error(f"Request path: {request.url.path}")
    logger.error(f"Request method: {request.method}")
    logger.error(f"Request headers: {dict(request.headers)}")
    
    # Try to get raw body
    try:
        raw_body = await request.body()
        logger.error(f"Raw request body: {raw_body.decode('utf-8')}")
    except Exception as e:
        logger.error(f"Error reading raw body: {str(e)}")
    
    logger.error(f"Validation error details: {exc.errors()}")
    logger.error(f"=== END VALIDATION ERROR ===")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": exc.body}
    )

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
    return {
        "message": "AI Proxy Server is running",
        "providers": list(config.providers.keys()),
        "rotations": list(config.rotations.keys()),
        "autoselect": list(config.autoselect.keys())
    }

@app.get("/api/rotations")
async def list_rotations():
    """List all available rotations"""
    logger.info("=== LIST ROTATIONS REQUEST ===")
    rotations_info = {}
    for rotation_id, rotation_config in config.rotations.items():
        models = []
        for provider in rotation_config.providers:
            for model in provider['models']:
                models.append({
                    "name": model['name'],
                    "provider_id": provider['provider_id'],
                    "weight": model['weight'],
                    "rate_limit": model.get('rate_limit')
                })
        rotations_info[rotation_id] = {
            "model_name": rotation_config.model_name,
            "models": models
        }
    logger.info(f"Available rotations: {list(rotations_info.keys())}")
    return rotations_info

@app.post("/api/rotations/chat/completions")
async def rotation_chat_completions(request: Request, body: ChatCompletionRequest):
    """
    Handle chat completions for rotations using model name to select rotation.
    
    The RotationHandler handles streaming internally based on the selected
    provider's type (google vs others), so we just pass through the response.
    """
    logger.info(f"=== ROTATION CHAT COMPLETION REQUEST START ===")
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Model requested: {body.model}")
    logger.info(f"Request headers: {dict(request.headers)}")
    logger.info(f"Request body: {body}")
    logger.info(f"Available rotations: {list(config.rotations.keys())}")

    body_dict = body.model_dump()

    # Check if the model name corresponds to a rotation
    if body.model not in config.rotations:
        logger.error(f"Model '{body.model}' not found in rotations")
        logger.error(f"Available rotations: {list(config.rotations.keys())}")
        raise HTTPException(
            status_code=400,
            detail=f"Model '{body.model}' not found. Available rotations: {list(config.rotations.keys())}"
        )

    logger.info(f"Model '{body.model}' found in rotations")
    logger.debug("Handling rotation request")

    try:
        # The rotation handler handles streaming internally and returns
        # a StreamingResponse for streaming requests or a dict for non-streaming
        result = await rotation_handler.handle_rotation_request(body.model, body_dict)
        logger.debug(f"Rotation response result type: {type(result)}")
        return result
    except Exception as e:
        logger.error(f"Error handling rotation chat_completions: {str(e)}", exc_info=True)
        raise

@app.get("/api/rotations/models")
async def list_rotation_models():
    """List all models across all rotations"""
    logger.info("=== LIST ROTATION MODELS REQUEST ===")
    all_models = []
    for rotation_id, rotation_config in config.rotations.items():
        for provider in rotation_config.providers:
            for model in provider['models']:
                all_models.append({
                    "id": f"{rotation_id}/{model['name']}",
                    "name": rotation_id,  # Use rotation name as the model name for selection
                    "object": "model",
                    "owned_by": provider['provider_id'],
                    "rotation_id": rotation_id,
                    "actual_model": model['name'],
                    "provider_id": provider['provider_id'],
                    "weight": model['weight'],
                    "rate_limit": model.get('rate_limit')
                })
    logger.info(f"Total rotation models available: {len(all_models)}")
    return {"data": all_models}

@app.get("/api/autoselect")
async def list_autoselect():
    """List all available autoselect configurations"""
    logger.info("=== LIST AUTOSELECT REQUEST ===")
    autoselect_info = {}
    for autoselect_id, autoselect_config in config.autoselect.items():
        autoselect_info[autoselect_id] = {
            "model_name": autoselect_config.model_name,
            "description": autoselect_config.description,
            "fallback": autoselect_config.fallback,
            "available_models": [
                {
                    "model_id": m.model_id,
                    "description": m.description
                }
                for m in autoselect_config.available_models
            ]
        }
    logger.info(f"Available autoselect: {list(autoselect_info.keys())}")
    return autoselect_info

@app.post("/api/autoselect/chat/completions")
async def autoselect_chat_completions(request: Request, body: ChatCompletionRequest):
    """Handle chat completions for autoselect using model name to select autoselect configuration"""
    logger.info(f"=== AUTOSELECT CHAT COMPLETION REQUEST START ===")
    logger.info(f"Request path: {request.url.path}")
    logger.info(f"Request headers: {dict(request.headers)}")
    
    # Log raw request body for debugging
    try:
        raw_body = await request.body()
        logger.info(f"Raw request body: {raw_body.decode('utf-8')}")
    except Exception as e:
        logger.error(f"Error reading raw body: {str(e)}")
    
    logger.info(f"Model requested: {body.model}")
    logger.info(f"Request body: {body}")
    logger.info(f"Available autoselect: {list(config.autoselect.keys())}")

    body_dict = body.model_dump()

    # Check if the model name corresponds to an autoselect configuration
    if body.model not in config.autoselect:
        logger.error(f"Model '{body.model}' not found in autoselect")
        logger.error(f"Available autoselect: {list(config.autoselect.keys())}")
        raise HTTPException(
            status_code=400,
            detail=f"Model '{body.model}' not found. Available autoselect: {list(config.autoselect.keys())}"
        )

    logger.info(f"Model '{body.model}' found in autoselect")
    logger.debug("Handling autoselect request")

    try:
        if body.stream:
            logger.debug("Handling streaming autoselect request")
            return await autoselect_handler.handle_autoselect_streaming_request(body.model, body_dict)
        else:
            logger.debug("Handling non-streaming autoselect request")
            result = await autoselect_handler.handle_autoselect_request(body.model, body_dict)
            logger.debug(f"Autoselect response result: {result}")
            return result
    except Exception as e:
        logger.error(f"Error handling autoselect chat_completions: {str(e)}", exc_info=True)
        raise

@app.get("/api/autoselect/models")
async def list_autoselect_models():
    """List all models across all autoselect configurations"""
    logger.info("=== LIST AUTOSELECT MODELS REQUEST ===")
    all_models = []
    for autoselect_id, autoselect_config in config.autoselect.items():
        for model_info in autoselect_config.available_models:
            all_models.append({
                "id": model_info.model_id,
                "name": autoselect_id,  # Use autoselect name as the model name for selection
                "object": "model",
                "owned_by": "autoselect",
                "autoselect_id": autoselect_id,
                "description": model_info.description,
                "fallback": autoselect_config.fallback
            })
    logger.info(f"Total autoselect models available: {len(all_models)}")
    return {"data": all_models}

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
    
    # Load server configuration
    server_config = load_server_config()
    host = server_config['host']
    port = server_config['port']
    
    logger.info(f"Starting AI Proxy Server on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main()
