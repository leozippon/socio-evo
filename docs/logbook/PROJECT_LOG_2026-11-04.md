# Project log — 2026-11-04

## Add BabelDOC to the shared authentication gateway

Added the `babeldoc` service, brand mapping and a 59-line light-theme override using the existing shared layout. The existing CornerHead and socio-evo stylesheets and CSP hashes remain unchanged; the compatibility tests also preserve service-specific cookies, the 30-day session lifetime, exact Origin checks and session isolation.

Validation: `PYTHONDONTWRITEBYTECODE=1 WEBUI_GATEWAY=/Data2/lzp/socio-evo/ops/webui/gateway.py /Data2/lzp/babeldoc/.venv/bin/pytest -p no:cacheprovider /Data2/lzp/babeldoc/tests/ops/test_gateway_compat.py` passed all 8 tests in 3.56 seconds. The delivery copy is byte-identical to the tested gateway; LSP and diff checks passed. Tests remain in the deployment repository rather than being duplicated here. This records the already-deployed patch without changing deployed files or restarting services.
