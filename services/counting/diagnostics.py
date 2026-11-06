"""Последний размеченный кадр из памяти счётчика для локального API (ADR-0029)."""
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def start_preview_server(engine, token, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.connection.settimeout(2)
            if not secrets.compare_digest(self.headers.get("Authorization", "").encode(),
                                          f"Bearer {token}".encode()):
                self.send_error(403)
                return
            parts = self.path.strip("/").split("/")
            cam = engine.get(parts[0]) if len(parts) == 3 else None
            if cam is not None:
                settings = cam.cfg["settings"]
                if (parts[1:] == [str(settings["version"]), str(settings.get("connection_version", 0))]
                        and time.time() - cam.preview_t < 3 and cam.preview):
                    frame = cam.preview
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(frame)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(frame)
                    return
            self.send_error(503)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
