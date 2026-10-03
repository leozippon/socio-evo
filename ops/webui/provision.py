#!/usr/bin/env python3
"""Root-only, host-specific deployment of the two WebUIs. See README.md."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import tarfile

from verify import wait_for_gateway

HERE = Path(__file__).resolve().parent
ETC = Path('/etc/webui')
BACKUP = Path('/var/backups/webui')
SERVICES = {'cornerhead': 20817, 'socio-evo': 20131}
RESTORE_PATHS = [
    '/etc/nginx/sites-available/cornerhead', '/etc/nginx/sites-available/socio-evo',
    '/etc/nginx/sites-enabled/cornerhead', '/etc/nginx/sites-enabled/socio-evo',
    '/etc/nginx/conf.d/webui.conf', '/etc/nftables.conf',
    '/etc/systemd/system/nginx.service.d/webui.conf',
    '/etc/systemd/system/nftables.service.d/webui.conf',
    '/etc/systemd/system/webui-auth@.service', '/etc/systemd/system/webui-firewall.service',
    '/etc/tmpfiles.d/webui.conf',
]


def run(*args: str, capture: bool = False, input: str | None = None) -> str:
    result = subprocess.run(args, check=True, text=True, input=input,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else ''


def write(path: Path, text: str, mode: int = 0o600, group: str = 'root') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.new')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, 'w') as output:
        output.write(text)
    os.chmod(tmp, mode)
    shutil.chown(tmp, user='root', group=group)
    tmp.replace(path)


def directory(path: Path, owner: str = 'root', group: str = 'root', mode: int = 0o700) -> None:
    path.mkdir(parents=True, exist_ok=True)
    shutil.chown(path, user=owner, group=group)
    path.chmod(mode)


def backup() -> None:
    directory(BACKUP)
    archive = BACKUP / 'pre-migration.tar.gz'
    if archive.exists():
        return
    existing = [p for p in RESTORE_PATHS if Path(p).exists() or Path(p).is_symlink()]
    with tarfile.open(archive, 'w:gz', dereference=False) as output:
        for name in existing + ['/opt/cornerhead', '/opt/socio-evo']:
            if Path(name).exists():
                output.add(name, arcname=name.lstrip('/'))
    archive.chmod(0o600)


def restrict_release_tree(root: Path) -> None:
    for path in [root, *root.rglob('*')]:
        if path.is_symlink():
            continue
        if not (path.is_dir() or path.is_file()):
            raise RuntimeError(f'unsupported release entry: {path}')
        shutil.chown(path, user='root', group='www-data')
        path.chmod(0o750 if path.is_dir() else 0o640)


def migrate_site(service: str) -> None:
    root = Path('/opt') / service
    directory(root, group='www-data', mode=0o750)
    directory(root / 'releases', group='www-data', mode=0o750)
    if service == 'cornerhead' and not (root / 'site').is_symlink():
        old = root / 'static'
        if not old.is_dir() or old.is_symlink():
            raise RuntimeError('expected the existing CornerHead static directory')
        release = root / 'releases' / 'pre-migration'
        old.rename(release)
        (root / 'site').symlink_to('releases/pre-migration')
        # Keep the old private listener functional until activation replaces its config.
        old.symlink_to('site')
    site = root / 'site'
    if not site.is_symlink():
        raise RuntimeError(f'{site} must be a release symlink')
    current = site.resolve(strict=True)
    if current.parent != root / 'releases':
        raise RuntimeError(f'{site} points outside releases')
    if service == 'cornerhead' and current.name == 'pre-migration':
        # The existing static tree becomes an intentional rollback release, not the new current name.
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-migration'
        release = root / 'releases' / stamp
        shutil.copytree(current, release, copy_function=os.link)
        restrict_release_tree(release)
        link = root / '.site-migration'
        link.symlink_to(f'releases/{stamp}')
        link.replace(site)
    restrict_release_tree(root / 'releases')


def render(text: str, **values: str) -> str:
    for key, value in values.items():
        text = text.replace(f'@{key}@', value)
    if re.search(r'@[A-Z_]+@', text):
        raise RuntimeError('unresolved deployment template')
    return text


def create_auth(service: str, public_ip: str) -> tuple[str, str]:
    """Use the gateway's canonical config generator/hash implementation."""
    spec = importlib.util.spec_from_file_location('webui_gateway', HERE / 'gateway.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('gateway.py is required before provisioning authentication')
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve their defining module through sys.modules.
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    origin = f'https://{public_ip}:{SERVICES[service]}'
    config = ETC / service / 'auth.json'
    credential = ETC / 'credentials' / f'{service}.json'
    if not config.exists():
        module.provision(config, credential, service=service, origin=origin,
                         state_dir=Path('/var/lib/webui') / service)
    data = json.loads(config.read_text())
    if data['service'] != service or data['origin'] != origin or data['session_days'] != 30:
        raise RuntimeError(f'existing auth configuration does not match {service}/{origin}')
    validated = module.Config(**dict(data, state_dir=Path(data['state_dir'])))
    shutil.chown(config, user=service, group=service)
    config.chmod(0o600)
    if credential.exists():
        shutil.chown(credential, user='root', group='root')
        credential.chmod(0o600)
    return validated.cookie_name, validated.csrf_cookie_name


def certificates(public_ip: str) -> None:
    tls = ETC / 'tls'
    directory(tls)
    ca_key, ca_cert = tls / 'ca.key', tls / 'ca.crt'
    if ca_key.exists() != ca_cert.exists():
        raise RuntimeError('incomplete private CA; restore it rather than silently replacing trust')
    if not ca_key.exists():
        run('openssl', 'req', '-x509', '-newkey', 'rsa:3072', '-nodes',
            '-keyout', str(ca_key), '-out', str(ca_cert), '-days', '3650',
            '-subj', '/CN=Cornerhead Private WebUI CA',
            '-addext', 'basicConstraints=critical,CA:TRUE,pathlen:0',
            '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
    key, cert = tls / 'server.key', tls / 'server.crt'
    if key.exists() != cert.exists():
        raise RuntimeError('incomplete server certificate; restore or explicitly renew it')
    if not key.exists():
        csr = tls / 'server.csr'
        run('openssl', 'req', '-new', '-newkey', 'rsa:3072', '-nodes',
            '-keyout', str(key), '-out', str(csr), '-subj', f'/CN={public_ip}')
        extension = tls / 'server.ext'
        write(extension, f'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName=IP:{public_ip}\n')
        run('openssl', 'x509', '-req', '-in', str(csr), '-CA', str(ca_cert),
            '-CAkey', str(ca_key), '-CAcreateserial', '-out', str(cert),
            '-days', '397', '-sha256', '-extfile', str(extension))
        csr.unlink()
        extension.unlink()
    for path in tls.iterdir():
        path.chmod(0o600 if path.name.endswith(('.key', '.srl')) else 0o644)
    run('openssl', 'verify', '-CAfile', str(ca_cert), '-verify_ip', public_ip, str(cert))
    # Only the public trust anchor is exported outside the private TLS directory.
    directory(Path('/opt/webui-auth/public'), mode=0o755)
    shutil.copyfile(ca_cert, '/opt/webui-auth/public/ca.crt')
    Path('/opt/webui-auth/public/ca.crt').chmod(0o644)


def firewall(public_ip: str) -> None:
    www_uid = pwd.getpwnam('www-data').pw_uid
    text = f'''add table inet webui
flush table inet webui
table inet webui {{
    chain local_out {{
        type filter hook output priority -10; policy accept;
        # fib covers every host address (IPv4/IPv6), not just the loopback interface.
        fib daddr type local tcp dport {{ 20131, 20817, 38889 }} meta skuid != {{ 0, {www_uid} }} counter reject with tcp reset
        ip daddr 127.0.0.0/8 tcp dport {{ 20131, 20817, 38889 }} meta skuid != {{ 0, {www_uid} }} counter reject with tcp reset
        ip daddr {public_ip} tcp dport {{ 20131, 20817, 38889 }} meta skuid != {{ 0, {www_uid} }} counter reject with tcp reset
        fib daddr type local tcp dport {{ 8080, 8090 }} counter reject with tcp reset
        ip daddr {public_ip} tcp dport {{ 8080, 8090 }} counter reject with tcp reset
    }}
}}
'''
    write(ETC / 'firewall.nft', text)
    run('nft', '-c', '-f', str(ETC / 'firewall.nft'))


def prepare(public_ip: str) -> None:
    backup()
    directory(ETC, mode=0o755)
    directory(ETC / 'credentials')
    directory(Path('/var/lib/webui'), mode=0o711)
    directory(Path('/opt/webui-auth'), mode=0o755)
    for service in SERVICES:
        try:
            account = pwd.getpwnam(service)
            if account.pw_shell != '/usr/sbin/nologin':
                raise RuntimeError(f'{service} is not a no-login service user')
            if 'www-data' in run('id', '-nG', service, capture=True).split():
                raise RuntimeError(f'{service} must not belong to nginx group')
        except KeyError:
            run('useradd', '--system', '--user-group', '--no-create-home',
                '--home-dir', f'/var/lib/webui/{service}', '--shell', '/usr/sbin/nologin', service)
        directory(ETC / service, group=service, mode=0o750)
        directory(Path('/var/lib/webui') / service, owner=service, group=service)
        migrate_site(service)
    certificates(public_ip)
    firewall(public_ip)
    cookies = {service: create_auth(service, public_ip) for service in SERVICES}
    if len({c for pair in cookies.values() for c in pair}) != 4 or not all(
        c.startswith('__Host-') for pair in cookies.values() for c in pair
    ):
        raise RuntimeError('gateway cookies must be distinct __Host- cookies')
    write(ETC / 'nginx-common.conf', render((HERE / 'nginx-common.conf').read_text(),
          CORNERHEAD_COOKIE=cookies['cornerhead'][0], CORNERHEAD_CSRF=cookies['cornerhead'][1],
          SOCIO_COOKIE=cookies['socio-evo'][0], SOCIO_CSRF=cookies['socio-evo'][1]), 0o644)
    write(ETC / 'nginx-security.conf', (HERE / 'nginx-security.conf').read_text(), 0o644)
    for service in SERVICES:
        variable = service.replace('-', '_') + '_cookie'
        # Config contains no secrets; nginx can traverse only these rendered include files.
        # Auth JSON stays in a separate service-only directory, with nginx includes elsewhere.
        directory(ETC / 'nginx' / service, mode=0o755)
        for name in ('nginx-auth.conf', 'nginx-auth-proxy.conf'):
            content = render((HERE / name).read_text(), SERVICE=service, COOKIE_VARIABLE=variable)
            content = content.replace(f'/etc/webui/{service}/nginx-auth-proxy.conf',
                                      f'/etc/webui/nginx/{service}/nginx-auth-proxy.conf')
            write(ETC / 'nginx' / service / name, content, 0o644)
        template = (HERE / 'nginx-cornerhead.conf') if service == 'cornerhead' else (HERE / 'nginx-site.conf')
        text = render(template.read_text(), PUBLIC_IP=public_ip)
        text = text.replace(f'/etc/webui/{service}/nginx-auth.conf', f'/etc/webui/nginx/{service}/nginx-auth.conf')
        write(ETC / 'nginx' / service / 'site.conf', text, 0o644)
    write(Path('/etc/tmpfiles.d/webui.conf'), (HERE / 'webui-tmpfiles.conf').read_text(), 0o644)
    run('systemd-tmpfiles', '--create', '/etc/tmpfiles.d/webui.conf')
    for name in ('webui-auth@.service', 'webui-firewall.service'):
        write(Path('/etc/systemd/system') / name, (HERE / name).read_text(), 0o644)
    for unit in ('nginx', 'nftables'):
        write(Path(f'/etc/systemd/system/{unit}.service.d/webui.conf'),
              (HERE / f'{unit}-systemd.conf').read_text(), 0o644)
    shutil.copyfile(HERE / 'gateway.py', '/opt/webui-auth/gateway.py')
    Path('/opt/webui-auth/gateway.py').chmod(0o644)
    run('systemctl', 'daemon-reload')
    print('Prepared protected releases, private CA, separate auth configs, and service units; no public ports opened.')


def arm_rollback() -> None:
    pending = subprocess.run(['systemctl', 'is-active', '--quiet', 'webui-rollback.timer'])
    if pending.returncode == 0:
        raise RuntimeError('an activation rollback is already armed; confirm or roll back that activation first')
    # Every activation has its own configuration snapshot (the compact pre-migration archive is immutable).
    directory(BACKUP / 'activation')
    snapshot = BACKUP / 'activation' / 'config.tar.gz'
    current = [p for p in RESTORE_PATHS if Path(p).exists() or Path(p).is_symlink()]
    with tarfile.open(snapshot, 'w:gz', dereference=False) as archive:
        for path in current:
            archive.add(path, arcname=path.lstrip('/'))
    snapshot.chmod(0o600)
    write(BACKUP / 'activation' / 'paths.json', json.dumps(current))
    rules = run('nft', 'list', 'table', 'inet', 'filter', capture=True)
    rules = 'add table inet filter\nflush table inet filter\n' + rules
    check = subprocess.run(['nft', 'list', 'table', 'inet', 'webui'], capture_output=True, text=True)
    if check.returncode == 0:
        rules += '\nadd table inet webui\nflush table inet webui\n' + check.stdout
    else:
        rules += '\ndelete table inet webui\n'
    old = subprocess.run(['nft', 'list', 'table', 'inet', 'cornerhead'], capture_output=True, text=True)
    if old.returncode == 0:
        rules += '\nadd table inet cornerhead\nflush table inet cornerhead\n' + old.stdout
    write(BACKUP / 'activation' / 'rollback.nft', rules)
    run('systemd-run', '--collect', '--unit=webui-rollback', '--on-active=300',
        '/usr/bin/python3', '-B', str(HERE / 'provision.py'), 'rollback')


def local_checks(public_ip: str, *, authenticated: bool = True) -> None:
    # Test with the real certificate/origin, bypassing only the cloud's NAT path.
    for service, port in SERVICES.items():
        url = f'https://{public_ip}:{port}'
        base = ['curl', '-sS', '--max-time', '10', '--cacert', str(ETC / 'tls/ca.crt'),
                '--resolve', f'{public_ip}:{port}:127.0.0.1']
        code = run(*base, '-o', '/dev/null', '-w', '%{http_code}', url + '/', capture=True)
        if code != '401':
            raise RuntimeError(f'{service}: anonymous static returned {code}, expected 401')
        code = run(*base, '-o', '/dev/null', '-w', '%{http_code}', url + '/_auth/check', capture=True)
        if code != '404':
            raise RuntimeError(f'{service}: auth check must be internal, got {code}')
    if authenticated:
        run('python3', '-B', str(HERE / 'verify.py'), '--local', '--restart', '--public-ip', public_ip)
    run('nginx', '-t')
    run('nft', '-c', '-f', '/etc/nftables.conf')


def activate(public_ip: str) -> None:
    arm_rollback()
    # Restrict local users before changing any listener. This replacement is atomic.
    guard = (ETC / 'firewall.nft').read_text()
    old = subprocess.run(['nft', 'list', 'table', 'inet', 'cornerhead'], capture_output=True)
    if old.returncode == 0:
        guard += '\ndelete table inet cornerhead\n'
    run('nft', '-c', '-f', '-', input=guard)
    run('nft', '-f', '-', input=guard)
    run('systemctl', 'enable', '--now', 'webui-firewall.service')
    for service in SERVICES:
        run('systemctl', 'enable', f'webui-auth@{service}.service')
        run('systemctl', 'restart', f'webui-auth@{service}.service')
        wait_for_gateway(service)
        target = Path(f'/etc/nginx/sites-available/{service}')
        write(target, (ETC / 'nginx' / service / 'site.conf').read_text(), 0o644)
        enabled = Path(f'/etc/nginx/sites-enabled/{service}')
        if enabled.exists() or enabled.is_symlink():
            enabled.unlink()
        enabled.symlink_to(target)
    write(Path('/etc/nginx/conf.d/webui.conf'), 'include /etc/webui/nginx-common.conf;\n', 0o644)
    run('nginx', '-t')
    # Relevant listeners only. Restart closes old workers/listeners, including established SSE.
    run('systemctl', 'restart', 'nginx')
    local_checks(public_ip)
    # Keep all existing filter rules. Add one named rule only after TLS/auth are locally valid.
    live = run('nft', 'list', 'table', 'inet', 'filter', capture=True)
    if 'webui-public' not in live:
        run('nft', 'add', 'rule', 'inet', 'filter', 'input', 'tcp', 'dport',
            '{', '20131', ',', '20817', '}', 'accept', 'comment', '"webui-public"')
        live = run('nft', 'list', 'table', 'inet', 'filter', capture=True)
    # Targeted per-table flushes are atomic and make reload idempotent; never flush ruleset.
    persistent = '# Managed WebUI migration: preserves the existing host filter table.\n'
    persistent += 'add table inet filter\nflush table inet filter\n' + live
    # Persist other tables unchanged rather than silently discarding unrelated live rules.
    tables = json.loads(run('nft', '-j', 'list', 'tables', capture=True))['nftables']
    for entry in tables:
        table = entry.get('table')
        if not table or (table['family'] == 'inet' and table['name'] in ('filter', 'webui', 'cornerhead')):
            continue
        family, name = table['family'], table['name']
        persistent += f'\nadd table {family} {name}\nflush table {family} {name}\n'
        persistent += run('nft', 'list', 'table', family, name, capture=True)
    persistent += '\ninclude "/etc/webui/firewall.nft"\n'
    write(Path('/etc/nftables.conf'), persistent, 0o600)
    run('nft', '-c', '-f', '/etc/nftables.conf')
    print('Activated both TLS/auth listeners; rollback remains armed until a second SSH connection confirms.')


def rollback() -> None:
    active = BACKUP / 'activation'
    original = json.loads((active / 'paths.json').read_text())
    for name in RESTORE_PATHS:
        path = Path(name)
        if path.exists() or path.is_symlink():
            path.unlink()
    with tarfile.open(active / 'config.tar.gz') as archive:
        # Archive is generated locally by root from the fixed allowlist above.
        archive.extractall('/')
    run('nft', '-f', str(active / 'rollback.nft'))
    run('systemctl', 'daemon-reload')
    run('nginx', '-t')
    run('systemctl', 'restart', 'nginx')
    print(f'Rolled back {len(original)} configuration paths and owned firewall tables.')


def confirm(public_ip: str) -> None:
    local_checks(public_ip, authenticated=False)
    run('systemctl', 'stop', 'webui-rollback.timer')
    shutil.rmtree(BACKUP / 'activation')
    # Obsolete path is removed only after old nginx config and references are replaced.
    static = Path('/opt/cornerhead/static')
    if static.is_symlink() and os.readlink(static) == 'site':
        static.unlink()
    elif static.exists():
        raise RuntimeError('unexpected obsolete static path: inspect rather than remove it blindly')
    print('Second SSH connection confirmed; rollback cancelled. Pre-migration backup retained.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'activate', 'confirm', 'rollback'))
    parser.add_argument('--public-ip', default='8.133.175.124')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('must run as root on the frontend host')
    ip = str(ipaddress.IPv4Address(args.public_ip))
    os.umask(0o077)
    if args.action == 'rollback':
        rollback()
    else:
        globals()[args.action](ip)


if __name__ == '__main__':
    main()
