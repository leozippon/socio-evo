# Private WebUI deployment

This directory is the canonical host deployment for CornerHead and socio-evo on the Debian frontend `cornerhead` (`root@8.133.175.124`). nginx terminates HTTPS, serves protected static releases, and checks a separate authentication process for each service. No containers or research processes run on this host.

| Service | Browser address | Static site | Backend |
| --- | --- | --- | --- |
| CornerHead | `https://8.133.175.124:20817/` | `/opt/cornerhead/site` | nginx → `127.0.0.1:38889` → existing reverse SSH tunnel → MacroQuant's private Unix socket |
| socio-evo | `https://8.133.175.124:20131/` | `/opt/socio-evo/site` | Published JSON bundle; no live research API |

The public endpoints require a valid login, including static assets and API requests. Anonymous browser navigation goes to the login form; API and file requests receive 401, not a successful HTML response. An unavailable authentication process fails closed. CornerHead's SSE proxy remains unbuffered. The compute-host API must remain UDS-only in its 0700 runtime directory; do not add a debugging TCP bridge.

## Install and update

This provisioner targets the already bootstrapped host, with nginx (including `auth_request`), nftables, Python 3.11+, `python3-venv`, curl, OpenSSL and existing root SSH access. The existing `inet filter` input chain and CornerHead reverse tunnel must be present for the first migration. It deliberately does not bootstrap SSH policy, install cloud agents, or replace unrelated access keys. Inspect the host and its firewall before running it elsewhere.

From the socio-evo checkout:

```bash
ops/webui/provision.sh cornerhead
```

`PUSH_SSH` can supply SSH options. `--prepare-only` creates the private CA, service accounts, separate credentials/configuration, protected release layout and service units without opening public ports. Provisioning does not rotate existing credentials or replace an existing CA. The complete command activates authentication/TLS, verifies valid login, Origin enforcement and session persistence locally, opens the two input ports, then uses a new SSH connection to cancel a five-minute rollback timer. If activation fails, the timer restores the preceding nginx and owned firewall configuration; inspect `journalctl -u webui-rollback` before retrying. A second activation is refused while its rollback timer is still active.

`/var/backups/webui/pre-migration.tar.gz` is one protected compact backup of the initial sites and relevant configuration. It is retained rather than recopied on each provision. The short-lived activation snapshot is deleted after confirmation. Nothing under `/opt/hangzhou-compute`, unrelated SSH access, cloud agents or experiments is cleaned up.

Push a stable, already published socio-evo bundle:

```bash
frontend/deploy/push.sh cornerhead build/site
```

Push CornerHead assets from MacroQuant:

```bash
ops/webui/webui_stack.sh sync
```

Both delegate to `push.sh`: only changed files are transferred, unchanged files are hard-linked, every file is checksum-verified, and `site` switches by one atomic rename. Production pushes require root and force `root:www-data`, 0750 directories and 0640 files; local uid/mode metadata cannot make published research readable to other host accounts. One previous release is retained for rollback; older releases are removed only after a successful switch. Do not publish into the upload source while a push is running. A custom fourth `ROOT` in the shared push command is a development/test target, not a protected production layout.

To roll back assets, use root to atomically replace `site` with a link to the retained release, then verify the site. Never edit files shared by hard links in place. CornerHead's old `static` path and both old 8080/8090 listeners are obsolete; configuration comes from these templates and `frontend/deploy/nginx-site.conf`, not the retired MacroQuant nginx template.

MacroQuant's `frontend_setup.sh` remains an explicit compatibility entry point. It preserves `FRONTEND`, `SSH_IDENTITY` and `HUB_PUBKEY_FILE`: the key is checked and appended with reverse-listen-only restrictions if missing, never substituted for the existing key list. `SOCIO_EVO_REPO` locates this checkout and `PUBLIC_IP` specifies the TLS origin. The old behavior of installing packages, rebuilding SSH policy and flushing the host firewall is intentionally retired, not silently reimplemented. Existing operator SSH keys remain installed, but old forwards to 8080 no longer provide a UI.

## Credentials, trust and sessions

Each service has its own generated username/password, password hash, session secret and session database. Plaintext credentials stay in root-only `/etc/webui/credentials/{cornerhead,socio-evo}.json`; do not paste them into logs or commit them. Auth config is owned by its dedicated no-login account, mode 0600, under `/etc/webui/SERVICE/`; state is private 0700 under `/var/lib/webui/SERVICE/`. The gateway runs through one `webui-auth@SERVICE.service` template and binds only `/run/webui-SERVICE/auth.sock`. Service users have their own primary groups, not `www-data` membership. The setgid runtime directory gives nginx traversal and socket access, not access to credentials/state. Site releases are readable by root and nginx, not by either auth account.

The IP certificate is signed by a private CA, not a browser-public issuer. Retrieve only the public CA certificate over the verified SSH connection:

```bash
install -d -m 700 "$HOME/.config/private-webui"
scp cornerhead:/opt/webui-auth/public/ca.crt "$HOME/.config/private-webui/ca.crt"
# Optional private credential retrieval; keep this directory and these files private.
(umask 077; scp cornerhead:/etc/webui/credentials/cornerhead.json "$HOME/.config/private-webui/cornerhead.json")
(umask 077; scp cornerhead:/etc/webui/credentials/socio-evo.json "$HOME/.config/private-webui/socio-evo.json")
```

