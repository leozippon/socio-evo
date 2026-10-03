"""Authentication invariants and real HTTP over the production Unix transport."""

import grp
import http.client
import io
import json
import os
import re
import socket
import sqlite3
import stat
import subprocess
import sys
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode

import pytest

from ops.webui.gateway import Config, Gateway, hash_password, main, provision

ORIGIN = "https://8.133.175.124:8443"
PASSWORD = "test-only-password-not-a-deployed-credential"
PROJECT = Path(__file__).parents[2]
GATEWAY = PROJECT / "ops" / "webui" / "gateway.py"


@dataclass
class Clock:
    now: float = 1_750_000_000

    def __call__(self) -> float:
        return self.now


@dataclass
class Result:
    status: int
    headers: list[tuple[str, str]]
    body: str

    def header(self, name: str) -> str | None:
        return next((value for key, value in self.headers if key.lower() == name.lower()), None)


class Browser:
    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway
        self.cookies: dict[str, str] = {}

    def request(self, method="GET", path="/_auth/check", *, form=None, headers=None, raw=None):
        body = urlencode(form).encode("ascii") if form is not None else raw or b""
        env = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path.split("?", 1)[0],
            "QUERY_STRING": path.partition("?")[2],
            "wsgi.input": io.BytesIO(body),
            "CONTENT_LENGTH": str(len(body)),
            "CONTENT_TYPE": "application/x-www-form-urlencoded",
            "HTTP_COOKIE": "; ".join(f"{key}={value}" for key, value in self.cookies.items()),
            "HTTP_X_ORIGINAL_METHOD": "GET",
        }
        if method == "POST":
            env["HTTP_ORIGIN"] = self.gateway.config.origin
        for name, value in (headers or {}).items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value
        result = Result(0, [], "")

        def start_response(status, response_headers):
            result.status, result.headers = int(status.split()[0]), response_headers

        result.body = b"".join(self.gateway(env, start_response)).decode("utf-8")
        assert result.header("Cache-Control") == "no-store, max-age=0"
        assert result.header("Content-Security-Policy") is not None
        self.save_cookies(result)
        return result

    def save_cookies(self, result: Result) -> None:
        for key, value in result.headers:
            if key.lower() == "set-cookie":
                parsed = SimpleCookie(value)
                for name, morsel in parsed.items():
                    if morsel["max-age"] == "0":
                        self.cookies.pop(name, None)
                    else:
                        self.cookies[name] = morsel.value

    def csrf(self, purpose="login") -> str:
        result = self.request(path=f"/_auth/{purpose}")
        assert result.status == 200
        return csrf_value(result)

    def login(self) -> Result:
        return self.request(
            "POST",
            "/_auth/login",
            form={
                "username": self.gateway.config.username,
                "password": PASSWORD,
                "csrf": self.csrf(),
            },
        )


def csrf_value(result: Result) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', result.body)
    assert match is not None
    return match[1]


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def config(tmp_path, password_hash):
    return Config(
        "socio-evo",
        ORIGIN,
        "test-admin",
        password_hash,
        "s" * 64,
        tmp_path / "state",
    )


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def browser(config, clock):
    return Browser(Gateway(config, clock))


def config_file(config: Config, path: Path) -> Path:
    path.write_text(
        json.dumps(dict(vars(config), state_dir=str(config.state_dir))), encoding="utf-8"
    )
    path.chmod(0o600)
    return path


def test_login_cookie_only_and_secure_attributes(browser):
    assert (
        browser.request(
            headers={
                "HTTP_X_REMOTE_USER": "test-admin",
                "HTTP_AUTHORIZATION": "Basic spoofed",
                "HTTP_X_AUTH_REQUEST_USER": "test-admin",
            }
        ).status
        == 401
    )
    csrf = browser.csrf()
    for username, password in (("test-admin", "wrong-password"), ("wrong-user", PASSWORD)):
        result = browser.request(
            "POST",
            "/_auth/login",
            form={
                "username": username,
                "password": password,
                "csrf": csrf,
            },
        )
        assert result.status == 401
        assert browser.gateway.config.cookie_name not in browser.cookies
    result = browser.login()
    assert result.status == 303
    assert result.header("Location") == "/"
    cookie = next(
        value for name, value in result.headers if name == "Set-Cookie" and "_session=" in value
    )
    assert cookie.startswith("__Host-socio-evo_session=")
    assert all(
        attribute in cookie
        for attribute in (
            "Secure",
            "HttpOnly",
            "SameSite=Lax",
            "Path=/",
            "Max-Age=2592000",
        )
    )
    assert "Domain=" not in cookie
    assert browser.request().status == 204
    assert (
        browser.request(path="/_auth/login?next=https://attacker.invalid").header("Location") == "/"
    )


