"""Minimal stdio MCP server exposing only one controlled JSON memory artifact."""
import argparse
import json
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--memory', required=True)
    p.add_argument('--read-only', action='store_true')
    args = p.parse_args()
    path = Path(args.memory)
    tools = [{'name': 'read_memory', 'description': 'Read your persisted memory from previous sessions.',
              'annotations': {'readOnlyHint': True, 'openWorldHint': False},
              'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}]
    if not args.read_only:
        tools.append({'name': 'write_memory', 'description': 'Replace persisted memory with valid JSON. You choose the structure and content. Preserve useful prior knowledge.',
                      'annotations': {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False},
                      'inputSchema': {'type': 'object', 'properties': {'json_text': {'type': 'string'}},
                                      'required': ['json_text'], 'additionalProperties': False}})
    for line in sys.stdin:
        request = json.loads(line)
        if 'id' not in request:
            continue
        method = request.get('method')
        if method == 'initialize':
            result = {'protocolVersion': request['params']['protocolVersion'], 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'worldmem-controlled-memory', 'version': '1.0'}}
        elif method == 'tools/list':
            result = {'tools': tools}
        elif method == 'tools/call':
            params = request['params']
            try:
                if params['name'] == 'read_memory':
                    output = path.read_text() if path.exists() else '{}'
                elif params['name'] == 'write_memory' and not args.read_only:
                    value = json.loads(params['arguments']['json_text'])
                    output = json.dumps(value, ensure_ascii=False, indent=2)
                    if len(output.encode()) > 262144:
                        raise ValueError('Memory exceeds the declared 256 KiB limit')
                    temp = path.with_suffix('.tmp')
                    temp.write_text(output + '\n')
                    temp.replace(path)
                    output = 'Memory saved.'
                else:
                    raise ValueError('Tool is unavailable')
                result = {'content': [{'type': 'text', 'text': output}]}
            except (ValueError, KeyError, OSError) as exc:
                result = {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
        elif method == 'ping':
            result = {}
        else:
            print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32601, 'message': 'Method not found'}}), flush=True)
            continue
        print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)


if __name__ == '__main__':
    main()
