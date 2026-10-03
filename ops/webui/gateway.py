#!/usr/bin/env python3
"""Shared, Unix-socket-only authentication for the two private-CA HTTPS WebUIs.

Run: python gateway.py --config /etc/webui/SERVICE/auth.json \
    --socket /run/webui-SERVICE/auth.sock
Install the adjacent requirements.txt in the serving Python environment first.

Trusted edge contract: nginx alone may reach the socket. Make /_auth/check an
internal auth_request location, forwarding Cookie and overwriting
X-Original-Method with the *parent* request method and X-Original-Origin with
its browser Origin (empty when absent). Never forward client-provided versions
of those headers. Proxy login/logout with the browser Origin unchanged. The
check grants unsafe requests only with an exact configured Origin; no Referer
fallback or identity header is accepted. Terminate TLS at nginx with the
private CA certificate trusted by clients, and add Cache-Control: no-store
always there too (including HTTP parser errors outside the WSGI application).

Systemd owns socket-parent permissions and the private StateDirectory; the
socket is 0660, group nginx by default. A non-root daemon should run with that
group and have a private readable config and an owned 0700 state directory.
Only login attempts are rate limited here, globally, to ten per minute; nginx
should additionally rate limit by client IP. No request/credential logging.

Provision *separately* for each service, as root (no secret arguments/output):
  python gateway.py --provision --config /etc/webui/SERVICE/auth.json \
    --service SERVICE --origin https://8.133.175.124:PORT \
    --state-dir /var/lib/webui/SERVICE \
    --credentials-file /root/SERVICE-webui-credentials.json
Parent directories must already exist. Both output files are exclusively
created, 0600, and root-owned. Never deploy the generated credentials file to
the WebUI. If using a dedicated daemon account, transfer ownership of only
its auth config to that account, retaining 0600. Changing the session secret,
password hash, username, service or origin invalidates existing sessions.
"""

from __future__ import annotations

import argparse
import base64
import errno
import grp
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import sqlite3
import stat
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

SERVICES = {"cornerhead", "socio-evo"}
SESSION_DAYS = 30
CSRF_SECONDS = 600
MAX_BODY_BYTES = 4096
MAX_COOKIE_BYTES = 8192
SCRYPT_N, SCRYPT_R, SCRYPT_P = 32768, 8, 3
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}\Z")
CSRF_RE = re.compile(r"([A-Za-z0-9_-]{43})\.([0-9]{1,12})\.([0-9a-f]{64})\Z")
USERNAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
HASH_RE = re.compile(r"scrypt\$32768\$8\$3\$([0-9a-f]{32})\$([0-9a-f]{64})\Z")
METHOD_RE = re.compile(r"[A-Z]{1,32}\Z")

# Static presentation follows each application's own tokens and original brand mark.
# Only layout is shared; CSP hashes the exact combined stylesheet for that service.
LAYOUT_CSS = """
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; font-synthesis: none; }
body {
  margin: 0;
  min-height: 100vh;
  min-height: 100svh;
  display: grid;
  place-items: center;
  padding: 24px 16px;
}
.shell { width: 100%; min-width: 0; }
.card { overflow-wrap: anywhere; }
.brand { display: flex; align-items: center; }
.brand-mark { display: block; flex: none; }
h1 { margin: 24px 0 20px; line-height: 1.25; }
p { margin: 0; }
.description { margin-bottom: 20px; }
form, .field { display: grid; }
.field { gap: 6px; }
input:not([type="hidden"]) {
  width: 100%;
  min-width: 0;
  min-height: 44px;
  font: inherit;
  font-size: 16px;
}
button, .button-link {
  display: block;
  appearance: none;
  width: 100%;
  min-height: 44px;
  font: inherit;
  text-align: center;
  text-decoration: none;
  cursor: pointer;
  box-shadow: none;
}
.error { margin: 0 0 20px; padding: 12px; }
.error-code { display: block; margin-bottom: 4px; font-size: 12px; font-weight: 650; }
@media (max-width: 480px) {
  .shell .card { padding: 24px 20px; }
}
"""

