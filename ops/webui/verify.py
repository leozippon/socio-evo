#!/usr/bin/env python3
"""Credential-safe production smoke checks, on the frontend or using private retrieved credentials."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlencode

SERVICES = {'cornerhead': 20817, 'socio-evo': 20131}


def wait_for_gateway(service: str) -> None:
    for _ in range(50):
        result = subprocess.run([
            'curl', '-s', '--max-time', '1', '--unix-socket', f'/run/webui-{service}/auth.sock',
            '-H', 'X-Original-Method: GET', '-o', '/dev/null', '-w', '%{http_code}',
            'http://auth/_auth/check',
        ], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout == '401':
            return
        time.sleep(0.1)
    raise RuntimeError(f'{service}: authentication socket did not become ready')


class Client:
    def __init__(self, service: str, work: Path, public_ip: str, local: bool,
                 ca: Path, credentials_dir: Path):
        self.service, self.work = service, work
        self.credentials_dir = credentials_dir
        self.origin = f'https://{public_ip}:{SERVICES[service]}'
        self.jar = work / 'cookies.txt'
        self.base = ['curl', '-sS', '--max-time', '15', '--cacert', str(ca)]
        if local:
            self.base += ['--resolve', f'{public_ip}:{SERVICES[service]}:127.0.0.1']

    def request(self, path: str, *, method: str = 'GET', form: dict | None = None,
                headers: dict[str, str] | None = None, jar: Path | None = None) -> tuple[int, str, str]:
        head, body = self.work / 'headers.txt', self.work / 'body.txt'
        custom = self.work / 'request-headers.txt'
        custom.write_text(''.join(f'{name}: {value}\n' for name, value in (headers or {}).items()))
        custom.chmod(0o600)
        args = self.base + ['--cookie', str(jar or self.jar), '--cookie-jar', str(self.jar),
                            '-X', method, '-D', str(head), '-o', str(body), '-w', '%{http_code}']
        if headers:
            args += ['--header', '@' + str(custom)]
        payload = None
        if form is not None:
            payload = urlencode(form)
            args += ['--data-binary', '@-', '-H', 'Content-Type: application/x-www-form-urlencoded']
        result = subprocess.run(args + [self.origin + path], input=payload, text=True,
                                capture_output=True, check=True)
        return int(result.stdout), body.read_text(), head.read_text()

    def expect(self, expected: int, path: str, **kwargs) -> tuple[str, str]:
        status, body, headers = self.request(path, **kwargs)
        if status != expected:
            raise RuntimeError(f'{self.service}: {kwargs.get("method", "GET")} {path}: expected {expected}, got {status}')
        if 'cache-control: no-store' not in headers.lower():
            raise RuntimeError(f'{self.service}: response must be no-store')
        return body, headers

    def login(self) -> None:
        self.expect(401, '/')
        self.expect(404, '/_auth/check')
        self.expect(303, '/', headers={'Accept': 'text/html'})
        body, _ = self.expect(200, '/_auth/login')
        match = re.search(r'name="csrf" value="([^"]+)"', body)
        if match is None:
            raise RuntimeError('missing login CSRF form')
        credential_path = self.credentials_dir / f'{self.service}.json'
        info = credential_path.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise RuntimeError('credentials must be owned by the caller with private permissions')
        credential = json.loads(credential_path.read_text())
        form = {'csrf': match[1], 'username': credential['username'], 'password': credential['password']}
        _, headers = self.expect(303, '/_auth/login', method='POST', form=form,
                                 headers={'Origin': self.origin})
        cookie = next((line for line in headers.splitlines() if line.lower().startswith('set-cookie: __host-')
                       and f'__Host-{self.service}_session=' in line), '')
        if not all(word in cookie for word in ('Secure', 'HttpOnly', 'SameSite=Lax', 'Path=/', 'Max-Age=2592000')):
            raise RuntimeError(f'{self.service}: invalid 30-day host cookie attributes')
        if 'Domain=' in cookie:
            raise RuntimeError('host cookie must not declare a Domain')
        self.expect(200, '/')

    def check_data(self) -> None:
        if self.service == 'cornerhead':
            body, _ = self.expect(200, '/api/health')
            if json.loads(body).get('code_current') is not True:
                raise RuntimeError('CornerHead source code fingerprint is stale')
            self.expect(200, '/static/app.js')
            safe = '/api/health'
        else:
            body, _ = self.expect(200, '/data/index.json')
            if json.loads(body).get('format') != 1:
                raise RuntimeError('unexpected socio bundle format')
            self.expect(200, '/js/app.js')
            safe = '/index.html'
        self.expect(404, '/.env')
        # No state-changing endpoint is invoked. Conflicting metadata must not bypass Origin.
        other_port = SERVICES['socio-evo' if self.service == 'cornerhead' else 'cornerhead']
        wrong = self.origin.rsplit(':', 1)[0] + f':{other_port}'
        for headers in ({}, {'Origin': wrong}, {'Origin': wrong, 'X-Original-Method': 'GET',
                                                'X-Original-Origin': self.origin}):
            self.expect(403, safe, method='POST', headers=headers)
        self.expect(405, safe, method='POST', headers={'Origin': self.origin})

    def logout(self) -> None:
        old = self.work / 'previous-cookies.txt'
        shutil.copyfile(self.jar, old)
        old.chmod(0o600)
        body, _ = self.expect(200, '/_auth/logout')
        match = re.search(r'name="csrf" value="([^"]+)"', body)
        if match is None:
            raise RuntimeError('missing logout confirmation form')
        self.expect(303, '/_auth/logout', method='POST', form={'csrf': match[1]}, headers={'Origin': self.origin})
        self.expect(401, '/', jar=old)


def verify(services: list[str], public_ip: str, local: bool, restart: bool,
           ca: Path, credentials_dir: Path) -> None:
    with tempfile.TemporaryDirectory(prefix='webui-check-') as name:
        work = Path(name)
        clients = {}
        for service in services:
            directory = work / service
            directory.mkdir(mode=0o700)
            client = clients[service] = Client(service, directory, public_ip, local, ca, credentials_dir)
            client.login()
            client.check_data()
            if restart:
                subprocess.run(['systemctl', 'restart', f'webui-auth@{service}.service'], check=True)
                # A stale socket pathname does not prove readiness after restart.
                wait_for_gateway(service)
                client.expect(200, '/')
            print(f'{service}: verified TLS, anonymous denial, login/cookie, static/data, exact-port Origin' +
                  (', restart persistence' if restart else ''))
        if len(clients) == 2:
            # A cookie jar contains cookies for the IP, not the port. Service A alone cannot enter B.
            for service, client in clients.items():
                peer = clients['socio-evo' if service == 'cornerhead' else 'cornerhead']
                cross_dir = work / f'cross-{service}'
                cross_dir.mkdir(mode=0o700)
                cross = Client(service, cross_dir, public_ip, local, ca, credentials_dir)
                cross.expect(401, '/', jar=peer.jar)
            print('cross-service cookies: rejected')
        for client in clients.values():
            client.logout()
        print('logout: server-side revocation verified')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', choices=SERVICES)
    parser.add_argument('--public-ip', default='8.133.175.124')
    parser.add_argument('--local', action='store_true', help='resolve the real TLS origin to loopback')
    parser.add_argument('--restart', action='store_true', help='verify issued cookies survive auth restart')
    parser.add_argument('--ca', type=Path, default=Path('/etc/webui/tls/ca.crt'))
    parser.add_argument('--credentials-dir', type=Path, default=Path('/etc/webui/credentials'),
                        help='private retrieved credential directory for an external verification')
    args = parser.parse_args()
    if args.restart and os.geteuid() != 0:
        parser.error('root on the frontend is required for --restart')
    os.umask(0o077)
    try:
        verify([args.service] if args.service else list(SERVICES), args.public_ip, args.local, args.restart,
               args.ca, args.credentials_dir)
    except RuntimeError as exc:
        parser.exit(1, f'WebUI verification failed: {exc}\n')
    except (OSError, ValueError, subprocess.CalledProcessError):
        parser.exit(1, 'WebUI verification failed; check TLS, auth services, and protected configuration (no secrets printed).\n')


if __name__ == '__main__':
    main()
