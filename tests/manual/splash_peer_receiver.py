"""Loopback-only hash witness for an independent Splash offer hook.

This records inbound hook evidence without retaining signed offer text. It is
not a Splash node and does not prove peer identity by itself. Correlate the
receipt with the separate node's identity/peer log and the maker's offer hash.
"""

import argparse
import hashlib
import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


MAX_BODY_BYTES = 512 * 1024
MAX_OFFER_BYTES = 300 * 1024


def make_server(port: int, output: Path) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/offer":
                self.reply(404, {"ok": False})
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                self.reply(413, {"ok": False})
                return
            try:
                body = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.reply(400, {"ok": False})
                return
            if type(body) is not dict or set(body) != {"offer"}:
                self.reply(400, {"ok": False})
                return
            offer = body["offer"]
            if type(offer) is not str or not offer.startswith("offer1"):
                self.reply(400, {"ok": False})
                return
            raw = offer.encode("utf-8")
            if len(raw) > MAX_OFFER_BYTES:
                self.reply(413, {"ok": False})
                return
            record = {
                "kind": "offer_hook_receipt",
                "received_at_utc": datetime.now(timezone.utc).isoformat(),
                "offer_sha256": hashlib.sha256(raw).hexdigest(),
                "offer_utf8_bytes": len(raw),
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.reply(200, {"ok": True})

        def reply(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args) -> None:
            return  # Avoid request logging, especially a future malformed URL.

    return HTTPServer(("127.0.0.1", port), Handler)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "receipts.jsonl"
        server = make_server(0, output)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            offer = "offer1synthetic-hook-probe"
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/offer",
                data=json.dumps({"offer": offer}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 200
            invalid = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/offer",
                data=b'{"offer":"not-an-offer"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(invalid, timeout=5)
                raise AssertionError("invalid offer was accepted")
            except urllib.error.HTTPError as error:
                assert error.code == 400
            records = [json.loads(line) for line in output.read_text().splitlines()]
            assert len(records) == 1
            assert (
                records[0]["offer_sha256"]
                == hashlib.sha256(offer.encode("utf-8")).hexdigest()
            )
            assert records[0]["offer_utf8_bytes"] == len(offer.encode("utf-8"))
            assert "offer" not in records[0]
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
    print("receiver hook synthetic self-test passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=14020)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not 1 <= args.port <= 65535 or args.output is None:
        parser.error("live mode requires --output and a valid --port")
    server = make_server(args.port, args.output)
    print(f"Loopback offer hook ready on 127.0.0.1:{server.server_port}/offer")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