CORNERHEAD_CSS = """
:root {
  color-scheme: light;
  --bg: #f3f5f9;
  --panel: #ffffff;
  --border: #dfe4ea;
  --text: #1c212c;
  --muted: #68717f;
  --accent: #2456c4;
  --accent-soft: #e8eefc;
  --input-bg: #f2f4f8;
  --input-border: #cdd4de;
  --bad: #bd3131;
  --bad-soft: #fbe7e7;
  --danger-border: #e5b8b8;
  --shadow: 0 1px 3px rgba(24, 34, 56, 0.08);
  font-size: clamp(14px, 12px + 0.22vw, 17.5px);
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --bg: #12151c;
    --panel: #1b1f28;
    --border: #2c323e;
    --text: #e4e8ef;
    --muted: #9aa2b1;
    --accent: #3987e5;
    --accent-soft: #1d2b45;
    --input-bg: #13161d;
    --input-border: #3a4150;
    --bad: #e06c6c;
    --bad-soft: #3a1c1c;
    --danger-border: #6d3a3a;
    --shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  }
}
body {
  background: var(--bg);
  color: var(--text);
  font: 1rem/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}
.shell { max-width: 400px; }
.card {
  padding: 28px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow);
}
.brand { gap: .55rem; font-size: 1.12rem; font-weight: 750; letter-spacing: .01em; }
.brand-mark { width: 1.7rem; height: 1.7rem; }
h1 { font-size: 1.19rem; font-weight: 700; }
.description { color: var(--muted); }
form { gap: 16px; }
label { font-size: .905rem; font-weight: 600; }
input:not([type="hidden"]) {
  padding: .5rem .7rem;
  border: 1px solid var(--input-border);
  border-radius: 8px;
  background: var(--input-bg);
  color: var(--text);
}
input:focus {
  outline: none;
  border-color: var(--accent);
  background: var(--panel);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
button, .button-link {
  padding: .45rem .95rem;
  border: 1px solid var(--accent);
  border-radius: 9px;
  background: var(--accent);
  color: #fff;
  font-size: .9rem;
  font-weight: 600;
  line-height: 1.45;
}
button:hover, .button-link:hover { background: color-mix(in srgb, var(--accent) 88%, #000); }
button:focus-visible, a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.error {
  border: 1px solid var(--danger-border);
  border-radius: 10px;
  background: var(--bad-soft);
  color: var(--bad);
}
"""

SOCIO_EVO_CSS = """
:root {
  color-scheme: light;
  --page: #f4efe4;
  --surface: #fffdf8;
  --surface-2: #f8f3e8;
  --ink: #1f1b14;
  --ink-2: #5a5246;
  --muted: #847b6c;
  --line: #e6dfd0;
  --ring: rgba(31, 27, 20, 0.1);
  --shadow: 0 1px 2px rgba(60, 45, 20, 0.08), 0 4px 14px rgba(60, 45, 20, 0.06);
  --accent: #8c6a3b;
  --focus: #1f1b14;
  --critical: #d03b3b;
  --critical-text: #b42727;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --page: #14120e;
    --surface: #1e1b16;
    --surface-2: #25211a;
    --ink: #f1ebdf;
    --ink-2: #c4bba9;
    --muted: #958c7b;
    --line: #332e25;
    --ring: rgba(255, 245, 225, 0.1);
    --shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 6px 18px rgba(0, 0, 0, 0.25);
    --accent: #d3b88a;
    --focus: #f1ebdf;
    --critical-text: #ef6b6b;
  }
}
body {
  background: var(--page);
  color: var(--ink);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.shell { max-width: 360px; }
.card {
  padding: 28px;
  background: var(--surface);
  border: 1px solid var(--ring);
  border-radius: 14px;
  box-shadow: var(--shadow);
}
.brand { gap: 8px; font-size: 15px; font-weight: 700; }
.brand-mark {
  width: 26px;
  height: 26px;
  fill: none;
  stroke: currentColor;
  stroke-width: 2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.brand-mark circle { fill: var(--accent); stroke: none; }
h1 { font-size: 22px; font-weight: 650; letter-spacing: -.01em; }
.description { color: var(--ink-2); }
form { gap: 18px; }
label { font-weight: 550; }
input:not([type="hidden"]) {
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-2);
  color: var(--ink);
}
input:focus, button:focus-visible, a:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
button, .button-link {
  padding: 6px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: var(--ink);
  color: var(--page);
  font-weight: 550;
}
button:hover, .button-link:hover { background: color-mix(in srgb, var(--ink) 85%, var(--page)); }
.error {
  border: 1px solid color-mix(in srgb, var(--critical) 45%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--critical) 12%, var(--surface));
  color: var(--critical-text);
}
"""

