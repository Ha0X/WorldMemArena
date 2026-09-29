"""Local HTTP/1.1 transport shim; forwards unchanged Responses JSON and SSE."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import requests
import socketserver


def start_proxy(log_path, request_audit_path=None, *, unix_socket=None, api_key=None):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != '/responses':
                self.send_error(404)
                return
            started = time.monotonic()
            status = None
            error = None
            try:
                data = self.rfile.read(int(self.headers['Content-Length']))
                if unix_socket is not None:
                    payload = json.loads(data)
                    if payload.get('model') != 'gpt-6-astra':
                        self.send_error(400, 'Unexpected evaluation model')
                        return
                if request_audit_path is not None:
                    payload = json.loads(data)
                    inputs = payload.get('input', [])
                    items = inputs if isinstance(inputs, list) else []
                    # Preserve actual custom tool exchanges; CLI JSONL may omit them.
                    audit = dict(model=payload.get('model'),
                                 previous_response_id=payload.get('previous_response_id'),
                                 input_count=len(items),
                                 tool_exchanges=[x for x in items if isinstance(x,dict) and x.get('type') in
                                                 ('custom_tool_call','custom_tool_call_output','function_call','function_call_output')])
                    with lock:
                        with request_audit_path.open('a') as f:
                            f.write(json.dumps(audit,ensure_ascii=False)+'\n')
                headers = {k:v for k,v in self.headers.items()
                           if k.lower() not in ('host','connection','content-length','accept-encoding')}
                if api_key is not None:
                    headers = {k:v for k,v in headers.items() if k.lower() != 'authorization'}
                    headers['Authorization'] = 'Bearer ' + api_key
                with requests.post('https://api.icodeeasy.cc/responses', data=data, headers=headers,
                                   stream=True, timeout=(20, 600)) as response:
                    status = response.status_code
                    self.send_response(status)
                    self.send_header('Content-Type',response.headers.get('Content-Type','text/event-stream'))
                    self.send_header('Connection','close')
                    self.end_headers()
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            self.wfile.write(chunk)
                            self.wfile.flush()
            except Exception as exc:
                error = type(exc).__name__
                if status is None:
                    self.send_error(502, error)
            finally:
                self.close_connection = True
                with lock:
                    with log_path.open('a') as f:
                        f.write(json.dumps(dict(status=status, error=error,
                                                seconds=round(time.monotonic()-started,2)))+'\n')

    if unix_socket is not None:
        if not api_key:
            raise ValueError('Isolated proxy requires an external API credential')
        class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
        server = UnixHTTPServer(str(unix_socket), Handler)
    else:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
