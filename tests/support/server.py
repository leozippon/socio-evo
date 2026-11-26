"""A model server on localhost that speaks the part of vLLM's API that adapters use: the models
listed (`GET /v1/models`), runtime LoRA loading and unloading, and chat completions that name a
model. It answers as vLLM 0.32 does where the adapters' code depends on it, keeps what it was
asked, and runs in a thread for the duration of a `with` block."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

KEY = "SOCIO_EVO_TEST_SERVER_KEY"
"""The environment variable whose value the server takes as its API key."""


class FakeServer:
    """The server of `base`, with API key `key`; `loaded` maps each adapter loaded to its
    directory, and `calls` keeps every request as (method, path, body, data-parallel rank). With
    `refuse` set, it refuses to load any adapter."""

    def __init__(self, base: str = "served", key: str = "secret") -> None:
        self.base, self.key = base, key
        self.loaded: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict[str, Any], str | None]] = []
        self.refuse = False
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._http.server_address[1]}/v1"

    def __enter__(self) -> FakeServer:
        threading.Thread(target=self._http.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.shutdown()
        self._http.server_close()

    def answer(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        if method == "GET" and path == "/v1/models":
            models = [{"id": self.base, "root": self.base, "parent": None}]
            models += [{"id": n, "root": p, "parent": self.base} for n, p in self.loaded.items()]
            return 200, {"object": "list", "data": models}
        if path == "/v1/load_lora_adapter":
            name, root = body["lora_name"], body["lora_path"]
            if name in self.loaded:
                return 400, f"The lora adapter '{name}' has already been loaded."
            if self.refuse or not (Path(root) / "adapter_config.json").is_file():
                return 404, f"No adapter found for {root}."
            self.loaded[name] = root
            return 200, f"Success: LoRA adapter '{name}' added successfully."
        if path == "/v1/unload_lora_adapter":
            if self.loaded.pop(body["lora_name"], None) is None:
                return 404, f"The lora adapter '{body['lora_name']}' cannot be found."
            return 200, f"Success: LoRA adapter '{body['lora_name']}' removed successfully."
        if path == "/v1/chat/completions":
            if body["model"] != self.base and body["model"] not in self.loaded:
                return 404, {"error": {"message": f"The model `{body['model']}` does not exist."}}
            choice = {"index": 0, "finish_reason": "length", "message": {"content": "Y"}}
            return 200, {"id": "x", "object": "chat.completion", "choices": [choice]}
        return 404, "Not Found"

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._serve("GET")

            def do_POST(self) -> None:
                self._serve("POST")

            def _serve(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else {}
                rank = self.headers.get("X-data-parallel-rank")
                server.calls.append((method, self.path, body, rank))
                if self.headers.get("Authorization") != f"Bearer {server.key}":
                    status, answer = 401, {"error": "Unauthorized"}
                else:
                    status, answer = server.answer(method, self.path, body)
                text = answer if isinstance(answer, str) else json.dumps(answer)
                data = text.encode()
                self.send_response(status)
                self.send_header(
                    "Content-Type", "text/plain" if isinstance(answer, str) else "application/json"
                )
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: object) -> None:
                pass

        return Handler
