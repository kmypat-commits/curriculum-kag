import importlib.util
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen


def test_local_proxy_preserves_patch_body_and_upstream_status():
    spec = importlib.util.spec_from_file_location('frontend_proxy', Path(__file__).resolve().parents[2] / 'frontend_server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    class Upstream(BaseHTTPRequestHandler):
        def do_PATCH(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass
    upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    proxy = ThreadingHTTPServer(('127.0.0.1', 0), module.Handler)
    module.BACKEND = f'http://127.0.0.1:{upstream.server_port}'
    for server in (upstream, proxy):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urlopen(Request(f'http://127.0.0.1:{proxy.server_port}/api/projects/3/constraints',
                             data=b'{"mode":"shadow"}', method='PATCH')) as response:
            assert response.status == 200
            assert response.read() == b'{"mode":"shadow"}'
    finally:
        for server in (proxy, upstream): server.shutdown(); server.server_close()