PAGE_CSS = {
    "cornerhead": LAYOUT_CSS + CORNERHEAD_CSS,
    "socio-evo": LAYOUT_CSS + SOCIO_EVO_CSS,
}
PAGE_CSS_HASH = {
    service: base64.b64encode(hashlib.sha256(css.encode("utf-8")).digest()).decode("ascii")
    for service, css in PAGE_CSS.items()
}
BRANDS = {
    "cornerhead": (
        "CornerHead",
        '<svg class="brand-mark" viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">'
        '<defs><linearGradient id="auth-ch-g" x1="0" y1="1" x2="1" y2="0">'
        '<stop offset="0" stop-color="#2456c4"/><stop offset="1" stop-color="#6ea8ff"/>'
        '</linearGradient></defs>'
        '<path d="M8 25 V9 H24" fill="none" stroke="url(#auth-ch-g)" stroke-width="5.5" '
        'stroke-linecap="round" stroke-linejoin="miter"/>'
        '<circle cx="22.5" cy="22.5" r="5.5" fill="url(#auth-ch-g)"/></svg>',
    ),
    "socio-evo": (
        "socio-evo",
        '<svg class="brand-mark" viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">'
        '<path d="M4 15 16 5l12 10"/><path d="M8 13v13h16V13"/>'
        '<circle cx="13" cy="20" r="2.6"/><circle cx="19.5" cy="20" r="2.6"/></svg>',
    ),
}


def hash_password(password: str) -> str:
    """Salted scrypt: 32 MiB memory, three passes, a random 128-bit salt."""
    if not password or len(password.encode("utf-8")) > 1024:
        raise ValueError("password must contain between 1 and 1024 UTF-8 bytes")
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
        maxmem=64 * 1024 * 1024,
    )


@dataclass(frozen=True)
class Config:
    service: str
    origin: str
    username: str
    password_hash: str
    session_secret: str
    state_dir: Path
    session_days: int = SESSION_DAYS

    def __post_init__(self) -> None:
        if self.service not in SERVICES:
            raise ValueError("service must be cornerhead or socio-evo")
        try:
            origin = urlsplit(self.origin)
            valid_origin = (
                origin.scheme == "https"
                and origin.username is None
                and origin.password is None
                and origin.hostname is not None
                and isinstance(ipaddress.ip_address(origin.hostname), ipaddress.IPv4Address)
                and origin.port is not None
                and 1 <= origin.port <= 65535
                and self.origin == f"https://{origin.hostname}:{origin.port}"
            )
        except (ValueError, TypeError):
            valid_origin = False
        if not valid_origin:
            raise ValueError("origin must be a canonical HTTPS IPv4 origin with an explicit port")
        if not isinstance(self.username, str) or not USERNAME_RE.fullmatch(self.username):
            raise ValueError("username must contain 1-64 ASCII letters, digits or ._-")
        if not isinstance(self.password_hash, str) or not HASH_RE.fullmatch(self.password_hash):
            raise ValueError("password_hash must be generated by hash_password")
        if not isinstance(self.session_secret, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{64}", self.session_secret
        ):
            raise ValueError("session_secret must be a 64-character random URL-safe secret")
        if not isinstance(self.state_dir, Path) or not self.state_dir.is_absolute():
            raise ValueError("state_dir must be an absolute path")
        if type(self.session_days) is not int or self.session_days != SESSION_DAYS:
            raise ValueError("session_days must be 30")

    @property
    def cookie_name(self) -> str:
        return f"__Host-{self.service}_session"

    @property
    def csrf_cookie_name(self) -> str:
        return f"__Host-{self.service}_csrf"

    @property
    def session_seconds(self) -> int:
        return self.session_days * 86400

    @classmethod
    def load(cls, path: Path) -> Config:
        with _open_private(path, create=False) as stream:
            try:
                raw = json.loads(stream.read(16385))
            except (ValueError, UnicodeError):
                raise ValueError("invalid auth config JSON") from None
        fields = {
            "service",
            "origin",
            "username",
            "password_hash",
            "session_secret",
            "state_dir",
            "session_days",
        }
        if (
            not isinstance(raw, dict)
            or set(raw) != fields
            or not all(isinstance(raw[key], str) for key in fields - {"session_days"})
        ):
            raise ValueError("auth config must contain exactly the documented fields")
        raw["state_dir"] = Path(raw["state_dir"])
        return cls(**raw)


