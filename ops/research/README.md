# Running the AutoResearch pair

Run the town and academy on the Zenith developer host with Python 3.11+, Docker, and this committed source checkout. All run state, probes and logs stay under `/project_c20250210/260903018`. The helper refuses local or relative run paths. The protocol and scientific comparison are described in [the research documentation](../../docs/research.md).

Install the package with `pip install -e '.[research,dev]'`, then build the research image:

```sh
docker build -t socio-evo-research:local -f ops/research/Dockerfile .
```

On hosts with slow access to Debian or PyPI, select mirrors for this build with `--build-arg DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`. The Debian mirror root must provide both `/debian` and `/debian-security`; this changes only the image build, not the host's package sources.

Load credentials from a private, mode-0600 file outside the checkout. The default profiles require `LIGHTING_API_KEY` for the actor and judge, and `TAVILY_API_KEY` for web search; `SEMANTIC_SCHOLAR_API_KEY` is optional. Credentials are read by the service process and are not passed into research containers. Keep this shell attached through a terminal multiplexer for the foreground controller:

```sh
set -a
. /absolute/private/path/credentials.env
set +a
export PYTHONDONTWRITEBYTECODE=1
RUNS=/project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113/runs
python -m ops.research.run_pair --runs-root "$RUNS" --preflight-only
python -m ops.research.run_pair --runs-root "$RUNS" --until-day 7
python -m ops.research.run_pair --runs-root "$RUNS" --resume --until-day 28
```

Each invocation verifies real actor tool calling and continuation, a structured judge reply, Tavily, Semantic Scholar, curl, and one research container command per distinct resource profile. A failure prevents either experiment from starting. The helper has no scripted research dry run. Preflight checks do not establish scientific quality or long-run stability.

The default seed is `20260302`; use `--seed N` to run another matched pair. Names end in `-seed-N`. The `pair-seed-N/` control directory retains frozen launch profiles, preflight status, separate process logs and exit codes; each experiment also owns its normal manifest and checkpoints. `--resume` requires identical frozen settings, refuses a live process, and skips an arm that already reached the requested checkpoint. A failed arm is not restarted automatically. Terminating the controller forwards termination to both experiment processes.

The research shell has internet access and configurable CPU, memory and command duration. The new protocol uses 8 CPU cores, 32 GiB and 600 seconds per command; shared files persist between commands. GPU access is opt-in: after verifying resources are free, pass `--town-gpu device=0 --academy-gpu device=1` on both launch and resume. These options expose NVIDIA devices and preflight them with `nvidia-smi`; the image supplies numerical Python libraries, but does not bundle a deep-learning framework. Install additional packages into the persistent workspace or build an appropriate image. The helper does not stop existing model servers or other experiments.

## Zenith SSH access

The platform's current personal API uses `https://zenith.bza.edu.cn/pt/api2`. Query `/instances/{instanceId}/ssh-access` and `/me/ssh-keys` with the token in the Authorization header. If the owner's registered keys need synchronization, POST `{}` to `/instances/{instanceId}/inject-ssh-keys`, then poll its returned `status_url`. A successful receipt must be followed by a real SSH probe; requesting key injection does not restart the machine. Keep host-key verification enabled. The old internal HTTP API has inconsistent legacy aliases and must not be used as the basis for diagnosing token permissions.

The verified two-A100 instance is `8sm69kjapr5m8teum8myfhz80`, with SSH `root@115.190.90.101:2936`. On 2026-11-13 the two already-registered keys were successfully synchronized and ordinary SSH login was restored. The platform token is separate from SSH private keys and model-service keys; do not put it in the repository or researcher environment.

## Prepared deployment, 2026-11-13

The independent checkout is `/project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113/code`. Its deployment receipt records the exact source revision and image identity; the core AutoResearch implementation was validated at `d46ae3e`. The deployment's `profiles/` overlays select its independent container image; `run-pair.sh` uses the existing Python environment without modifying it and loads the existing matching Lighting credential into the controller environment. To add Tavily later, place `TAVILY_API_KEY` in the deployment root's private mode-0600 `credentials.env`, outside the source checkout.

```sh
DEPLOY=/project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113
"$DEPLOY/run-pair.sh" --preflight-only
"$DEPLOY/run-pair.sh" --until-day 7
"$DEPLOY/run-pair.sh" --resume --until-day 28
```

The read-only viewer listens on remote `127.0.0.1:8919`; the local SSH tunnel exposes `http://127.0.0.1:8919/`. It currently reports an empty run list and waits for the first experiment. The old 14-day pilot is completed and remains separate. Actual actor tool continuation and the configured judge's grounded structured review have passed; a full paired preflight and experiment launch remain deferred at the user's request until Tavily credentials are available.

The prepared executable revision is `ebf4bb5`, with image `socio-evo-autoresearch:ebf4bb5`. Real container checks passed numerical computation, persistent output, HTTPS curl/git, evidence protection, GPU visibility and timeout cleanup. Their records and image digest are under the deployment root. Public Semantic Scholar returned HTTP429 during preparation; it must pass a fresh preflight as well as the still-missing Tavily service before either arm starts. Deployment readiness does not mean that the full paired preflight or a scientific experiment has run.
