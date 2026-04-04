"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

MCP (Model Context Protocol) Server for AISBF.

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

MCP Server for AISBF - Provides remote agent configuration capabilities.
"""
import time
import json
import logging
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from .config import config

logger = logging.getLogger(__name__)


class MCPAuthLevel:
    """MCP authentication levels"""
    NONE = 0
    AUTOSELECT = 1  # Can access autoselection and autorotation settings
    FULLCONFIG = 2  # Can access all configurations (providers, rotations, autoselect, aisbf)


def load_mcp_config() -> Dict:
    """Load MCP configuration from aisbf.json"""
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
            # Fallback to source tree
            config_path = Path(__file__).parent.parent / 'config' / 'aisbf.json'
    
    if config_path.exists():
        with open(config_path) as f:
            aisbf_config = json.load(f)
            return aisbf_config.get('mcp', {
                'enabled': False,
                'autoselect_tokens': [],
                'fullconfig_tokens': []
            })
    
    return {'enabled': False, 'autoselect_tokens': [], 'fullconfig_tokens': []}


def get_auth_level(token: str) -> int:
    """
    Get the authentication level for a given token.
    
    Returns:
        MCPAuthLevel.NONE - No access
        MCPAuthLevel.AUTOSELECT - Can access autoselection/autorotation settings
        MCPAuthLevel.FULLCONFIG - Can access all configurations
    """
    mcp_config = load_mcp_config()
    
    if not mcp_config.get('enabled', False):
        return MCPAuthLevel.FULLCONFIG  # If MCP is not enabled, allow all
    
    fullconfig_tokens = mcp_config.get('fullconfig_tokens', [])
    autoselect_tokens = mcp_config.get('autoselect_tokens', [])
    
    if token in fullconfig_tokens:
        return MCPAuthLevel.FULLCONFIG
    
    if token in autoselect_tokens:
        return MCPAuthLevel.AUTOSELECT
    
    return MCPAuthLevel.NONE


def require_auth(auth_level: int = MCPAuthLevel.AUTOSELECT):
    """Decorator to require specific auth level"""
    def decorator(func):
        async def wrapper(request: Request, *args, **kwargs):
            # Get token from header
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                raise HTTPException(
                    status_code=401,
                    detail="Missing or invalid Authorization header. Use: Authorization: Bearer <token>"
                )
            
            token = auth_header.replace('Bearer ', '')
            level = get_auth_level(token)
            
            if level == MCPAuthLevel.NONE:
                raise HTTPException(
                    status_code=403,
                    detail="Invalid MCP authentication token"
                )
            
            if level < auth_level:
                if auth_level == MCPAuthLevel.FULLCONFIG:
                    raise HTTPException(
                        status_code=403,
                        detail="Token does not have fullconfig access. Use a fullconfig token."
                    )
                else:
                    raise HTTPException(
                        status_code=403,
                        detail="Token does not have sufficient permissions"
                    )
            
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator


class MCPServer:
    """MCP Server for AISBF"""
    
    def __init__(self):
        self.config = config
    
    def get_available_tools(self, auth_level: int, user_id: Optional[int] = None) -> List[Dict]:
        """
        Get list of available MCP tools based on auth level and user.
        
        Args:
            auth_level: The authentication level (MCPAuthLevel)
            user_id: Optional user ID to include user-specific tools
            
        Returns:
            List of tool definitions
        """
        tools = []
        
        # Tools available to all authenticated users (AUTOSELECT and above)
        tools.extend([
            {
                "name": "list_models",
                "description": "List all available models from all providers, rotations, and autoselect configurations",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "list_rotations",
                "description": "List all available rotation configurations",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "list_autoselect",
                "description": "List all available autoselect configurations",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "chat_completion",
                "description": "Send a chat completion request to a model (provider, rotation, or autoselect)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "Model identifier (e.g., 'gemini/gemini-pro', 'rotation/coding', 'autoselect/default')"
                        },
                        "messages": {
                            "type": "array",
                            "description": "List of message objects with role and content"
                        },
                        "temperature": {
                            "type": "number",
                            "description": "Sampling temperature (0-2)",
                            "default": 1.0
                        },
                        "max_tokens": {
                            "type": "integer",
                            "description": "Maximum tokens to generate",
                            "default": 2048
                        },
                        "stream": {
                            "type": "boolean",
                            "description": "Enable streaming response",
                            "default": False
                        }
                    },
                    "required": ["model", "messages"]
                }
            }
        ])
        
        # Add user-specific tools if user_id is provided
        if user_id:
            tools.extend([
                # User models
                {
                    "name": "list_user_models",
                    "description": "List all models from user's own providers, rotations, and autoselects",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                # User providers
                {
                    "name": "list_user_providers",
                    "description": "List all user-configured providers",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "get_user_provider",
                    "description": "Get a specific user provider configuration",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "provider_id": {
                                "type": "string",
                                "description": "Provider ID to get"
                            }
                        },
                        "required": ["provider_id"]
                    }
                },
                {
                    "name": "set_user_provider",
                    "description": "Save a user provider configuration",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "provider_id": {
                                "type": "string",
                                "description": "Provider ID to save"
                            },
                            "provider_data": {
                                "type": "object",
                                "description": "Provider configuration data"
                            }
                        },
                        "required": ["provider_id", "provider_data"]
                    }
                },
                {
                    "name": "delete_user_provider",
                    "description": "Delete a user provider configuration",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "provider_id": {
                                "type": "string",
                                "description": "Provider ID to delete"
                            }
                        },
                        "required": ["provider_id"]
                    }
                },
                # User rotations
                {
                    "name": "list_user_rotations",
                    "description": "List all user-configured rotations",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "get_user_rotation",
                    "description": "Get a specific user rotation configuration",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "rotation_id": {
                                "type": "string",
                                "description": "Rotation ID to get"
                            }
                        },
                        "required": ["rotation_id"]
                    }
                },
                {
                    "name": "set_user_rotation",
                    "description": "Save a user rotation configuration",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "rotation_id": {
                                "type": "string",
                                "description": "Rotation ID to save"
                            },
                            "rotation_data": {
                                "type": "object",
                                "description": "Rotation configuration data"
                            }
                        },
                        "required": ["rotation_id", "rotation_data"]
                    }
                },
                {
                    "name": "delete_user_rotation",
                    "description": "Delete a user rotation configuration",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "rotation_id": {
                                "type": "string",
                                "description": "Rotation ID to delete"
                            }
                        },
                        "required": ["rotation_id"]
                    }
                },
                # User autoselects
                {
                    "name": "list_user_autoselects",
                    "description": "List all user-configured autoselects",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "get_user_autoselect",
                    "description": "Get a specific user autoselect configuration",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "autoselect_id": {
                                "type": "string",
                                "description": "Autoselect ID to get"
                            }
                        },
                        "required": ["autoselect_id"]
                    }
                },
                {
                    "name": "set_user_autoselect",
                    "description": "Save a user autoselect configuration",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "autoselect_id": {
                                "type": "string",
                                "description": "Autoselect ID to save"
                            },
                            "autoselect_data": {
                                "type": "object",
                                "description": "Autoselect configuration data"
                            }
                        },
                        "required": ["autoselect_id", "autoselect_data"]
                    }
                },
                {
                    "name": "delete_user_autoselect",
                    "description": "Delete a user autoselect configuration",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "autoselect_id": {
                                "type": "string",
                                "description": "Autoselect ID to delete"
                            }
                        },
                        "required": ["autoselect_id"]
                    }
                },
                # User chat completion
                {
                    "name": "user_chat_completion",
                    "description": "Send a chat completion request using user's own configurations",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "model": {
                                "type": "string",
                                "description": "User model identifier (e.g., 'user-provider/myprovider/mymodel', 'user-rotation/myrotation', 'user-autoselect/myautoselect')"
                            },
                            "messages": {
                                "type": "array",
                                "description": "List of message objects with role and content"
                            },
                            "temperature": {
                                "type": "number",
                                "description": "Sampling temperature (0-2)",
                                "default": 1.0
                            },
                            "max_tokens": {
                                "type": "integer",
                                "description": "Maximum tokens to generate",
                                "default": 2048
                            },
                            "stream": {
                                "type": "boolean",
                                "description": "Enable streaming response",
                                "default": False
                            }
                        },
                        "required": ["model", "messages"]
                    }
                }
            ])
        
        # Tools available to AUTOSELECT level and above
        if auth_level >= MCPAuthLevel.AUTOSELECT:
            tools.extend([
                {
                    "name": "get_autoselect_config",
                    "description": "Get autoselect configuration (rotation and autoselect settings only)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "autoselect_id": {
                                "type": "string",
                                "description": "Optional autoselect ID to get specific config. If not provided, returns all."
                            }
                        },
                        "required": []
                    }
                },
                {
                    "name": "get_rotation_config",
                    "description": "Get rotation configuration",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "rotation_id": {
                                "type": "string",
                                "description": "Optional rotation ID to get specific config. If not provided, returns all."
                            }
                        },
                        "required": []
                    }
                },
                {
                    "name": "get_autoselect_settings",
                    "description": "Get detailed autoselect settings including model selection logic",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "autoselect_id": {
                                "type": "string",
                                "description": "Autoselect ID to get settings for"
                            }
                        },
                        "required": ["autoselect_id"]
                    }
                },
                {
                    "name": "get_rotation_settings",
                    "description": "Get detailed rotation settings including provider weights",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "rotation_id": {
                                "type": "string",
                                "description": "Rotation ID to get settings for"
                            }
                        },
                        "required": ["rotation_id"]
                    }
                }
            ])
        
        # Tools available only to FULLCONFIG level
        if auth_level >= MCPAuthLevel.FULLCONFIG:
            tools.extend([
                {
                    "name": "get_providers_config",
                    "description": "Get provider configurations (requires fullconfig access)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "provider_id": {
                                "type": "string",
                                "description": "Optional provider ID to get specific config. If not provided, returns all."
                            }
                        },
                        "required": []
                    }
                },
                {
                    "name": "set_autoselect_config",
                    "description": "Set autoselect configuration (requires fullconfig access)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "autoselect_id": {
                                "type": "string",
                                "description": "Autoselect configuration ID"
                            },
                            "autoselect_data": {
                                "type": "object",
                                "description": "Autoselect configuration data"
                            }
                        },
                        "required": ["autoselect_id", "autoselect_data"]
                    }
                },
                {
                    "name": "set_rotation_config",
                    "description": "Set rotation configuration (requires fullconfig access)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "rotation_id": {
                                "type": "string",
                                "description": "Rotation configuration ID"
                            },
                            "rotation_data": {
                                "type": "object",
                                "description": "Rotation configuration data"
                            }
                        },
                        "required": ["rotation_id", "rotation_data"]
                    }
                },
                {
                    "name": "set_provider_config",
                    "description": "Set provider configuration (requires fullconfig access)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "provider_id": {
                                "type": "string",
                                "description": "Provider configuration ID"
                            },
                            "provider_data": {
                                "type": "object",
                                "description": "Provider configuration data"
                            }
                        },
                        "required": ["provider_id", "provider_data"]
                    }
                },
                {
                    "name": "get_server_config",
                    "description": "Get AISBF server configuration (requires fullconfig access)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "set_server_config",
                    "description": "Set AISBF server configuration (requires fullconfig access)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "server_data": {
                                "type": "object",
                                "description": "Server configuration data"
                            }
                        },
                        "required": ["server_data"]
                    }
                },
                {
                    "name": "get_tor_status",
                    "description": "Get TOR hidden service status (requires fullconfig access)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                },
                {
                    "name": "delete_autoselect_config",
                    "description": "Delete an autoselect configuration (requires fullconfig access)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "autoselect_id": {
                                "type": "string",
                                "description": "Autoselect configuration ID to delete"
                            }
                        },
                        "required": ["autoselect_id"]
                    }
                },
                {
                    "name": "delete_rotation_config",
                    "description": "Delete a rotation configuration (requires fullconfig access)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "rotation_id": {
                                "type": "string",
                                "description": "Rotation configuration ID to delete"
                            }
                        },
                        "required": ["rotation_id"]
                    }
                },
                {
                    "name": "delete_provider_config",
                    "description": "Delete a provider configuration (requires fullconfig access)",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "provider_id": {
                                "type": "string",
                                "description": "Provider configuration ID to delete"
                            }
                        },
                        "required": ["provider_id"]
                    }
                }
            ])
        
        return tools
    
    async def handle_tool_call(self, tool_name: str, arguments: Dict, auth_level: int, user_id: Optional[int] = None) -> Dict:
        """
        Handle an MCP tool call.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            auth_level: Authentication level
            user_id: Optional user ID for user-specific operations
            
        Returns:
            Tool result
        """
        # Route to appropriate handler
        handlers = {
            # Common tools
            'list_models': self._list_models,
            'list_rotations': self._list_rotations,
            'list_autoselect': self._list_autoselect,
            'chat_completion': self._chat_completion,
        }
        
        # Add autoselect-level tools
        if auth_level >= MCPAuthLevel.AUTOSELECT:
            handlers.update({
                'get_autoselect_config': self._get_autoselect_config,
                'get_rotation_config': self._get_rotation_config,
                'get_autoselect_settings': self._get_autoselect_settings,
                'get_rotation_settings': self._get_rotation_settings,
            })
        
        # Add fullconfig-level tools (now support user_id for routing)
        if auth_level >= MCPAuthLevel.FULLCONFIG:
            handlers.update({
                'get_providers_config': self._get_providers_config,
                'set_autoselect_config': lambda args: self._set_autoselect_config(args, user_id),
                'set_rotation_config': lambda args: self._set_rotation_config(args, user_id),
                'set_provider_config': lambda args: self._set_provider_config(args, user_id),
                'get_server_config': self._get_server_config,
                'set_server_config': self._set_server_config,
                'get_tor_status': self._get_tor_status,
                'delete_autoselect_config': self._delete_autoselect_config,
                'delete_rotation_config': self._delete_rotation_config,
                'delete_provider_config': self._delete_provider_config,
            })
        
        # Add user-specific tools (available to all authenticated users with user_id)
        if user_id:
            handlers.update({
                # User models
                'list_user_models': self._list_user_models,
                # User providers
                'list_user_providers': self._list_user_providers,
                'get_user_provider': self._get_user_provider,
                'set_user_provider': self._set_user_provider,
                'delete_user_provider': self._delete_user_provider,
                # User rotations
                'list_user_rotations': self._list_user_rotations,
                'get_user_rotation': self._get_user_rotation,
                'set_user_rotation': self._set_user_rotation,
                'delete_user_rotation': self._delete_user_rotation,
                # User autoselects
                'list_user_autoselects': self._list_user_autoselects,
                'get_user_autoselect': self._get_user_autoselect,
                'set_user_autoselect': self._set_user_autoselect,
                'delete_user_autoselect': self._delete_user_autoselect,
                # User chat completion
                'user_chat_completion': self._user_chat_completion,
            })
        
        if tool_name not in handlers:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
        
        handler = handlers[tool_name]
        return await handler(arguments)
    
    async def _list_models(self, args: Dict) -> Dict:
        """List all available models"""
        from .handlers import RequestHandler, RotationHandler, AutoselectHandler
        
        all_models = []
        
        # Add provider models
        for provider_id, provider_config in self.config.providers.items():
            try:
                request_handler = RequestHandler()
                # Create dummy request for handler
                from starlette.requests import Request
                scope = {"type": "http", "method": "GET", "headers": [], "query_string": b"", "path": f"/api/{provider_id}/models"}
                dummy_request = Request(scope)
                provider_models = await request_handler.handle_model_list(dummy_request, provider_id)
                for model in provider_models:
                    model['id'] = f"{provider_id}/{model.get('id', '')}"
                    # Ensure OpenAI-compatible required fields are present
                    if 'object' not in model:
                        model['object'] = 'model'
                    if 'created' not in model:
                        model['created'] = int(time.time())
                    if 'owned_by' not in model:
                        model['owned_by'] = provider_config.name
                    model['type'] = 'provider'
                    all_models.append(model)
            except Exception as e:
                logger.warning(f"Error listing models for provider {provider_id}: {e}")
        
        # Add rotations
        for rotation_id, rotation_config in self.config.rotations.items():
            all_models.append({
                'id': f"rotation/{rotation_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-rotation',
                'type': 'rotation',
                'rotation_id': rotation_id,
                'model_name': rotation_config.model_name,
                'capabilities': getattr(rotation_config, 'capabilities', [])
            })
        
        # Add autoselect
        for autoselect_id, autoselect_config in self.config.autoselect.items():
            all_models.append({
                'id': f"autoselect/{autoselect_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-autoselect',
                'type': 'autoselect',
                'autoselect_id': autoselect_id,
                'model_name': autoselect_config.model_name,
                'description': autoselect_config.description,
                'capabilities': getattr(autoselect_config, 'capabilities', [])
            })
        
        return {"models": all_models}
    
    async def _list_rotations(self, args: Dict) -> Dict:
        """List all rotations"""
        rotations_info = {}
        for rotation_id, rotation_config in self.config.rotations.items():
            rotations_info[rotation_id] = {
                "model_name": rotation_config.model_name,
                "providers": rotation_config.providers
            }
        return {"rotations": rotations_info}
    
    async def _list_autoselect(self, args: Dict) -> Dict:
        """List all autoselect configurations"""
        autoselect_info = {}
        for autoselect_id, autoselect_config in self.config.autoselect.items():
            autoselect_info[autoselect_id] = {
                "model_name": autoselect_config.model_name,
                "description": autoselect_config.description,
                "fallback": autoselect_config.fallback,
                "selection_model": getattr(autoselect_config, 'selection_model', 'internal'),
                "available_models": [
                    {"model_id": m.model_id, "description": m.description}
                    for m in autoselect_config.available_models
                ]
            }
        return {"autoselect": autoselect_info}
    
    async def _chat_completion(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Handle chat completion request"""
        from .handlers import RequestHandler, RotationHandler, AutoselectHandler
        from .models import ChatCompletionRequest
        from starlette.requests import Request

        model = args.get('model')
        messages = args.get('messages', [])
        temperature = args.get('temperature', 1.0)
        max_tokens = args.get('max_tokens', 2048)
        stream = args.get('stream', False)

        # Parse provider from model
        if '/' in model:
            parts = model.split('/', 1)
            provider_id = parts[0]
            actual_model = parts[1]
        else:
            provider_id = model
            actual_model = model

        # Create request data
        request_data = {
            "model": actual_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }

        # Create dummy request
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": b"",
            "path": f"/api/{provider_id}/chat/completions"
        }
        dummy_request = Request(scope)

        # Route to appropriate handler (with user_id support)
        from main import get_user_handler
        if provider_id == "autoselect":
            handler = get_user_handler('autoselect', user_id)
            if actual_model not in self.config.autoselect and (not user_id or actual_model not in handler.user_autoselects):
                raise HTTPException(status_code=400, detail=f"Autoselect '{actual_model}' not found")
            if stream:
                return {"error": "Streaming not supported in MCP, use SSE endpoint instead"}
            else:
                return await handler.handle_autoselect_request(actual_model, request_data)
        elif provider_id == "rotation":
            handler = get_user_handler('rotation', user_id)
            if actual_model not in self.config.rotations and (not user_id or actual_model not in handler.user_rotations):
                raise HTTPException(status_code=400, detail=f"Rotation '{actual_model}' not found")
            return await handler.handle_rotation_request(actual_model, request_data)
        else:
            handler = get_user_handler('request', user_id)
            if provider_id not in self.config.providers and (not user_id or provider_id not in handler.user_providers):
                raise HTTPException(status_code=400, detail=f"Provider '{provider_id}' not found")
            if stream:
                return {"error": "Streaming not supported in MCP, use SSE endpoint instead"}
            else:
                return await handler.handle_chat_completion(dummy_request, provider_id, request_data)
    
    async def _get_autoselect_config(self, args: Dict) -> Dict:
        """Get autoselect configuration"""
        autoselect_id = args.get('autoselect_id')
        
        if autoselect_id:
            if autoselect_id not in self.config.autoselect:
                raise HTTPException(status_code=404, detail=f"Autoselect '{autoselect_id}' not found")
            autoselect_config = self.config.autoselect[autoselect_id]
            return {
                "autoselect_id": autoselect_id,
                "config": {
                    "model_name": autoselect_config.model_name,
                    "description": autoselect_config.description,
                    "fallback": autoselect_config.fallback,
                    "selection_model": getattr(autoselect_config, 'selection_model', 'internal'),
                    "available_models": [
                        {"model_id": m.model_id, "description": m.description}
                        for m in autoselect_config.available_models
                    ]
                }
            }
        else:
            # Return all autoselect configs
            all_autoselect = {}
            for as_id, as_config in self.config.autoselect.items():
                all_autoselect[as_id] = {
                    "model_name": as_config.model_name,
                    "description": as_config.description,
                    "fallback": as_config.fallback,
                    "selection_model": getattr(as_config, 'selection_model', 'internal'),
                    "available_models": [
                        {"model_id": m.model_id, "description": m.description}
                        for m in as_config.available_models
                    ]
                }
            return {"autoselect": all_autoselect}
    
    async def _get_rotation_config(self, args: Dict) -> Dict:
        """Get rotation configuration"""
        rotation_id = args.get('rotation_id')
        
        if rotation_id:
            if rotation_id not in self.config.rotations:
                raise HTTPException(status_code=404, detail=f"Rotation '{rotation_id}' not found")
            rotation_config = self.config.rotations[rotation_id]
            return {
                "rotation_id": rotation_id,
                "config": {
                    "model_name": rotation_config.model_name,
                    "providers": rotation_config.providers
                }
            }
        else:
            # Return all rotation configs
            all_rotations = {}
            for rot_id, rot_config in self.config.rotations.items():
                all_rotations[rot_id] = {
                    "model_name": rot_config.model_name,
                    "providers": rot_config.providers
                }
            return {"rotations": all_rotations}
    
    async def _get_autoselect_settings(self, args: Dict) -> Dict:
        """Get detailed autoselect settings"""
        autoselect_id = args.get('autoselect_id')
        
        if not autoselect_id:
            raise HTTPException(status_code=400, detail="autoselect_id is required")
        
        if autoselect_id not in self.config.autoselect:
            raise HTTPException(status_code=404, detail=f"Autoselect '{autoselect_id}' not found")
        
        # Load full autoselect config from file
        config_path = Path.home() / '.aisbf' / 'autoselect.json'
        if not config_path.exists():
            config_path = Path(__file__).parent.parent / 'config' / 'autoselect.json'
        
        with open(config_path) as f:
            full_config = json.load(f)
        
        autoselect_data = full_config.get('autoselect', {})
        return {"autoselect_id": autoselect_id, "settings": autoselect_data.get(autoselect_id, {})}
    
    async def _get_rotation_settings(self, args: Dict) -> Dict:
        """Get detailed rotation settings"""
        rotation_id = args.get('rotation_id')
        
        if not rotation_id:
            raise HTTPException(status_code=400, detail="rotation_id is required")
        
        if rotation_id not in self.config.rotations:
            raise HTTPException(status_code=404, detail=f"Rotation '{rotation_id}' not found")
        
        # Load full rotation config from file
        config_path = Path.home() / '.aisbf' / 'rotations.json'
        if not config_path.exists():
            config_path = Path(__file__).parent.parent / 'config' / 'rotations.json'
        
        with open(config_path) as f:
            full_config = json.load(f)
        
        rotations_data = full_config.get('rotations', {})
        return {"rotation_id": rotation_id, "settings": rotations_data.get(rotation_id, {})}
    
    async def _get_providers_config(self, args: Dict) -> Dict:
        """Get provider configuration"""
        provider_id = args.get('provider_id')
        
        # Load from file to get full config including api keys
        config_path = Path.home() / '.aisbf' / 'providers.json'
        if not config_path.exists():
            config_path = Path(__file__).parent.parent / 'config' / 'providers.json'
        
        with open(config_path) as f:
            full_config = json.load(f)
        
        providers_data = full_config.get('providers', {})
        
        if provider_id:
            if provider_id not in providers_data:
                raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
            return {"provider_id": provider_id, "config": providers_data[provider_id]}
        else:
            return {"providers": providers_data}
    
    async def _set_autoselect_config(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Set autoselect configuration. Config admin saves to files, other users save to database."""
        autoselect_id = args.get('autoselect_id')
        autoselect_data = args.get('autoselect_data')
        
        if not autoselect_id or not autoselect_data:
            raise HTTPException(status_code=400, detail="autoselect_id and autoselect_data are required")
        
        # Check if user is config admin (user_id is None means config admin)
        is_config_admin = user_id is None
        
        if is_config_admin:
            # Config admin: save to JSON files
            config_path = Path.home() / '.aisbf' / 'autoselect.json'
            if not config_path.exists():
                config_path = Path(__file__).parent.parent / 'config' / 'autoselect.json'
            
            with open(config_path) as f:
                full_config = json.load(f)
            
            if 'autoselect' not in full_config:
                full_config['autoselect'] = {}
            
            full_config['autoselect'][autoselect_id] = autoselect_data
            
            # Save config
            save_path = Path.home() / '.aisbf' / 'autoselect.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            
            return {"status": "success", "message": f"Autoselect '{autoselect_id}' saved to file. Restart server for changes to take effect."}
        else:
            # Database user: save to database
            from .database import get_database
            db = get_database()
            db.save_user_autoselect(user_id, autoselect_id, autoselect_data)
            return {"status": "success", "message": f"Autoselect '{autoselect_id}' saved to database for user {user_id}."}
    
    async def _set_rotation_config(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Set rotation configuration. Config admin saves to files, other users save to database."""
        rotation_id = args.get('rotation_id')
        rotation_data = args.get('rotation_data')
        
        if not rotation_id or not rotation_data:
            raise HTTPException(status_code=400, detail="rotation_id and rotation_data are required")
        
        # Check if user is config admin (user_id is None means config admin)
        is_config_admin = user_id is None
        
        if is_config_admin:
            # Config admin: save to JSON files
            config_path = Path.home() / '.aisbf' / 'rotations.json'
            if not config_path.exists():
                config_path = Path(__file__).parent.parent / 'config' / 'rotations.json'
            
            with open(config_path) as f:
                full_config = json.load(f)
            
            if 'rotations' not in full_config:
                full_config['rotations'] = {}
            
            full_config['rotations'][rotation_id] = rotation_data
            
            # Save config
            save_path = Path.home() / '.aisbf' / 'rotations.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            
            return {"status": "success", "message": f"Rotation '{rotation_id}' saved to file. Restart server for changes to take effect."}
        else:
            # Database user: save to database
            from .database import get_database
            db = get_database()
            db.save_user_rotation(user_id, rotation_id, rotation_data)
            return {"status": "success", "message": f"Rotation '{rotation_id}' saved to database for user {user_id}."}
    
    async def _set_provider_config(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Set provider configuration. Config admin saves to files, other users save to database."""
        provider_id = args.get('provider_id')
        provider_data = args.get('provider_data')
        
        if not provider_id or not provider_data:
            raise HTTPException(status_code=400, detail="provider_id and provider_data are required")
        
        # Check if user is config admin (user_id is None means config admin)
        is_config_admin = user_id is None
        
        if is_config_admin:
            # Config admin: save to JSON files
            config_path = Path.home() / '.aisbf' / 'providers.json'
            if not config_path.exists():
                config_path = Path(__file__).parent.parent / 'config' / 'providers.json'
            
            with open(config_path) as f:
                full_config = json.load(f)
            
            if 'providers' not in full_config:
                full_config['providers'] = {}
            
            full_config['providers'][provider_id] = provider_data
            
            # Save config
            save_path = Path.home() / '.aisbf' / 'providers.json'
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'w') as f:
                json.dump(full_config, f, indent=2)
            
            return {"status": "success", "message": f"Provider '{provider_id}' saved to file. Restart server for changes to take effect."}
        else:
            # Database user: save to database
            from .database import get_database
            db = get_database()
            db.save_user_provider(user_id, provider_id, provider_data)
            return {"status": "success", "message": f"Provider '{provider_id}' saved to database for user {user_id}."}
    
    async def _get_server_config(self, args: Dict) -> Dict:
        """Get server configuration"""
        config_path = Path.home() / '.aisbf' / 'aisbf.json'
        if not config_path.exists():
            config_path = Path(__file__).parent.parent / 'config' / 'aisbf.json'
        
        with open(config_path) as f:
            server_config = json.load(f)
        
        return {"server_config": server_config}
    
    async def _set_server_config(self, args: Dict) -> Dict:
        """Set server configuration"""
        server_data = args.get('server_data')
        
        if not server_data:
            raise HTTPException(status_code=400, detail="server_data is required")
        
        # Load existing config
        config_path = Path.home() / '.aisbf' / 'aisbf.json'
        if not config_path.exists():
            config_path = Path(__file__).parent.parent / 'config' / 'aisbf.json'
        
        with open(config_path) as f:
            full_config = json.load(f)
        
        # Merge new data
        full_config.update(server_data)
        
        # Save config
        save_path = Path.home() / '.aisbf' / 'aisbf.json'
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'w') as f:
            json.dump(full_config, f, indent=2)
        
        return {"status": "success", "message": "Server config saved. Restart server for changes to take effect."}
    
    async def _get_tor_status(self, args: Dict) -> Dict:
        """Get TOR hidden service status"""
        # Import tor_service from main module
        try:
            import main
            tor_service = getattr(main, 'tor_service', None)
            
            if tor_service:
                status = tor_service.get_status()
                return {"tor_status": status}
            else:
                return {
                    "tor_status": {
                        "enabled": False,
                        "connected": False,
                        "onion_address": None,
                        "service_id": None,
                        "control_host": None,
                        "control_port": None,
                        "hidden_service_port": None
                    }
                }
        except Exception as e:
            logger.error(f"Error getting TOR status: {e}")
            return {
                "tor_status": {
                    "enabled": False,
                    "connected": False,
                    "error": str(e)
                }
            }
    
    async def _delete_autoselect_config(self, args: Dict) -> Dict:
        """Delete autoselect configuration"""
        autoselect_id = args.get('autoselect_id')
        
        if not autoselect_id:
            raise HTTPException(status_code=400, detail="autoselect_id is required")
        
        # Load existing config
        config_path = Path.home() / '.aisbf' / 'autoselect.json'
        if not config_path.exists():
            raise HTTPException(status_code=404, detail="Autoselect config not found")
        
        with open(config_path) as f:
            full_config = json.load(f)
        
        if autoselect_id not in full_config.get('autoselect', {}):
            raise HTTPException(status_code=404, detail=f"Autoselect '{autoselect_id}' not found")
        
        del full_config['autoselect'][autoselect_id]
        
        # Save config
        save_path = Path.home() / '.aisbf' / 'autoselect.json'
        with open(save_path, 'w') as f:
            json.dump(full_config, f, indent=2)
        
        return {"status": "success", "message": f"Autoselect '{autoselect_id}' deleted. Restart server for changes to take effect."}
    
    async def _delete_rotation_config(self, args: Dict) -> Dict:
        """Delete rotation configuration"""
        rotation_id = args.get('rotation_id')
        
        if not rotation_id:
            raise HTTPException(status_code=400, detail="rotation_id is required")
        
        # Load existing config
        config_path = Path.home() / '.aisbf' / 'rotations.json'
        if not config_path.exists():
            raise HTTPException(status_code=404, detail="Rotations config not found")
        
        with open(config_path) as f:
            full_config = json.load(f)
        
        if rotation_id not in full_config.get('rotations', {}):
            raise HTTPException(status_code=404, detail=f"Rotation '{rotation_id}' not found")
        
        del full_config['rotations'][rotation_id]
        
        # Save config
        save_path = Path.home() / '.aisbf' / 'rotations.json'
        with open(save_path, 'w') as f:
            json.dump(full_config, f, indent=2)
        
        return {"status": "success", "message": f"Rotation '{rotation_id}' deleted. Restart server for changes to take effect."}
    
    async def _delete_provider_config(self, args: Dict) -> Dict:
        """Delete provider configuration"""
        provider_id = args.get('provider_id')
        
        if not provider_id:
            raise HTTPException(status_code=400, detail="provider_id is required")
        
        # Load existing config
        config_path = Path.home() / '.aisbf' / 'providers.json'
        if not config_path.exists():
            raise HTTPException(status_code=404, detail="Providers config not found")
        
        with open(config_path) as f:
            full_config = json.load(f)
        
        if provider_id not in full_config.get('providers', {}):
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
        
        del full_config['providers'][provider_id]
        
        # Save config
        save_path = Path.home() / '.aisbf' / 'providers.json'
        with open(save_path, 'w') as f:
            json.dump(full_config, f, indent=2)
        
        return {"status": "success", "message": f"Provider '{provider_id}' deleted. Restart server for changes to take effect."}


    # ===== User-specific MCP tools =====
    
    async def _list_user_models(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """List all models from user's own providers, rotations, and autoselects"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        from .database import get_database
        db = get_database()
        
        all_models = []
        
        # Get user providers
        user_providers = db.get_user_providers(user_id)
        for provider in user_providers:
            provider_id = provider['provider_id']
            provider_config = provider['config']
            models = provider_config.get('models', [])
            for model in models:
                all_models.append({
                    'id': f"user-provider/{provider_id}/{model.get('name', '')}",
                    'object': 'model',
                    'created': int(time.time()),
                    'owned_by': provider_id,
                    'provider': provider_id,
                    'type': 'user_provider',
                    'model_name': model.get('name', ''),
                    'source': 'user_config'
                })
        
        # Get user rotations
        user_rotations = db.get_user_rotations(user_id)
        for rotation in user_rotations:
            rotation_id = rotation['rotation_id']
            rotation_config = rotation['config']
            all_models.append({
                'id': f"user-rotation/{rotation_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-user-rotation',
                'type': 'user_rotation',
                'rotation_id': rotation_id,
                'model_name': rotation_config.get('model_name', rotation_id),
                'source': 'user_config'
            })
        
        # Get user autoselects
        user_autoselects = db.get_user_autoselects(user_id)
        for autoselect in user_autoselects:
            autoselect_id = autoselect['autoselect_id']
            autoselect_config = autoselect['config']
            all_models.append({
                'id': f"user-autoselect/{autoselect_id}",
                'object': 'model',
                'created': int(time.time()),
                'owned_by': 'aisbf-user-autoselect',
                'type': 'user_autoselect',
                'autoselect_id': autoselect_id,
                'model_name': autoselect_config.get('model_name', autoselect_id),
                'description': autoselect_config.get('description'),
                'source': 'user_config'
            })
        
        return {"models": all_models}

    async def _list_user_providers(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """List all user-configured providers"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        from .database import get_database
        db = get_database()
        
        providers = db.get_user_providers(user_id)
        providers_info = {}
        
        for provider in providers:
            provider_id = provider['provider_id']
            provider_config = provider['config']
            # Remove sensitive fields
            safe_config = {k: v for k, v in provider_config.items() 
                          if k not in ['api_key', 'password', 'secret', 'token']}
            
            providers_info[provider_id] = {
                'name': provider_config.get('name', provider_id),
                'type': provider_config.get('type', 'unknown'),
                'endpoint': provider_config.get('endpoint'),
                'models_count': len(provider_config.get('models', [])),
                'config': safe_config
            }
        
        return {"providers": providers_info}

    async def _get_user_provider(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Get a specific user provider configuration"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        provider_id = args.get('provider_id')
        if not provider_id:
            raise HTTPException(status_code=400, detail="provider_id is required")
        
        from .database import get_database
        db = get_database()
        
        provider = db.get_user_provider(user_id, provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
        
        # Remove sensitive fields
        safe_config = {k: v for k, v in provider['config'].items() 
                      if k not in ['api_key', 'password', 'secret', 'token']}
        
        return {"provider_id": provider_id, "config": safe_config}

    async def _set_user_provider(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Save a user provider configuration"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        provider_id = args.get('provider_id')
        provider_data = args.get('provider_data')
        
        if not provider_id or not provider_data:
            raise HTTPException(status_code=400, detail="provider_id and provider_data are required")
        
        from .database import get_database
        db = get_database()
        
        db.save_user_provider(user_id, provider_id, provider_data)
        
        return {"status": "success", "message": f"Provider '{provider_id}' saved successfully."}

    async def _delete_user_provider(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Delete a user provider configuration"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        provider_id = args.get('provider_id')
        if not provider_id:
            raise HTTPException(status_code=400, detail="provider_id is required")
        
        from .database import get_database
        db = get_database()
        
        db.delete_user_provider(user_id, provider_id)
        
        return {"status": "success", "message": f"Provider '{provider_id}' deleted successfully."}

    async def _list_user_rotations(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """List all user-configured rotations"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        from .database import get_database
        db = get_database()
        
        rotations = db.get_user_rotations(user_id)
        rotations_info = {}
        
        for rotation in rotations:
            rotation_id = rotation['rotation_id']
            rotation_config = rotation['config']
            rotations_info[rotation_id] = {
                "model_name": rotation_config.get('model_name', rotation_id),
                "providers": rotation_config.get('providers', [])
            }
        
        return {"rotations": rotations_info}

    async def _get_user_rotation(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Get a specific user rotation configuration"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        rotation_id = args.get('rotation_id')
        if not rotation_id:
            raise HTTPException(status_code=400, detail="rotation_id is required")
        
        from .database import get_database
        db = get_database()
        
        rotation = db.get_user_rotation(user_id, rotation_id)
        if not rotation:
            raise HTTPException(status_code=404, detail=f"Rotation '{rotation_id}' not found")
        
        return {"rotation_id": rotation_id, "config": rotation['config']}

    async def _set_user_rotation(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Save a user rotation configuration"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        rotation_id = args.get('rotation_id')
        rotation_data = args.get('rotation_data')
        
        if not rotation_id or not rotation_data:
            raise HTTPException(status_code=400, detail="rotation_id and rotation_data are required")
        
        from .database import get_database
        db = get_database()
        
        db.save_user_rotation(user_id, rotation_id, rotation_data)
        
        return {"status": "success", "message": f"Rotation '{rotation_id}' saved successfully."}

    async def _delete_user_rotation(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Delete a user rotation configuration"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        rotation_id = args.get('rotation_id')
        if not rotation_id:
            raise HTTPException(status_code=400, detail="rotation_id is required")
        
        from .database import get_database
        db = get_database()
        
        db.delete_user_rotation(user_id, rotation_id)
        
        return {"status": "success", "message": f"Rotation '{rotation_id}' deleted successfully."}

    async def _list_user_autoselects(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """List all user-configured autoselects"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        from .database import get_database
        db = get_database()
        
        autoselects = db.get_user_autoselects(user_id)
        autoselects_info = {}
        
        for autoselect in autoselects:
            autoselect_id = autoselect['autoselect_id']
            autoselect_config = autoselect['config']
            autoselects_info[autoselect_id] = {
                "model_name": autoselect_config.get('model_name', autoselect_id),
                "description": autoselect_config.get('description', ''),
                "fallback": autoselect_config.get('fallback', ''),
                "available_models": autoselect_config.get('available_models', [])
            }
        
        return {"autoselects": autoselects_info}

    async def _get_user_autoselect(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Get a specific user autoselect configuration"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        autoselect_id = args.get('autoselect_id')
        if not autoselect_id:
            raise HTTPException(status_code=400, detail="autoselect_id is required")
        
        from .database import get_database
        db = get_database()
        
        autoselect = db.get_user_autoselect(user_id, autoselect_id)
        if not autoselect:
            raise HTTPException(status_code=404, detail=f"Autoselect '{autoselect_id}' not found")
        
        return {"autoselect_id": autoselect_id, "config": autoselect['config']}

    async def _set_user_autoselect(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Save a user autoselect configuration"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        autoselect_id = args.get('autoselect_id')
        autoselect_data = args.get('autoselect_data')
        
        if not autoselect_id or not autoselect_data:
            raise HTTPException(status_code=400, detail="autoselect_id and autoselect_data are required")
        
        from .database import get_database
        db = get_database()
        
        db.save_user_autoselect(user_id, autoselect_id, autoselect_data)
        
        return {"status": "success", "message": f"Autoselect '{autoselect_id}' saved successfully."}

    async def _delete_user_autoselect(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Delete a user autoselect configuration"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        autoselect_id = args.get('autoselect_id')
        if not autoselect_id:
            raise HTTPException(status_code=400, detail="autoselect_id is required")
        
        from .database import get_database
        db = get_database()
        
        db.delete_user_autoselect(user_id, autoselect_id)
        
        return {"status": "success", "message": f"Autoselect '{autoselect_id}' deleted successfully."}

    async def _user_chat_completion(self, args: Dict, user_id: Optional[int] = None) -> Dict:
        """Send a chat completion request using user's own configurations"""
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")
        
        model = args.get('model')
        messages = args.get('messages', [])
        temperature = args.get('temperature', 1.0)
        max_tokens = args.get('max_tokens', 2048)
        stream = args.get('stream', False)
        
        if not model:
            raise HTTPException(status_code=400, detail="model is required")
        
        # Parse model format: user-provider/id/model, user-rotation/id, user-autoselect/id
        if '/' in model:
            parts = model.split('/', 2)
            if len(parts) < 3:
                raise HTTPException(status_code=400, detail="Invalid model format. Use 'user-provider/id/model', 'user-rotation/id', or 'user-autoselect/id'")
            
            provider_type = parts[0]
            config_id = parts[1]
            actual_model = parts[2] if len(parts) > 2 else None
        else:
            raise HTTPException(status_code=400, detail="Invalid model format. Use 'user-provider/id/model', 'user-rotation/id', or 'user-autoselect/id'")
        
        # Create request data
        request_data = {
            "model": actual_model or config_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }
        
        # Route to appropriate handler
        from starlette.requests import Request
        from main import get_user_handler
        
        scope = {
            "type": "http",
            "method": "POST",
            "headers": [],
            "query_string": b"",
            "path": "/api/user/chat/completions"
        }
        dummy_request = Request(scope)
        
        if provider_type == "user-autoselect":
            handler = get_user_handler('autoselect', user_id)
            if config_id not in handler.user_autoselects:
                raise HTTPException(status_code=400, detail=f"User autoselect '{config_id}' not found")
            if stream:
                return {"error": "Streaming not supported in MCP, use SSE endpoint instead"}
            return await handler.handle_autoselect_request(config_id, request_data)
        
        elif provider_type == "user-rotation":
            handler = get_user_handler('rotation', user_id)
            if config_id not in handler.user_rotations:
                raise HTTPException(status_code=400, detail=f"User rotation '{config_id}' not found")
            return await handler.handle_rotation_request(config_id, request_data)
        
        elif provider_type == "user-provider":
            handler = get_user_handler('request', user_id)
            if config_id not in handler.user_providers:
                raise HTTPException(status_code=400, detail=f"User provider '{config_id}' not found")
            
            provider_config = handler.user_providers[config_id]
            if not validate_kiro_credentials(config_id, provider_config):
                raise HTTPException(status_code=403, detail=f"Provider '{config_id}' credentials not available")
            
            if stream:
                return {"error": "Streaming not supported in MCP, use SSE endpoint instead"}
            return await handler.handle_chat_completion(dummy_request, config_id, request_data)
        
        raise HTTPException(status_code=400, detail="Invalid model type. Use 'user-provider', 'user-rotation', or 'user-autoselect'")


# Global MCP server instance
mcp_server = MCPServer()
