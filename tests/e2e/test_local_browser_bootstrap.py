"""The native splash must carry the private browser bootstrap credential."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect


def test_splash_passes_bootstrap_credential_to_local_server(page, tmp_path):
    requests = []

    class BootstrapHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get("Cookie", "")))
            if self.path == "/?bootstrap=example-token":
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header(
                    "Set-Cookie", "test-session=bound; HttpOnly; SameSite=Lax; Path=/"
                )
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<p>ready</p>")

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), BootstrapHandler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        source = (Path(__file__).resolve().parents[2] / "splash.html").read_text(
            encoding="utf-8"
        )
        splash = tmp_path / "splash.html"
        splash.write_text(
            source.replace("127.0.0.1:5000", f"127.0.0.1:{port}"), encoding="utf-8"
        )
        page.goto(f"{splash.as_uri()}#bootstrap=example-token")
        page.wait_for_url(f"http://127.0.0.1:{port}/", timeout=7000)

        expect(page.locator("p")).to_have_text("ready")
        assert requests == [
            ("/?bootstrap=example-token", ""),
            ("/", "test-session=bound"),
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
