"""Simple dev server: serves frontend + proxies API calls to uvicorn.

Usage: python3 serve.py
Then open http://localhost:8080
Requires uvicorn running separately: uvicorn api.main:app --port 8000
"""
import http.server
import urllib.request
import json
from pathlib import Path

PORT = 8080
FRONTEND = Path(__file__).parent / "frontend" / "index.html"
API_BACKEND = "http://localhost:8000"


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/"):
            self._proxy()
        else:
            self._serve_frontend()

    def _serve_frontend(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(FRONTEND.read_bytes())

    def _proxy(self):
        url = API_BACKEND + self.path
        try:
            with urllib.request.urlopen(url) as resp:
                body = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"feil": str(e)}).encode())

    def log_message(self, format, *args):
        pass  # quiet


if __name__ == "__main__":
    print(f"Serving on http://localhost:{PORT}")
    print(f"Proxying API to {API_BACKEND}")
    http.server.HTTPServer(("", PORT), Handler).serve_forever()