def test_session_store_is_private_hashed_persistent_and_expires(browser, clock, config):
    assert browser.login().status == 303
    token = browser.cookies[config.cookie_name]
    path = browser.gateway.sessions.path
    assert stat.S_IMODE(config.state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with closing(sqlite3.connect(path)) as connection:
        digest, expires = connection.execute("SELECT digest, expires_at FROM sessions").fetchone()
    assert re.fullmatch("[0-9a-f]{64}", digest)
    assert token.encode() not in path.read_bytes()
    assert expires == clock.now + 30 * 86400
    restarted = Browser(Gateway(Config.load(config_file(config, path.parent / "auth.json")), clock))
    restarted.cookies = browser.cookies.copy()
    assert restarted.request().status == 204
    clock.now = expires - 0.01
    assert restarted.request().status == 204
    clock.now = expires
    assert restarted.request().status == 401
    assert Browser(Gateway(config, clock)).gateway.sessions.valid(token) is False


def test_logout_confirmation_csrf_and_durable_revocation(browser, config, clock):
    assert browser.login().status == 303
    token = browser.cookies[config.cookie_name]
    csrf = browser.csrf("logout")
    assert browser.request().status == 204  # GET confirmation must not log out.
    for origin in (None, "null", "https://8.133.175.124:9443"):
        assert (
            browser.request(
                "POST",
                "/_auth/logout",
                form={"csrf": csrf},
                headers={
                    "HTTP_ORIGIN": origin,
                },
            ).status
            == 403
        )
    assert browser.request("POST", "/_auth/logout", form={"csrf": "forged"}).status == 403
    result = browser.request("POST", "/_auth/logout", form={"csrf": csrf})
    assert result.status == 303
    assert result.header("Location") == "/_auth/login"
    assert config.cookie_name not in browser.cookies
    assert browser.request().status == 401
    replay = Browser(Gateway(config, clock))
    replay.cookies[config.cookie_name] = token
    assert replay.request().status == 401
    with closing(sqlite3.connect(replay.gateway.sessions.path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_login_rotates_session_and_logout_csrf_is_bound_to_session(browser):
    assert browser.login().status == 303
    first_token = browser.cookies[browser.gateway.config.cookie_name]
    logout_csrf = browser.csrf("logout")
    # A different browser logs in; a logout token cannot be replayed against it.
    other = Browser(browser.gateway)
    assert other.login().status == 303
    other.cookies[browser.gateway.config.csrf_cookie_name] = logout_csrf
    assert other.request("POST", "/_auth/logout", form={"csrf": logout_csrf}).status == 403
    # Signing in again replaces this browser's original session rather than fixing it.
    fresh_form = Browser(browser.gateway)
    csrf = fresh_form.csrf()
    browser.cookies[browser.gateway.config.csrf_cookie_name] = csrf
    assert (
        browser.request(
            "POST",
            "/_auth/login",
            form={
                "username": "test-admin",
                "password": PASSWORD,
                "csrf": csrf,
            },
        ).status
        == 303
    )
    assert not browser.gateway.sessions.valid(first_token)
    assert other.request().status == 204


def test_cookie_tampering_duplicates_and_cross_service_replay(browser, config, clock):
    assert browser.login().status == 303
    token = browser.cookies[config.cookie_name]
    for value in (token[:-1] + ("a" if token[-1] != "a" else "b"), "short", "x" * 9000):
        assert (
            browser.request(headers={"HTTP_COOKIE": f"{config.cookie_name}={value}"}).status == 401
        )
    assert (
        browser.request(
            headers={
                "HTTP_COOKIE": f"{config.cookie_name}={token}; {config.cookie_name}=forged",
            }
        ).status
        == 401
    )
    # Deliberately share the secret AND SQLite file: service/origin namespacing
    # must still prevent relabelling an otherwise valid service cookie.
    other_config = replace(config, service="cornerhead", origin="https://8.133.175.124:9443")
    other = Browser(Gateway(other_config, clock))
    other.cookies[config.cookie_name] = token
    assert other.request().status == 401
    other.cookies[other_config.cookie_name] = token
    assert other.request().status == 401
    assert other.login().status == 303
    assert other.request().status == 204
    assert browser.request().status == 204
    assert config.cookie_name != other_config.cookie_name
    csrf = other.csrf("logout")
    browser.cookies[config.csrf_cookie_name] = csrf
    assert browser.request("POST", "/_auth/logout", form={"csrf": csrf}).status == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "CUSTOM"])
def test_check_requires_exact_original_origin_for_unsafe_methods(browser, method):
    assert browser.login().status == 303
    for origin in (
        None,
        "",
        "null",
        "http://8.133.175.124:8443",
        "https://8.133.175.124:9443",
        ORIGIN + "/",
    ):
        assert (
            browser.request(
                headers={
                    "HTTP_X_ORIGINAL_METHOD": method,
                    "HTTP_X_ORIGINAL_ORIGIN": origin,
                    "HTTP_ORIGIN": ORIGIN,
                    "HTTP_REFERER": ORIGIN + "/",
                }
            ).status
            == 403
        )
    assert (
        browser.request(
            headers={
                "HTTP_X_ORIGINAL_METHOD": method,
                "HTTP_X_ORIGINAL_ORIGIN": ORIGIN,
            }
        ).status
        == 204
    )
    for bad_method in (None, "", "get", "POST, GET"):
        assert (
            browser.request(
                headers={
                    "HTTP_X_ORIGINAL_METHOD": bad_method,
                    "HTTP_X_ORIGINAL_ORIGIN": ORIGIN,
                }
            ).status
            == 403
        )
    for safe_method in ("GET", "HEAD", "OPTIONS"):
        assert browser.request(headers={"HTTP_X_ORIGINAL_METHOD": safe_method}).status == 204


def test_login_origin_signed_double_submit_and_csrf_expiry(browser, clock):
    csrf = browser.csrf()
    form = {"username": "test-admin", "password": PASSWORD, "csrf": csrf}
    for method in ("GET", "POST"):
        for origin in ("null", ORIGIN + "/", "https://8.133.175.124:9443", ORIGIN + ", " + ORIGIN):
            assert (
                browser.request(
                    method,
                    "/_auth/login",
                    form=form if method == "POST" else None,
                    headers={"HTTP_ORIGIN": origin},
                ).status
                == 403
            )
    assert (
        browser.request(
            "POST",
            "/_auth/login",
            form=form,
            headers={
                "HTTP_ORIGIN": None,
                "HTTP_REFERER": ORIGIN + "/_auth/login",
            },
        ).status
        == 403
    )
    assert (
        browser.request("POST", "/_auth/login", form=form, headers={"HTTP_COOKIE": None}).status
        == 403
    )
    forged = "x" * 43 + f".{int(clock.now) + 600}." + "0" * 64
    assert (
        browser.request(
            "POST",
            "/_auth/login",
            form=dict(form, csrf=forged),
            headers={
                "HTTP_COOKIE": f"{browser.gateway.config.csrf_cookie_name}={forged}",
            },
        ).status
        == 403
    )
    clock.now += 600
    assert browser.request("POST", "/_auth/login", form=form).status == 403
    assert browser.login().status == 303


def test_bounded_forms_no_open_redirect_and_no_secret_logging(browser, caplog):
    csrf = browser.csrf()
    form = {"username": "test-admin", "password": PASSWORD, "csrf": csrf}
    for raw, headers, status in (
        (b"x" * 4097, {}, 413),
        (urlencode(form).encode(), {"CONTENT_LENGTH": None}, 400),
        (urlencode(form).encode(), {"CONTENT_LENGTH": "-1"}, 400),
        (urlencode(form).encode(), {"CONTENT_TYPE": "application/json"}, 415),
        (urlencode(form).encode() + b"&username=duplicate", {}, 400),
        (urlencode(dict(form, next="https://attacker.invalid")).encode(), {}, 400),
        (b"username=%ff&password=x&csrf=x", {}, 400),
        (b"", {}, 400),
    ):
        assert browser.request("POST", "/_auth/login", raw=raw, headers=headers).status == status
    assert browser.login().status == 303
    token = browser.cookies[browser.gateway.config.cookie_name]
    assert browser.request("PUT", "/_auth/login").status == 405
    assert browser.request(path="/not-found").status == 404
    # A real broken store must fail closed, not silently authenticate or forget revocations.
    path = browser.gateway.sessions.path
    backup = path.with_suffix(".backup")
    path.rename(backup)
    try:
        assert browser.request().status == 503
    finally:
        path.unlink(missing_ok=True)
        backup.rename(path)
    assert PASSWORD not in caplog.text
    assert token not in caplog.text
    assert browser.gateway.config.session_secret not in caplog.text
    assert "authentication operation failed" in caplog.text


def test_modest_global_login_limit(browser, clock):
    csrf = browser.csrf()
    bad_form = {"username": "!", "password": PASSWORD, "csrf": csrf}
    for i in range(10):
        assert (
            browser.request(
                "POST",
                "/_auth/login",
                form=bad_form,
                headers={
                    "HTTP_X_FORWARDED_FOR": f"192.0.2.{i}",
                },
            ).status
            == 401
        )
    assert (
        browser.request(
            "POST",
            "/_auth/login",
            form={
                "username": "test-admin",
                "password": PASSWORD,
                "csrf": csrf,
            },
        ).status
        == 429
    )
    clock.now += 60
    assert browser.login().status == 303


@pytest.mark.parametrize(
    "change",
    [
        {"service": "other"},
        {"origin": "http://8.133.175.124:8443"},
        {"origin": "https://user:password@8.133.175.124:8443"},
        {"origin": ORIGIN + "/"},
        {"origin": "https://8.133.175.124"},
        {"origin": "https://8.133.175.124:8443/path"},
        {"origin": "https://localhost:8443"},
        {"state_dir": Path("relative")},
        {"session_days": True},
        {"session_days": 31},
        {"password_hash": "plain-text"},
        {"session_secret": "short"},
    ],
)
def test_config_rejects_unsafe_values(config, change):
    with pytest.raises(ValueError):
        replace(config, **change)


def test_private_config_permissions_schema_and_credential_rotation(config, tmp_path, clock):
    path = config_file(config, tmp_path / "auth.json")
    assert Config.load(path) == config
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        Config.load(path)
    path.chmod(0o600)
    linked = tmp_path / "linked.json"
    linked.symlink_to(path)
    with pytest.raises(OSError):
        Config.load(linked)
    data = json.loads(path.read_text())
    path.write_text(json.dumps(dict(data, unrecognized="value")))
    with pytest.raises(ValueError, match="documented fields"):
        Config.load(path)
    gateway = Gateway(config, clock)
    token = gateway.sessions.create()
    assert not Gateway(replace(config, session_secret="t" * 64), clock).sessions.valid(token)
    assert not Gateway(replace(config, username="new-admin"), clock).sessions.valid(token)
    assert not Gateway(
        replace(config, password_hash=hash_password(PASSWORD)), clock
    ).sessions.valid(token)


def test_safe_provision_separate_credentials_exclusive_files_and_no_output(
    tmp_path, monkeypatch, capsys
):
    if os.geteuid() != 0:
        with pytest.raises(ValueError, match="root"):
            provision(
                tmp_path / "auth.json",
                tmp_path / "credentials.json",
                service="socio-evo",
                origin=ORIGIN,
                state_dir=tmp_path / "state",
            )
    configs, credentials = [], []
    # The test host is non-root: bypass only the CLI root gate. Files are
    # still created by the real filesystem and their private modes are checked.
    with monkeypatch.context() as patch:
        patch.setattr(os, "geteuid", lambda: 0)
        for service in ("cornerhead", "socio-evo"):
            config_path, creds_path = (
                tmp_path / f"{service}.json",
                tmp_path / f"{service}-creds.json",
            )
            provision(
                config_path,
                creds_path,
                service=service,
                origin=ORIGIN,
                state_dir=tmp_path / service,
            )
            for path in (config_path, creds_path):
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
            configs.append(json.loads(config_path.read_text()))
            credentials.append(json.loads(creds_path.read_text()))
            assert credentials[-1]["password"] not in config_path.read_text()
            before = creds_path.read_bytes()
            fresh = tmp_path / f"{service}-fresh.json"
            with pytest.raises(FileExistsError):
                provision(
                    fresh, creds_path, service=service, origin=ORIGIN, state_dir=tmp_path / service
                )
            assert not fresh.exists()
            assert creds_path.read_bytes() == before
    assert credentials[0]["username"] != credentials[1]["username"]
    assert credentials[0]["password"] != credentials[1]["password"]
    assert configs[0]["session_secret"] != configs[1]["session_secret"]
    assert configs[0]["password_hash"] != configs[1]["password_hash"]
    assert capsys.readouterr() == ("", "")


def test_cli_fails_without_serving_contract(config, tmp_path, capsys):
    path = config_file(config, tmp_path / "auth.json")
    with pytest.raises(SystemExit) as exc:
        main(["--config", str(path)])
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert PASSWORD not in output.err
    assert config.session_secret not in output.err


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: Path):
        super().__init__("localhost", timeout=3)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self.path))


