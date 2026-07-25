"""Serve the production frontend and proxy local API requests."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import Request, urlopen
import mimetypes


DIST = Path(__file__).resolve().parent / ".runtime" / "dist"
BACKEND = "http://127.0.0.1:8000"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        return

    def _send_bytes(self, status: int, body: bytes, content_type: str, cache_control: str = "no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)

    def _static_path(self) -> Path:
        clean = unquote(self.path.split("?", 1)[0]).lstrip("/")
        candidate = (DIST / clean).resolve()
        root = DIST.resolve()
        if not clean or not str(candidate).startswith(str(root)) or not candidate.exists() or candidate.is_dir():
            candidate = root / "index.html"
        return candidate

    def _serve_static(self):
        try:
            path = self._static_path()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix.lower() in {".html", ".js", ".css", ".json", ".txt"}:
                content_type = content_type.split(";")[0] + "; charset=utf-8"
            cache_control = (
                "public, max-age=31536000, immutable"
                if "assets" in path.parts else "no-cache"
            )
            self._send_bytes(200, path.read_bytes(), content_type, cache_control)
        except Exception as exc:
            self._send_bytes(500, f"Ошибка интерфейса: {exc}".encode(), "text/plain; charset=utf-8")

    def _proxy(self):
        target = BACKEND + self.path[4:]
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        headers = {key: value for key, value in self.headers.items() if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}}
        timeout = 900 if self.path.startswith("/api/planner/") and self.path.endswith("/build") else 120
        try:
            response = urlopen(Request(target, data=body, headers=headers, method=self.command), timeout=timeout)
            payload = response.read()
            self.send_response(response.status)
            for key, value in response.headers.items():
                if key.lower() not in {"transfer-encoding", "connection", "content-length"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers(); self.wfile.write(payload)
        except HTTPError as exc:
            payload = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json; charset=utf-8"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers(); self.wfile.write(payload)
        except URLError as exc:
            self._send_bytes(502, f"Backend недоступен: {exc}".encode(), "text/plain; charset=utf-8")
        except Exception as exc:
            self._send_bytes(500, f"Ошибка прокси: {exc}".encode(), "text/plain; charset=utf-8")

    do_GET = lambda self: self._proxy() if self.path.startswith("/api/") else self._serve_static()
    do_HEAD = do_GET
    do_POST = lambda self: self._proxy()
    do_PUT = do_POST
    do_DELETE = do_POST


ThreadingHTTPServer(("127.0.0.1", 3001), Handler).serve_forever()
