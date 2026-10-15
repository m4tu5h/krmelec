"""Serve only the web folder and menus.json; keep project secrets out of the web root."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/menus.json":
            try:
                content = (ROOT / "menus.json").read_bytes()
            except FileNotFoundError:
                self.send_error(404, "Run the notebook save cell to create menus.json")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        super().do_GET()

    def list_directory(self, path):
        self.send_error(404)
        return None


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), partial(Handler, directory=str(ROOT / "web")))
    print("Krmelec: http://127.0.0.1:8000 — Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
