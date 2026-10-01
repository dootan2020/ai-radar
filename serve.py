"""Serve the local dashboard at http://localhost:8790 (Ctrl+C to stop)."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket


class LocalServer(ThreadingHTTPServer):
    # HTTPServer enables SO_REUSEADDR, which permits a second Windows listener
    # to bind the same endpoint. Claim the port exclusively instead.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def main():
    site = Path(__file__).resolve().parent / "site"
    handler = partial(Handler, directory=str(site))
    try:
        server = LocalServer(("127.0.0.1", 8790), handler)
    except OSError as error:
        raise SystemExit(f"Cannot serve localhost:8790: {error}") from error
    print("AI Radar: http://localhost:8790 — Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
