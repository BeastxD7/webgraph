"""Tiny sink for manually-collected browser oracle data.

The browser POSTs one JSON record per site here. Keeping the payload out of the agent's
context is the entire point: 100 sites x ~100 links each is far too much to read back
through a tool result, and none of it needs to be read -- only compared.

Permissive CORS because the request originates from whatever page is being measured.
Bound to loopback only.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OUT = Path(__file__).parent / "oracle.jsonl"


class Handler(BaseHTTPRequestHandler):
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        raw = self.rfile.read(length)
        try:
            record = json.loads(raw)
            record["collected_at"] = datetime.now(UTC).isoformat()
            with OUT.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            body = json.dumps({"ok": True, "site": record.get("u"), "links": record.get("n")})
        except Exception as exc:  # noqa: BLE001
            body = json.dumps({"ok": False, "error": str(exc)})
        self.send_response(200)
        self._cors()
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args: object) -> None:
        return


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"collector on :{port} -> {OUT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