def _open_private(path: Path, *, create: bool):
    flags = (os.O_RDWR if create else os.O_RDONLY) | os.O_NOFOLLOW
    if create:
        flags |= os.O_CREAT
    descriptor = os.open(path, flags, 0o600)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        os.close(descriptor)
        raise ValueError("auth files must be owned by the daemon user and have private permissions")
    return os.fdopen(descriptor, "r", encoding="utf-8")


def provision(
    config_path: Path,
    credentials_path: Path,
    *,
    service: str,
    origin: str,
    state_dir: Path,
) -> None:
    """Root-only exclusive provisioning; do not print or return generated secrets."""
    if os.geteuid() != 0:
        raise ValueError("provisioning must run as root")
    username = f"{service}-admin-{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(32)
    config = Config(
        service,
        origin,
        username,
        hash_password(password),
        secrets.token_urlsafe(48),
        state_dir,
    )
    payload = dict(vars(config), state_dir=str(state_dir))
    credentials = {"service": service, "origin": origin, "username": username, "password": password}
    created: list[Path] = []
    descriptors: list[int] = []
    try:
        # Reserve both paths before writing either. An existing file is never altered.
        for path in (config_path, credentials_path):
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            descriptors.append(descriptor)
            created.append(path)
        for descriptor, data in zip(descriptors, (payload, credentials), strict=True):
            with os.fdopen(os.dup(descriptor), "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


class SessionStore:
    """SQLite transactions commit before issuing cookies or acknowledging logout."""

    def __init__(self, config: Config, clock: Callable[[], float] = time.time) -> None:
        self.config, self.clock = config, clock
        self.path = config.state_dir / "sessions.sqlite3"
        config.state_dir.mkdir(mode=0o700, parents=False, exist_ok=True)
        info = config.state_dir.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            raise ValueError("state_dir must be an owned private directory (0700)")
        with _open_private(self.path, create=True):
            pass
        # Bind tokens/CSRF to this service and credential generation, even if
        # two deployments accidentally use the same directory or secret.
        self.key = config.session_secret.encode("ascii")
        self.scope = json.dumps(
            [config.service, config.origin, config.username, config.password_hash],
            separators=(",", ":"),
        ).encode("ascii")
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sessions "
                "(digest TEXT PRIMARY KEY, expires_at REAL NOT NULL)"
            )
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (self.clock(),))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def digest(self, token: str, purpose: str = "session") -> str:
        data = self.scope + b"\0" + purpose.encode("ascii") + b"\0" + token.encode("utf-8")
        return hmac.new(self.key, data, hashlib.sha256).hexdigest()

    def create(self, previous: str | None = None) -> str:
        token, now = secrets.token_urlsafe(32), self.clock()
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            if previous and TOKEN_RE.fullmatch(previous):
                connection.execute(
                    "DELETE FROM sessions WHERE digest = ?", (self.digest(previous),)
                )
            # Bound store growth; a single deployment supports at most 1024 sessions.
            connection.execute(
                "DELETE FROM sessions WHERE digest IN "
                "(SELECT digest FROM sessions ORDER BY expires_at DESC LIMIT -1 OFFSET 1023)"
            )
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?)",
                (self.digest(token), now + self.config.session_seconds),
            )
        return token

    def valid(self, token: str | None) -> bool:
        if not token or not TOKEN_RE.fullmatch(token):
            return False
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT expires_at FROM sessions WHERE digest = ?",
                (self.digest(token),),
            ).fetchone()
        return row is not None and self.clock() < row[0]

    def revoke(self, token: str | None) -> None:
        if token and TOKEN_RE.fullmatch(token):
            with closing(self._connect()) as connection, connection:
                connection.execute("DELETE FROM sessions WHERE digest = ?", (self.digest(token),))


@dataclass
class Response:
    status: int
    body: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    is_html: bool = False


class RequestError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status, self.message = status, message


