"""Opt-in real browser regression with isolated TLS, credentials and session state."""

import base64
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import threading
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from ops.webui.gateway import Config, Gateway, Response, hash_password

PROJECT = Path(__file__).parents[2]


def test_native_https_login_and_logout(tmp_path):
    chromium = os.environ.get("CHROMIUM", "")
    if not chromium:
        pytest.skip("opt in with CHROMIUM=/absolute/path/to/existing/chrome")
    assert Path(chromium).is_file(), "CHROMIUM must point to an existing executable"
    assert shutil.which("node") and shutil.which("openssl"), "Node.js and OpenSSL required"
    helper = PROJECT / "tests/frontend/native_form_check.mjs"
    source = helper.read_text()
    assert "--remote-debugging-pipe" in source and "--remote-debugging-port" not in source
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True, capture_output=True, timeout=10,
    )
    public = subprocess.run(
        ["openssl", "x509", "-in", str(cert), "-pubkey", "-noout"],
        check=True, capture_output=True, timeout=5,
    ).stdout
    der = subprocess.run(
        ["openssl", "pkey", "-pubin", "-outform", "DER"], input=public,
        check=True, capture_output=True, timeout=5,
    ).stdout
    spki = base64.b64encode(hashlib.sha256(der).digest()).decode()

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, format, *args):
            pass

    edge = (PROJECT / "ops/webui/nginx-security.conf").read_text()
    policy = next(line.split()[2] for line in edge.splitlines()
                  if line.startswith("add_header Referrer-Policy "))

    def application(environ, start_response):
        def edge_response(status, headers):
            return start_response(status, [*headers, ("Referrer-Policy", policy)])

        if environ["PATH_INFO"] == "/":
            valid = gateway.sessions.valid(gateway.cookie(environ, gateway.config.cookie_name))
            response = Response(200, "Protected fixture") if valid else Response(
                303, headers=(("Location", "/_auth/login"),)
            )
            edge_response(f"{response.status} Test", list(response.headers))
            return [response.body.encode()]
        return gateway(environ, edge_response)

    # TCP/TLS exists only in this isolated test fixture; production remains Unix-socket-only.
    server = make_server("127.0.0.1", 0, application, handler_class=QuietHandler)
    origin = f"https://127.0.0.1:{server.server_port}"
    password = "isolated-browser-test-password"
    gateway = Gateway(Config(
        "socio-evo", origin, "browser-test", hash_password(password), "s" * 64,
        tmp_path / "state",
    ))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = dict(os.environ, WEBUI_BROWSER_SPKI=spki)
        env.pop("WEBUI_BROWSER_PROXY", None)
        result = subprocess.run(
            ["node", str(helper), f"socio-evo={origin}"],
            input=json.dumps({"socio-evo": {"username": "browser-test", "password": password}}),
            capture_output=True, text=True, timeout=75, env=env,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "native login 200, logout confirmation and revocation passed" in result.stdout
        assert password not in result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
