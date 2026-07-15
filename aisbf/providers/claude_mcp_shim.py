#!/usr/bin/env python3
"""
Copyleft (C) 2026 Stefy Lanza <stefy@nexlab.net>

AISBF - AI Service Broker Framework || AI Should Be Free

MCP stdio shim that exposes a caller's OpenAI/Anthropic tool definitions to the
claude CLI, so the model emits real tool_use blocks instead of describing tool
calls in prose.

The claude CLI's --tools flag only selects built-in tools by name; there is no
flag that registers arbitrary function definitions.  MCP is the only injection
point, so this server advertises the caller's tools via tools/list.

It never executes anything.  In the OpenAI protocol the *client* runs tools and
posts the results back on the next request, so the broker has no way to satisfy
a call mid-request.  The provider terminates the CLI as soon as it sees a
tool_use block and returns it to the client as tool_calls; tools/call is
therefore normally never reached.  It is implemented anyway (returning a
sentinel) so that a race — the CLI dispatching the call before we tear it down —
fails loudly in the transcript rather than hanging the subprocess.

Run as a standalone script; stdlib only, so it works under any interpreter the
CLI can spawn.  Tool definitions are read from the JSON file named by
AISBF_MCP_TOOLS_FILE.

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
"""
import json
import os
import sys

SERVER_NAME = 'aisbf'
DEFAULT_PROTOCOL_VERSION = '2024-11-05'
CALL_SENTINEL = (
    'AISBF: this tool is executed by the calling client, not here. '
    'The broker should have already returned this call to the client.'
)


def _log(message: str) -> None:
    sys.stderr.write(f'[aisbf-mcp-shim] {message}\n')
    sys.stderr.flush()


def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + '\n')
    sys.stdout.flush()


def _load_tools() -> list:
    """
    Load tool definitions and convert them to the MCP tools/list schema.

    Accepts Anthropic-style (input_schema) or MCP-style (inputSchema) entries.
    """
    path = os.environ.get('AISBF_MCP_TOOLS_FILE', '')
    if not path:
        _log('AISBF_MCP_TOOLS_FILE not set; serving no tools')
        return []
    try:
        with open(path, 'r') as fh:
            raw = json.load(fh)
    except Exception as exc:
        _log(f'failed to read {path}: {exc}')
        return []

    tools = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        name = entry.get('name')
        if not name:
            continue
        schema = entry.get('inputSchema') or entry.get('input_schema') or {}
        # MCP requires an object schema; a bare/empty schema is rejected by
        # some clients, so normalise to a valid empty object schema.
        if not isinstance(schema, dict) or schema.get('type') != 'object':
            schema = {'type': 'object', 'properties': {}}
        tools.append({
            'name': name,
            'description': entry.get('description', '') or '',
            'inputSchema': schema,
        })
    _log(f'serving {len(tools)} tool(s): {[t["name"] for t in tools]}')
    return tools


def main() -> None:
    tools = _load_tools()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get('method')
        req_id = req.get('id')

        # Notifications carry no id and require no response.
        if req_id is None:
            continue

        if method == 'initialize':
            params = req.get('params') or {}
            protocol = params.get('protocolVersion') or DEFAULT_PROTOCOL_VERSION
            _send({'jsonrpc': '2.0', 'id': req_id, 'result': {
                'protocolVersion': protocol,
                'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': {'name': SERVER_NAME, 'version': '1.0.0'},
            }})
        elif method == 'tools/list':
            _send({'jsonrpc': '2.0', 'id': req_id,
                   'result': {'tools': tools}})
        elif method == 'tools/call':
            params = req.get('params') or {}
            _log(f'unexpected tools/call for {params.get("name")!r} '
                 f'- broker should have terminated the turn first')
            _send({'jsonrpc': '2.0', 'id': req_id, 'result': {
                'content': [{'type': 'text', 'text': CALL_SENTINEL}],
                'isError': True,
            }})
        elif method == 'ping':
            _send({'jsonrpc': '2.0', 'id': req_id, 'result': {}})
        else:
            _send({'jsonrpc': '2.0', 'id': req_id, 'error': {
                'code': -32601, 'message': f'method not found: {method}',
            }})


if __name__ == '__main__':
    main()
