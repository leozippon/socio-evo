#!/usr/bin/env python3
"""Reproduce host UID/address and file boundaries without reading any private contents."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

USERS = ('admin', 'nobody', 'cornerhead', 'socio-evo')
PORTS = (20817, 20131, 38889, 8080, 8090)


def main() -> None:
    if os.geteuid() != 0:
        raise SystemExit('run as root on the frontend')
    addresses = {'127.0.0.1', '127.0.0.2', '::1', '8.133.175.124'}
    interfaces = json.loads(subprocess.check_output(['ip', '-j', 'address'], text=True))
    for interface in interfaces:
        for entry in interface['addr_info']:
            address = entry['local']
            if entry['family'] == 'inet6' and entry.get('scope') == 'link':
                address += '%' + interface['ifname']
            addresses.add(address)
    probe = '''import socket,sys
address,port=sys.argv[1],int(sys.argv[2])
try:
    connection=socket.create_connection((address,port),timeout=1)
except OSError:
    sys.exit(0)
connection.close()
sys.exit(1)
'''
    checks = 0
    for user in USERS:
        for address in sorted(addresses):
            for port in PORTS:
                result = subprocess.run(['runuser', '-u', user, '--', 'python3', '-c', probe,
                                         address, str(port)], capture_output=True, text=True)
                if result.returncode != 0:
                    raise RuntimeError(f'{user} could connect to {address}:{port}')
                checks += 1
        for service in ('cornerhead', 'socio-evo'):
            paths = [f'/opt/{service}/site/index.html', f'/var/lib/webui/{service}/sessions.sqlite3',
                     f'/etc/webui/credentials/{service}.json', '/etc/webui/tls/server.key', '/etc/webui/tls/ca.key']
            if user != service:
                paths.append(f'/etc/webui/{service}/auth.json')
            for path in paths:
                if user == service and path.startswith(f'/var/lib/webui/{service}/'):
                    continue  # its own session database is intentionally readable
                if not Path(path).exists():
                    raise RuntimeError(f'expected deployed file is missing: {path}')
                result = subprocess.run(['runuser', '-u', user, '--', 'test', '-r', path])
                if result.returncode == 0:
                    raise RuntimeError(f'{user} could read {path}')
                checks += 1
    print(f'UID/address/file isolation: {checks} checks passed across {len(addresses)} host destinations.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
