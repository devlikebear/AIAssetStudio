"""Stands in for packs/assets/tts_server.py: the same HTTP contract, no model. FAKE_TTS_EXIT makes it die at once."""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def _answer(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._answer({"ready": True})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._answer({"duration_s": 1.0, "sample_rate": 24000, "spoke": body["text"]})

    def log_message(self, *args):
        pass


def end_with_parent() -> None:
    sys.stdin.buffer.read()
    os._exit(0)


if __name__ == "__main__":
    if os.environ.get("FAKE_TTS_EXIT"):
        sys.exit(1)
    threading.Thread(target=end_with_parent, daemon=True).start()
    HTTPServer(("127.0.0.1", int(sys.argv[sys.argv.index("--port") + 1])), Handler).serve_forever()
