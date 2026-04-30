from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from aisbf.mcp import mcp_server, MCPAuthLevel, load_mcp_config
import json, logging
from aisbf.database import DatabaseRegistry

router = APIRouter()
_server_config = None
_get_user_handler = None

def init(server_config_ref, get_user_handler_fn):
    global _server_config, _get_user_handler
    _server_config = server_config_ref
    _get_user_handler = get_user_handler_fn

logger = logging.getLogger(__name__)

def get_mcp_auth_level(request: Request) -> int:
    mcp_config = load_mcp_config()
    if not mcp_config.get('enabled', False):
        if _server_config and _server_config.get('auth_enabled', False):
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                token = auth_header.replace('Bearer ', '')
                if token in _server_config.get('auth_tokens', []):
                    return MCPAuthLevel.FULLCONFIG
        return MCPAuthLevel.NONE
    fullconfig_tokens = mcp_config.get('fullconfig_tokens', [])
    autoselect_tokens = mcp_config.get('autoselect_tokens', [])
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return MCPAuthLevel.NONE
    token = auth_header.replace('Bearer ', '')
    if token in fullconfig_tokens:
        return MCPAuthLevel.FULLCONFIG
    if token in autoselect_tokens:
        return MCPAuthLevel.AUTOSELECT
    return MCPAuthLevel.NONE

@router.get("/mcp")
async def mcp_sse(request: Request):
    auth_level = get_mcp_auth_level(request)
    if auth_level == MCPAuthLevel.NONE:
        return JSONResponse(status_code=401, content={"error": "Invalid or missing MCP authentication token"})

    async def event_generator():
        yield f"data: {json.dumps({'event': 'connected', 'auth_level': auth_level})}\n\n".encode('utf-8')
        request_text = ""
        try:
            body = await request._receive()
            if body and isinstance(body, bytes):
                request_text = body.decode('utf-8')
            elif body and isinstance(body, dict):
                request_text = json.dumps(body)
        except Exception as e:
            logger.warning(f"Error reading MCP request body: {e}")
        if not request_text:
            request_text = request.query_params.get('request', '{}')
        try:
            mcp_request = json.loads(request_text) if request_text else {}
        except json.JSONDecodeError:
            yield f"data: {json.dumps({'error': 'Invalid JSON request'})}\n\n".encode('utf-8')
            return
        method = mcp_request.get('method', '')
        request_id = mcp_request.get('id')
        params = mcp_request.get('params', {})
        if method == 'initialize':
            response = {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": True}, "resources": {"subscribe": True, "listChanged": True}}, "serverInfo": {"name": "AISBF MCP Server", "version": "1.0.0"}}}
            yield f"data: {json.dumps(response)}\n\n".encode('utf-8')
        elif method == 'tools/list':
            user_id = getattr(request.state, 'user_id', None)
            tools = mcp_server.get_available_tools(auth_level, user_id)
            yield f"data: {json.dumps({'jsonrpc': '2.0', 'id': request_id, 'result': {'tools': tools}})}\n\n".encode('utf-8')
        elif method == 'tools/call':
            tool_name = params.get('name')
            arguments = params.get('arguments', {})
            if not tool_name:
                yield f"data: {json.dumps({'error': 'Tool name is required'})}\n\n".encode('utf-8')
                return
            try:
                user_id = getattr(request.state, 'user_id', None)
                result = await mcp_server.handle_tool_call(tool_name, arguments, auth_level, user_id)
                yield f"data: {json.dumps({'jsonrpc': '2.0', 'id': request_id, 'result': result})}\n\n".encode('utf-8')
            except Exception as e:
                yield f"data: {json.dumps({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32603, 'message': str(e)}})}\n\n".encode('utf-8')
        yield f"data: {json.dumps({'event': 'done'})}\n\n".encode('utf-8')

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/mcp")
async def mcp_post(request: Request):
    auth_level = get_mcp_auth_level(request)
    if auth_level == MCPAuthLevel.NONE:
        return JSONResponse(status_code=401, content={"error": "Invalid or missing MCP authentication token"})
    try:
        body = await request.body()
        mcp_request = json.loads(body.decode('utf-8')) if body else {}
    except json.JSONDecodeError:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON request body"})
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid request body"})
    method = mcp_request.get('method', '')
    request_id = mcp_request.get('id')
    params = mcp_request.get('params', {})
    if method == 'initialize':
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {"listChanged": True}, "resources": {"subscribe": True, "listChanged": True}}, "serverInfo": {"name": "AISBF MCP Server", "version": "1.0.0"}}}
    elif method == 'tools/list':
        user_id = getattr(request.state, 'user_id', None)
        tools = mcp_server.get_available_tools(auth_level, user_id)
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
    elif method == 'tools/call':
        tool_name = params.get('name')
        arguments = params.get('arguments', {})
        if not tool_name:
            return JSONResponse(status_code=400, content={"error": "Tool name is required"})
        try:
            user_id = getattr(request.state, 'user_id', None)
            result = await mcp_server.handle_tool_call(tool_name, arguments, auth_level, user_id)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(e)}}
    return JSONResponse(status_code=400, content={"error": "Unknown MCP method"})

