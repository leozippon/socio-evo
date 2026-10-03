#!/usr/bin/env bash
# Upload the canonical deployment sources, prepare, activate, and confirm via a NEW SSH session.
set -euo pipefail
if [[ $# -lt 1 ]]; then
    echo "usage: $0 HOST [PUBLIC_IP] [--prepare-only] [--hub-pubkey FILE]" >&2; exit 2
fi
host=$1; shift
ip=8.133.175.124
if [[ $# -gt 0 && $1 != --* ]]; then ip=$1; shift; fi
prepare_only=0
hub_key=
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prepare-only) prepare_only=1; shift;;
        --hub-pubkey) [[ $# -ge 2 ]] || exit 2; hub_key=$2; shift 2;;
        *) echo "unknown option: $1" >&2; exit 2;;
    esac
done
HERE=$(cd "$(dirname "$0")" && pwd)
[[ -f "$HERE/gateway.py" ]] || { echo "gateway.py must be available before provisioning" >&2; exit 1; }
python3 -c 'import ipaddress,sys; ipaddress.IPv4Address(sys.argv[1])' "$ip"
remote() {
    # shellcheck disable=SC2086
    ${PUSH_SSH:-ssh} "$host" "$1"
}
remote 'install -d -o root -g root -m 700 /opt/webui-auth/deploy'
tar --exclude=__pycache__ --exclude='*.pyc' -cf - -C "$HERE" . -C "$HERE/../../frontend/deploy" nginx-site.conf \
    | remote 'umask 077; tar -xf - -C /opt/webui-auth/deploy --no-same-owner --no-same-permissions; chmod -R go-rwx /opt/webui-auth/deploy'
remote 'set -eu; if [ ! -x /opt/webui-auth/venv/bin/python ]; then python3 -m venv /opt/webui-auth/venv; fi; /opt/webui-auth/venv/bin/pip install --disable-pip-version-check --index-url https://pypi.org/simple -r /opt/webui-auth/deploy/requirements.txt'
remote "python3 -B /opt/webui-auth/deploy/provision.py prepare --public-ip $ip"
if [[ -n $hub_key ]]; then
    [[ -s $hub_key ]] || { echo "missing hub public key: $hub_key" >&2; exit 2; }
    # Preserve every existing key and SSH policy. Append this restricted tunnel key only if absent.
    remote 'python3 -B /opt/webui-auth/deploy/install_tunnel_key.py' < "$hub_key"
fi
if [[ $prepare_only = 1 ]]; then
    echo 'Prepared only. To activate: rerun without --prepare-only.'; exit 0
fi
remote "python3 -B /opt/webui-auth/deploy/provision.py activate --public-ip $ip"
# Fresh SSH connection proves access survives before cancelling the rollback timer.
remote "python3 -B /opt/webui-auth/deploy/provision.py confirm --public-ip $ip"
echo "Deployed: https://$ip:20817/ and https://$ip:20131/"
echo 'Private credentials: /etc/webui/credentials/ on the frontend; CA: /opt/webui-auth/public/ca.crt'
