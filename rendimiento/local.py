"""El panel de rendimiento en tu PC, sin Vercel: http://localhost:8001"""
import mimetypes
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "api"))
from index import handler  # noqa: E402

PUBLIC = (ROOT / "public").resolve()


class Local(handler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return super().do_GET()
        file = PUBLIC / "index.html" if path == "/" else (PUBLIC / path.lstrip("/")).resolve()
        if not file.is_relative_to(PUBLIC) or not file.is_file():
            return self.send_error(404)
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(file.name)[0] or "text/plain") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.environ.get("RENDIMIENTO_PORT", "8001"))
    print(f"Rendimiento: http://localhost:{port}/")
    ThreadingHTTPServer(("127.0.0.1", port), Local).serve_forever()