@router.get("/mcp/u/{username}/tools")
async def mcp_user_list_tools(request: Request, username: str):
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})
    if not is_global_token and not is_admin:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(status_code=403, content={"error": "Access denied. Username in URL must match authenticated user."})
    tools = mcp_server.get_available_tools(MCPAuthLevel.USER, user_id)
    return {"tools": tools}

@router.post("/mcp/u/{username}/tools/call")
async def mcp_user_call_tool(request: Request, username: str):
    user_id = getattr(request.state, 'user_id', None)
    is_admin = getattr(request.state, 'is_admin', False)
    is_global_token = getattr(request.state, 'is_global_token', False)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})
    if not is_global_token and not is_admin:
        db = DatabaseRegistry.get_config_database()
        authenticated_user = db.get_user_by_id(user_id)
        if authenticated_user and authenticated_user['username'] != username:
            return JSONResponse(status_code=403, content={"error": "Access denied. Username in URL must match authenticated user."})
    try:
        body = await request.body()
        body_data = json.loads(body.decode('utf-8')) if body else {}
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON request body"})
    tool_name = body_data.get('name')
    arguments = body_data.get('arguments', {})
    if not tool_name:
        return JSONResponse(status_code=400, content={"error": "Tool name is required"})
    try:
        result = await mcp_server.handle_tool_call(tool_name, arguments, MCPAuthLevel.USER, user_id)
        return {"result": result}
    except Exception as e:
        logger.error(f"Error calling MCP tool: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/mcp/tools")
async def mcp_list_tools(request: Request):
    auth_level = get_mcp_auth_level(request)
    if auth_level == MCPAuthLevel.NONE:
        return JSONResponse(status_code=401, content={"error": "Invalid or missing MCP authentication token"})
    user_id = getattr(request.state, 'user_id', None)
    tools = mcp_server.get_available_tools(auth_level, user_id)
    return {"tools": tools}

@router.post("/mcp/tools/call")
async def mcp_call_tool(request: Request):
    auth_level = get_mcp_auth_level(request)
    if auth_level == MCPAuthLevel.NONE:
        return JSONResponse(status_code=401, content={"error": "Invalid or missing MCP authentication token"})
    try:
        body = await request.body()
        body_data = json.loads(body.decode('utf-8')) if body else {}
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON request body"})
    tool_name = body_data.get('name')
    arguments = body_data.get('arguments', {})
    if not tool_name:
        return JSONResponse(status_code=400, content={"error": "Tool name is required"})
    try:
        user_id = getattr(request.state, 'user_id', None)
        result = await mcp_server.handle_tool_call(tool_name, arguments, auth_level, user_id)
        return {"result": result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