Import the CA into the browser/OS trust store only on intended clients, then open the exact HTTPS addresses above and sign in. Trusting a CA authorizes its issuer; protect it accordingly. Never bypass the warning with `curl -k`. Command-line verification uses `curl --cacert ...`. Private CA and server keys remain root-only in `/etc/webui/tls/`. The CA is valid for ten years and the server certificate for 397 days from creation; inspect actual expiry with `openssl x509 -in /opt/webui-auth/public/ca.crt -noout -dates` and the root-readable `/etc/webui/tls/server.crt`. Renew the leaf certificate before expiry using the existing CA, preserving the IP SAN; check the new certificate with `openssl verify -CAfile /etc/webui/tls/ca.crt -verify_ip 8.133.175.124 ...`, atomically install it, and run `nginx -t` before reloading. Replace the CA only as an explicit trust migration on every client.

A successful login issues a Secure, HttpOnly, host-only, SameSite=Lax cookie with a 30-day lifetime. Session expiry is fixed, not extended on each request; sessions survive gateway restarts. Visit `/_auth/logout` and confirm the form to revoke that session server-side. Login/logout forms carry a short-lived CSRF token. Password or identity changes invalidate old sessions; coordinate intentional credential rotation rather than deleting only the plaintext credential file.

Cookies are not port-scoped. The services use distinct `__Host-cornerhead_session` and `__Host-socio-evo_session` names, plus corresponding `_csrf` cookies. nginx sends only the current service's two cookies to that gateway and strips all Cookie/Authorization headers before CornerHead's upstream. Unsafe methods require the configured HTTPS Origin including its port; another port on the same IP is not an authorized Origin. root and nginx are trusted boundary accounts; this does not protect against root compromise.

## Firewall and verification

Host input preserves existing SSH/DHCP/ICMP and unrelated rules, with one named admission rule for the two HTTPS ports added after local auth/TLS checks. The deployment replaces only its dedicated `inet webui` guard table and the retired CornerHead-only guard table, never flushes the whole ruleset. Persistent per-table reloads are atomic and idempotent. nftables and the guard load before networking/nginx; nginx requires the guard and starts after the auth units. Auth restarts do not stop nginx; requests fail closed during an auth outage. Stopping nftables does not flush protections.

Local output restrictions admit only root/nginx to 20817, 20131 and raw tunnel 38889. Destination matching covers all host addresses (including IPv6), loopback ranges and the public NAT IP, not just packets on `lo`; the same ports on unrelated remote hosts are unaffected. Old 8080/8090 destinations are rejected. A local login does not exempt admin, nobody or either service account from these kernel checks.

On the frontend, validate real TLS, credentials, cookie attributes, data, exact-port Origin checks, cross-service rejection and logout without exposing secrets:

```bash
ssh cornerhead 'python3 /opt/webui-auth/deploy/verify.py --local --restart'
ssh cornerhead 'python3 /opt/webui-auth/deploy/check_isolation.py'
ssh cornerhead 'nginx -t && nft -c -f /etc/nftables.conf'
ssh cornerhead 'systemctl status webui-firewall webui-auth@cornerhead webui-auth@socio-evo nginx'
```

`--local` maps the real certificate/origin to loopback; omit it to test the public NAT path from the host. Rate limits apply to diagnostic logins too: avoid repeated rapid verification. A successful localhost check does not establish Internet reachability. From an external client with the private files retrieved above, run `python3 ops/webui/verify.py --ca "$HOME/.config/private-webui/ca.crt" --credentials-dir "$HOME/.config/private-webui"` to verify both real public endpoints without bypassing TLS. Cloud security-group/firewall admission for TCP 20817/20131 may also be required; report cloud timeouts separately from host-level success.

Scripted checks set Origin explicitly and cannot establish that a browser generates it. The gateway and nginx both use `Referrer-Policy: same-origin` so native login/logout form POSTs retain the exact HTTPS Origin, while cross-origin referrers remain suppressed. Missing, `null` and wrong-port Origins are still rejected.

An opt-in regression uses an existing Chromium executable, Node.js, OpenSSL and the test Python environment; it installs nothing:

```bash
CHROMIUM=/absolute/path/to/chrome python -m pytest tests/frontend/test_native_forms.py -q
```

It serves an isolated TLS fixture with test-only credentials and the actual gateway plus nginx's referrer policy, then checks native dummy login (401, not 403), authenticated login, logout confirmation and replay rejection. Browser submissions use the page's real form and cookie jar without overriding Origin. The fixture scopes a temporary certificate exception to its generated certificate's public key; it does not test CA trust or Safari.

The same bounded browser probe can check the deployed services. Run it separately from rapid scripted probes, allowing at least one minute after other login diagnostics; nginx's existing login rate limit also covers form-page GETs:

```bash
CHROMIUM=/absolute/path/to/chrome node tests/frontend/native_form_check.mjs \
  cornerhead=https://8.133.175.124:20817 socio-evo=https://8.133.175.124:20131 </dev/null
```

Optional private JSON on stdin (`{"SERVICE":{"username":"...","password":"..."}}`) enables authenticated login/logout checks; never put credentials in command arguments or tracked files. `WEBUI_BROWSER_PROXY` optionally sets a browser proxy. Use the browser/OS CA trust store for normal TLS; `WEBUI_BROWSER_SPKI` is only a narrowly scoped certificate-public-key exception for diagnostics and is not evidence of CA validation. Pair such a diagnostic with the CA-validated HTTP verifier above. The probe uses inherited private pipes for Chromium's DevTools protocol, with no DevTools TCP port. It reports only statuses and Origins and removes its temporary profile. Actual Safari must be checked separately on an available Apple client.

For ordinary source-host diagnostics, MacroQuant's `webui_stack.sh status` checks its UDS, loaded-code fingerprint and authenticated frontend API path. Restart only the relevant UI/tunnel; never restart experiments to fix dashboard access. Check source-host listeners with `ss -lntp '( sport = :38888 or sport = :8765 )'`, identify the process and checkout before removing any legacy listener, and do not terminate an unrelated project's service blindly.