class Gateway:
    def __init__(self, config: Config, clock: Callable[[], float] = time.time) -> None:
        self.config, self.clock = config, clock
        self.sessions = SessionStore(config, clock)
        self.attempts: deque[float] = deque()
        self.attempt_lock = threading.Lock()

    def __call__(self, environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        try:
            response = self.dispatch(environ)
        except RequestError as exc:
            response = Response(exc.status, exc.message)
        except Exception:
            # Never log exception arguments, submitted forms, cookies or headers.
            logging.getLogger("webui-auth").error("authentication operation failed")
            response = Response(503, "Authentication unavailable")
        # Presentation only: keep failures, headers and cookies exactly as dispatched.
        if response.status >= 400 and environ.get("PATH_INFO") in {"/_auth/login", "/_auth/logout"}:
            response = Response(
                response.status,
                self.error_html(environ["PATH_INFO"], response.status, response.body),
                response.headers,
                True,
            )
        body = response.body.encode("utf-8")
        headers = [
            (
                "Content-Type",
                "text/html; charset=utf-8" if response.is_html else "text/plain; charset=utf-8",
            ),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store, max-age=0"),
            ("Pragma", "no-cache"),
            (
                "Content-Security-Policy",
                "default-src 'none'; "
                + (
                    f"style-src 'sha256-{PAGE_CSS_HASH[self.config.service]}'; "
                    if response.is_html else ""
                )
                + "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            ),
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "same-origin"),
            *response.headers,
        ]
        start_response(f"{response.status} {HTTPStatus(response.status).phrase}", headers)
        return [b"" if environ.get("REQUEST_METHOD") == "HEAD" else body]

    def dispatch(self, environ: dict[str, Any]) -> Response:
        path, method = environ.get("PATH_INFO"), environ.get("REQUEST_METHOD")
        if path == "/_auth/check" and method == "GET":
            original_method = environ.get("HTTP_X_ORIGINAL_METHOD", "")
            if not METHOD_RE.fullmatch(original_method):
                raise RequestError(403, "Missing or invalid original method")
            if (
                original_method not in {"GET", "HEAD", "OPTIONS"}
                and environ.get("HTTP_X_ORIGINAL_ORIGIN") != self.config.origin
            ):
                raise RequestError(403, "Same-origin required for unsafe requests")
            return Response(
                204 if self.sessions.valid(self.cookie(environ, self.config.cookie_name)) else 401
            )
        if path not in {"/_auth/login", "/_auth/logout"}:
            return Response(404, "Not found")
        if method not in {"GET", "POST"}:
            return Response(405, "Method not allowed", (("Allow", "GET, POST"),))
        origin = environ.get("HTTP_ORIGIN")
        if (origin is not None and origin != self.config.origin) or (
            method == "POST" and origin != self.config.origin
        ):
            raise RequestError(403, "Same-origin required")
        purpose = "login" if path == "/_auth/login" else "logout"
        session = self.cookie(environ, self.config.cookie_name)
        binding = (session or "") if purpose == "logout" else ""
        if method == "GET":
            if purpose == "login" and self.sessions.valid(session):
                return Response(303, headers=(("Location", "/"),))
            csrf = self.cookie(environ, self.config.csrf_cookie_name)
            if not csrf or not self.valid_csrf(csrf, purpose, binding):
                csrf = self.new_csrf(purpose, binding)
            return Response(
                200,
                self.form_html(purpose, csrf),
                (
                    (
                        "Set-Cookie",
                        self.set_cookie(self.config.csrf_cookie_name, csrf, CSRF_SECONDS),
                    ),
                ),
                True,
            )
        form = self.read_form(
            environ, {"csrf", "username", "password"} if purpose == "login" else {"csrf"}
        )
        csrf = self.cookie(environ, self.config.csrf_cookie_name)
        if (
            not csrf
            or not hmac.compare_digest(form["csrf"].encode("utf-8"), csrf.encode("utf-8"))
            or not self.valid_csrf(csrf, purpose, binding)
        ):
            raise RequestError(403, "Invalid or expired form; reload the page")
        if purpose == "logout":
            self.sessions.revoke(session)
            return Response(
                303,
                headers=(
                    ("Location", "/_auth/login"),
                    ("Set-Cookie", self.set_cookie(self.config.cookie_name, "", 0)),
                    ("Set-Cookie", self.set_cookie(self.config.csrf_cookie_name, "", 0)),
                ),
            )
        self.limit_login()
        username, password = form["username"], form["password"]
        if (
            not USERNAME_RE.fullmatch(username)
            or not password
            or len(password.encode("utf-8")) > 1024
        ):
            raise RequestError(401, "Invalid username or password")
        encoded = HASH_RE.fullmatch(self.config.password_hash)
        assert encoded is not None  # validated at startup
        password_matches = hmac.compare_digest(
            _scrypt(password, bytes.fromhex(encoded[1])), bytes.fromhex(encoded[2])
        )
        username_matches = hmac.compare_digest(
            username.encode("utf-8"), self.config.username.encode("utf-8")
        )
        if not (password_matches & username_matches):
            raise RequestError(401, "Invalid username or password")
        token = self.sessions.create(session)
        return Response(
            303,
            headers=(
                ("Location", "/"),
                (
                    "Set-Cookie",
                    self.set_cookie(self.config.cookie_name, token, self.config.session_seconds),
                ),
                ("Set-Cookie", self.set_cookie(self.config.csrf_cookie_name, "", 0)),
            ),
        )

    def limit_login(self) -> None:
        with self.attempt_lock:
            now = self.clock()
            while self.attempts and self.attempts[0] <= now - 60:
                self.attempts.popleft()
            if len(self.attempts) >= 10:
                raise RequestError(429, "Too many login attempts; wait one minute")
            self.attempts.append(now)

    def cookie(self, environ: dict[str, Any], name: str) -> str | None:
        header = environ.get("HTTP_COOKIE", "")
        if not header or len(header) > MAX_COOKIE_BYTES:
            return None
        # Reject duplicate cookie names rather than choosing an attacker's copy.
        if sum(item.strip().split("=", 1)[0] == name for item in header.split(";")) != 1:
            return None
        parsed: SimpleCookie = SimpleCookie()
        try:
            parsed.load(header)
        except CookieError:
            return None
        return parsed[name].value if name in parsed else None

    def new_csrf(self, purpose: str, binding: str) -> str:
        prefix = f"{secrets.token_urlsafe(32)}.{int(self.clock()) + CSRF_SECONDS}"
        return prefix + "." + self.sessions.digest(prefix + "\0" + binding, f"csrf-{purpose}")

    def valid_csrf(self, token: str | None, purpose: str, binding: str) -> bool:
        match = CSRF_RE.fullmatch(token or "")
        if not match or not self.clock() < int(match[2]) <= self.clock() + CSRF_SECONDS:
            return False
        expected = self.sessions.digest(f"{match[1]}.{match[2]}\0{binding}", f"csrf-{purpose}")
        return hmac.compare_digest(match[3], expected)

    @staticmethod
    def set_cookie(name: str, token: str, seconds: int) -> str:
        same_site = "Strict" if name.endswith("_csrf") else "Lax"
        return f"{name}={token}; Secure; HttpOnly; SameSite={same_site}; Path=/; Max-Age={seconds}"

    @staticmethod
    def read_form(environ: dict[str, Any], expected: set[str]) -> dict[str, str]:
        if (
            environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip().lower()
            != "application/x-www-form-urlencoded"
        ):
            raise RequestError(415, "Expected a URL-encoded form")
        length = environ.get("CONTENT_LENGTH", "")
        if not length.isascii() or not length.isdecimal() or len(length) > 8:
            raise RequestError(400, "Invalid content length")
        size = int(length)
        if size > MAX_BODY_BYTES:
            raise RequestError(413, "Request too large")
        if not size:
            raise RequestError(400, "Empty form")
        raw = environ["wsgi.input"].read(size)
        if len(raw) != size:
            raise RequestError(400, "Incomplete form")
        try:
            values = parse_qs(
                raw.decode("ascii"),
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
                max_num_fields=len(expected),
            )
            if set(values) != expected or any(len(items) != 1 for items in values.values()):
                raise ValueError
        except (ValueError, UnicodeError):
            raise RequestError(400, "Invalid form") from None
        return {key: items[0] for key, items in values.items()}

    def page_html(self, title: str, content: str) -> str:
        """Shared shell; content is markup built only by the escaped renderers below."""
        brand, mark = BRANDS[self.config.service]
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · {html.escape(brand)}</title>
<style>{PAGE_CSS[self.config.service]}</style></head>
<body class="{html.escape(self.config.service, quote=True)}">
<main class="shell"><section class="card" aria-labelledby="page-title">
<div class="brand">{mark}<span>{html.escape(brand)}</span></div>
<h1 id="page-title">{html.escape(title)}</h1>{content}
</section></main></body></html>"""

    def form_html(self, purpose: str, csrf: str) -> str:
        login = purpose == "login"
        title = "Sign in" if login else "Sign out?"
        description = (
            ""
            if login
            else '<p class="description">This ends your session in this browser. '
            "You can sign in again at any time.</p>"
        )
        fields = (
            """
<div class="field"><label for="username">Username</label>
<input id="username" name="username" type="text" autocomplete="username"
autocapitalize="none" spellcheck="false" maxlength="64" required></div>
<div class="field"><label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password"
maxlength="256" required></div>"""
            if login
            else ""
        )
        content = f"""{description}
<form method="post" action="/_auth/{html.escape(purpose, quote=True)}">
<input type="hidden" name="csrf" value="{html.escape(csrf, quote=True)}">{fields}
<button type="submit">{"Sign in" if login else "Confirm sign out"}</button></form>"""
        return self.page_html(title, content)

    def error_html(self, path: str, status: int, message: str) -> str:
        login = path == "/_auth/login"
        title = "Unable to sign in" if login else "Unable to sign out"
        recovery = "Return to sign in" if login else "Return to sign-out confirmation"
        content = f"""
<div class="error" role="alert">
<span class="error-code">{html.escape(str(status))} ·
{html.escape(HTTPStatus(status).phrase)}</span>
<p>{html.escape(message)}</p></div>
<a class="button-link" href="{html.escape(path, quote=True)}">{html.escape(recovery)}</a>"""
        return self.page_html(title, content)


def serve(gateway: Gateway, path: Path, socket_group: str = "nginx") -> None:
    """No TCP fallback. Parent access is controlled by the systemd unit."""
    from waitress.server import create_server

    if not path.is_absolute() or not path.parent.is_dir():
        raise ValueError("socket must be an absolute path in an existing runtime directory")
    gid = grp.getgrnam(socket_group).gr_gid
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
            raise ValueError("refusing to replace a non-socket or unowned socket")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            try:
                probe.connect(str(path))
            except OSError as exc:
                if exc.errno != errno.ECONNREFUSED:
                    raise ValueError("cannot safely replace runtime socket") from None
            else:
                raise ValueError("authentication socket is already in use")
        path.unlink()
    server = create_server(
        gateway,
        unix_socket=str(path),
        unix_socket_perms="660",
        threads=4,
        max_request_body_size=MAX_BODY_BYTES,
        max_request_header_size=16384,
        channel_timeout=30,
        cleanup_interval=5,
        connection_limit=64,
        expose_tracebacks=False,
        log_socket_errors=False,
    )
    try:
        if path.stat().st_gid != gid:
            os.chown(path, -1, gid)
        server.run()
    finally:
        server.task_dispatcher.shutdown()
        server.close()
        path.unlink(missing_ok=True)


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--socket", type=Path)
    parser.add_argument(
        "--socket-group",
        default="nginx",
        help="default nginx; override only for local transport tests",
    )
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--service", choices=sorted(SERVICES))
    parser.add_argument("--origin")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--credentials-file", type=Path)
    args = parser.parse_args(arguments)
    try:
        if args.provision:
            if (
                not all((args.service, args.origin, args.state_dir, args.credentials_file))
                or args.socket
            ):
                parser.error(
                    "provisioning requires --service, --origin, --state-dir "
                    "and --credentials-file, without --socket"
                )
            provision(
                args.config,
                args.credentials_file,
                service=args.service,
                origin=args.origin,
                state_dir=args.state_dir,
            )
        else:
            if not args.socket or any(
                (args.service, args.origin, args.state_dir, args.credentials_file)
            ):
                parser.error("serving requires --config and --socket, without provisioning options")
            serve(Gateway(Config.load(args.config)), args.socket, args.socket_group)
    except (OSError, ValueError, KeyError, sqlite3.Error):
        # Exception details may contain secret file contents: deliberately omit them.
        parser.exit(
            1,
            "webui-auth: startup/provisioning failed; check private files, "
            "config, state and socket permissions\n",
        )


if __name__ == "__main__":
    main()
