#!/usr/bin/env python3
"""Append a missing restricted hub public key; never replace existing SSH access."""
import os
from pathlib import Path
import subprocess
import sys

if os.geteuid() != 0:
    raise SystemExit('run as root on the frontend')
key = sys.stdin.read().strip()
parts = key.split()
if len(parts) < 2 or parts[0] not in ('ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256') or '\n' in key:
    raise SystemExit('expected one OpenSSH public key')
path = Path('/etc/ssh/authorized_keys.d/cornerhead')
if not path.exists():
    raise SystemExit('missing central tunnel key file; bootstrap SSH separately and explicitly')
old = path.read_text()
if any(parts[1] in line.split() for line in old.splitlines() if not line.startswith('#')):
    print('Existing hub key preserved.')
else:
    text = old.rstrip() + '\nrestrict,port-forwarding,permitlisten="127.0.0.1:38889" ' + key + '\n'
    tmp = path.with_suffix('.new')
    tmp.write_text(text)
    tmp.chmod(0o644)
    tmp.replace(path)
    subprocess.run(['sshd', '-t'], check=True)
    print('Added one restricted hub key; unrelated SSH access unchanged.')
