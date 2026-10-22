"""Development HTTPS material must pass normal, strict certificate verification."""

import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from election.dev import tls_dev


def test_generated_development_certificate_passes_strict_tls_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    tls_dev()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"TLS verified")

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(".runtime/tls/server.pem", ".runtime/tls/server-key.pem")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        verified = ssl.create_default_context(cafile=".runtime/tls/ca.pem")
        response = httpx.get(f"https://localhost:{server.server_port}", verify=verified)
        assert response.status_code == 200
        assert response.text == "TLS verified"
        with pytest.raises(SystemExit, match="already exist"):
            tls_dev()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