def unix_request(
    path: Path, method="GET", route="/_auth/check", *, cookies=None, form=None, headers=None
):
    request_headers = {"X-Original-Method": "GET", **(headers or {})}
    if cookies:
        request_headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
    body = urlencode(form) if form is not None else None
    if method == "POST":
        request_headers.setdefault("Origin", ORIGIN)
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    with closing(UnixHTTPConnection(path)) as connection:
        connection.request(method, route, body=body, headers=request_headers)
        response = connection.getresponse()
        result = Result(response.status, response.getheaders(), response.read().decode())
    assert result.header("Cache-Control") == "no-store, max-age=0"
    return result


@contextmanager
def running_gateway(config: Config, config_path: Path, socket_path: Path):
    pytest.importorskip("waitress")
    group = grp.getgrgid(os.getegid()).gr_name
    process = subprocess.Popen(
        [
            sys.executable,
            str(GATEWAY),
            "--config",
            str(config_path),
            "--socket",
            str(socket_path),
            "--socket-group",
            group,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("gateway process exited before opening its Unix socket")
            try:
                if unix_request(socket_path).status == 401:
                    break
            except OSError:
                time.sleep(0.02)
        else:
            pytest.fail("gateway did not start within five seconds")
        yield process
    finally:
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        assert PASSWORD not in stdout + stderr
        assert config.session_secret not in stdout + stderr


def test_real_unix_http_login_restart_logout_replay_and_socket_permissions(config, tmp_path):
    path = config_file(config, tmp_path / "auth.json")
    socket_path = tmp_path / "auth.sock"
    browser = Browser(Gateway(config))
    with running_gateway(config, path, socket_path):
        assert stat.S_ISSOCK(socket_path.stat().st_mode)
        assert stat.S_IMODE(socket_path.stat().st_mode) == 0o660
        assert socket_path.stat().st_gid == os.getegid()
        login = unix_request(socket_path, route="/_auth/login")
        browser.save_cookies(login)
        csrf = csrf_value(login)
        result = unix_request(
            socket_path,
            "POST",
            "/_auth/login",
            cookies=browser.cookies,
            form={
                "username": config.username,
                "password": PASSWORD,
                "csrf": csrf,
            },
        )
        assert result.status == 303
        browser.save_cookies(result)
        token = browser.cookies[config.cookie_name]
        assert unix_request(socket_path, cookies=browser.cookies).status == 204
        assert (
            unix_request(
                socket_path,
                cookies=browser.cookies,
                headers={
                    "X-Original-Method": "POST",
                    "X-Original-Origin": "https://8.133.175.124:9443",
                },
            ).status
            == 403
        )
    # SIGTERM leaves a stale socket; startup must safely recover it and keep sessions.
    with running_gateway(config, path, socket_path) as process:
        assert unix_request(socket_path, cookies=browser.cookies).status == 204
        duplicate = subprocess.run(
            [
                sys.executable,
                str(GATEWAY),
                "--config",
                str(path),
                "--socket",
                str(socket_path),
                "--socket-group",
                grp.getgrgid(os.getegid()).gr_name,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert duplicate.returncode == 1
        assert process.poll() is None
        assert unix_request(socket_path, cookies=browser.cookies).status == 204
        confirmation = unix_request(socket_path, route="/_auth/logout", cookies=browser.cookies)
        browser.save_cookies(confirmation)
        csrf = csrf_value(confirmation)
        assert (
            unix_request(
                socket_path, "POST", "/_auth/logout", cookies=browser.cookies, form={"csrf": csrf}
            ).status
            == 303
        )
        assert unix_request(socket_path, cookies={config.cookie_name: token}).status == 401
    with running_gateway(config, path, socket_path):
        assert unix_request(socket_path, cookies={config.cookie_name: token}).status == 401
