# Project log — 2026-10-03

## Private WebUI deployment

Completed the protected deployment on `cornerhead`: CornerHead at `https://8.133.175.124:20817/` and socio-evo at `https://8.133.175.124:20131/`. The user chose a private CA and separate generated credentials for the two services. Public access requires trusting that CA on the client and signing in.

nginx terminates HTTPS and protects both services through a shared authentication implementation, with separate per-service identities, configuration and session databases. Sessions use 30-day, server-revocable cookies and survive authentication-process restarts. CornerHead retains its existing private Unix socket and reverse SSH backend path; socio-evo serves the static published bundle without a live research API. Both use consistent `/opt/SERVICE/releases` and `/opt/SERVICE/site` layouts with restricted file access. nftables isolation blocks ordinary local users from the protected listeners and raw tunnel, alongside filesystem restrictions. The obsolete 8080/8090 listeners are closed. These controls do not protect against root or a user with sudo privileges.

The canonical deployment, update, trust and credential-retrieval instructions are [ops/webui/README.md](../../ops/webui/README.md). Plaintext credentials remain on the host in root-only `/etc/webui/credentials/{cornerhead,socio-evo}.json`; no secrets are recorded here.

Cleanup retains one protected pre-migration backup and one previous release per service. Unrelated hangzhou-compute, cloud services, SSH access, ADMCubeQuant and research workloads were left untouched. ADMCubeQuant's existing source-host listener on 38888 is outside this deployment's scope. CornerHead's existing degraded API state is unchanged, with `code_current=true`; successful deployment verification does not establish full backend health.

## Verification and acceptance status

The developer verified external access with CA-validated TLS, login, exact-Origin enforcement, cross-service rejection and logout, as well as session persistence across restart and fail-closed behavior. All 164 UID/address/filesystem isolation checks passed. Published contents matched source checksums for all three CornerHead files and all 358 socio-evo files.

Independent acceptance testing passed the frontend tests (43 passed) and the full suite (230 passed). The independent sol auditor completed the frozen-deployment audit with no blocking defect: external private-CA TLS, authentication, protected assets, header-bypass rejection, exact-Origin enforcement and logout tests passed, and all 164 isolation checks were independently rerun. The auditor inspected live source/configuration parity, nginx and nftables syntax, enabled services and boot ordering. No actual reboot was performed. Authentication restart and fail-closed tests passed in the developer's earlier verification; the independent auditor did not restart services.

## Research documentation

No experiments were rerun. `docs/summary.md` was corrected to remove stale statements that the pilot had not run or that only the smoke run had completed: the existing pilot completed 28 days with eight agents, as recorded in [the preceding project log](PROJECT_LOG_2026-10-02.md). Research code, results and workloads were not changed for this deployment.
