"""Local-only browser proof: python tests/serve-reader-failures.py.

Routes: /healthy/, /empty/, /missing-app/, /missing-module/, /stalled-request/,
/stalled-body/, /stalled-compact/. Success uses the captured real v2 fixture.
No production files or external data are changed. Stop with Ctrl+C.
"""

from functools import partial
from http.server import SimpleHTTPRequestHandler
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from serve import LocalServer

CASES = {'healthy', 'empty', 'missing-app', 'missing-module', 'stalled-request',
         'stalled-body', 'stalled-compact'}
FIXTURE = ROOT / 'tests/fixtures/edition-real-snapshot.json'


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_GET(self):
        parts = urlsplit(self.path).path.lstrip('/').split('/', 1)
        case = parts[0]
        if case not in CASES:
            self.send_error(404, 'Choose a reader test route')
            return
        asset = parts[1] if len(parts) == 2 else ''
        if ((case == 'missing-app' and asset == 'app.js') or
                (case == 'missing-module' and asset == 'snapshot.js')):
            self.send_error(404, 'Deliberately missing module')
            return
        if asset in {'data/radar-ui.json', 'data/radar.json'}:
            stalled = case in {'stalled-request', 'stalled-body'} or (
                case == 'stalled-compact' and asset.endswith('radar-ui.json'))
            if stalled and case != 'stalled-body':
                time.sleep(30)
                return
            data = json.loads(FIXTURE.read_text(encoding='utf-8'))
            if case == 'empty':
                data.update(stories=[], sections={}, sources=[], repos=[])
            payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            try:
                if stalled:
                    self.wfile.write(payload[:1])
                    self.wfile.flush()
                    time.sleep(30)
                else:
                    self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self.path = '/' + (asset or 'index.html')
        super().do_GET()


if __name__ == '__main__':
    handler = partial(Handler, directory=str(ROOT / 'site'))
    with LocalServer(('127.0.0.1', 8790), handler) as server:
        print('Reader proof: http://127.0.0.1:8790/healthy/ — Ctrl+C to stop', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
