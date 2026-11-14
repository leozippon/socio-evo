# Preparing and running the AI laboratory

This guide owns deployment procedures; the [research protocol](../../docs/research.md) owns the scientific design. The current target is one four-person laboratory, with local Qwen inference on host GPU 0 and CUDA/PyTorch research on host GPU 1. Preparation and acceptance probes do not start the formal experiment.

All source deployment, runtime state, probes and generated reports stay on Zenith under `/project_c20250210/260903018`. The launcher refuses local or relative run roots. The deployment being prepared is `/project_c20250210/260903018/socio-evo-ai-lab/deployment-20261114-r1`. The completed town/academy pair is preserved separately.

## Prepare services

Install the committed source with Python 3.11+ and `pip install -e '.[research,dev]'`. The existing serving interpreter is `/personal_fast_storage/qwen-serving/venv/bin/python`; it reads Qwen3.8-27B-FP8 weights from `/public_fast_storage/lty26/models/Qwen3.8-27B-FP8`. Check the selected GPUs before starting services. From the deployed checkout, the current serving command is:

```sh
DEPLOY=/project_c20250210/260903018/socio-evo-ai-lab/deployment-20261114-r1
LD_LIBRARY_PATH=/personal_fast_storage/qwen-serving/cuda-compat/usr/local/cuda-12.9/compat \
  /personal_fast_storage/qwen-serving/venv/bin/python -m ops.research.model_service \
  --root "$DEPLOY" --gpus 0 --port 8041 --max-model-len 262144 \
  --max-num-seqs 8 --kv-cache-dtype auto
```

Keep the foreground service in a persistent remote terminal or process supervisor. Tensor parallelism follows the single selected GPU; the server can hold eight sequences while the laboratory has four concurrent residents. The service writes `model-status.json`, `model.log` and mode-0600 `model.env`/`model-api-key` under the deployment root. A `ready` state includes a real tool-call/continuation probe. A process lock prevents concurrent owners of that root. After observing a run in the running state, the service stops when all watched runs are terminal; pre-existing completed or interrupted manifests do not stop a freshly restarted service during resume preflight.

Build the research image independently of the model-serving environment:

```sh
docker build -t socio-evo-ai-lab:20261114 -f ops/research/Dockerfile.cuda .
```

The CUDA Dockerfile extends the existing scientific image and installs PyTorch, Transformers, Datasets and Accelerate. Its package/index build arguments are defined in that file. Research containers mount shared files at `/research`, read-only evidence at `/records`, and a separate persistent runtime at `/runtime`. Ordinary `pip install` targets `/runtime/python`; model downloads and caches also live outside research Git. The scientific state required for a result must stay under `/research`, including training checkpoints and environment/version records.

Load `TAVILY_API_KEY` and `LIGHTING_API_KEY` from the deployment's private mode-0600 `credentials.env`, and the local model credential from `model.env`. Credentials stay outside the source checkout and research containers:

```sh
set -a
. "$DEPLOY/credentials.env"
. "$DEPLOY/model.env"
set +a
export PYTHONDONTWRITEBYTECODE=1
python -m ops.research.run_lab --runs-root "$DEPLOY/runs" --preflight-only
```

Preflight uses the actual profile to test actor tool calling and continuation, a structured external judge reply, Tavily, curl, the scientific container, host-GPU identity, a CUDA optimizer step and saved tensor loading in another container. A separate acceptance probe verifies that an installed package survives container replacement. Semantic Scholar is recorded as disabled, not passed. A failed check prevents launch. Acceptance requires those concrete operations, not merely `nvidia-smi` or successful package imports.

## Start and resume

After preparation is accepted, the default profile runs through the day-28 checkpoint:

```sh
python -m ops.research.run_lab --runs-root "$DEPLOY/runs" --seed 20260302
```

For an explicitly staged run, `--until-day 7` stops before the commission and `--resume --until-day 28` continues with the same frozen configuration. The model service must be available during launch and resume. `--gpu device=1` is already the research default; keep GPU 0 reserved for inference. The laboratory launcher never starts a second institutional arm. It locks the control directory, refuses a live duplicate, freezes its configuration and does not silently restart a failed run.

The control directory is `runs/lab-seed-20260302/`; `preflight.json` there records enabled checks. The actual experiment, once launched, is `runs/ai-lab-seed-20260302/`, with its own manifest, checkpoints, research Git history, resident files, raw judge reviews and persistent runtime. A control directory created by `--preflight-only` is not evidence of a launched experiment. Configuration changes require a new run rather than silently changing a resumed one.

For a separate read-only viewer, use a free remote port and SSH forwarding:

```sh
python -m frontend.research_server --runs-root "$DEPLOY/runs" --site "$DEPLOY/site" --port 8920
```

Forward local port 8920 to remote `127.0.0.1:8920`. The viewer reads remote files directly and remains waiting before a run exists. Keep viewer data and all later analysis on Zenith; do not mirror experiment outputs into the checkout.

## Preparation status and history

Preparation passed its complete preflight at 2026-11-14 09:31:33 UTC; the formal experiment has not been launched. Local Qwen is ready on host GPU 0 with TP=1 and context length 262144. Real tool calling and feedback continuation, the external `gpt-6.1-sol` judge, Tavily, curl, host-GPU-1 CUDA training and checkpoint loading in a second container all passed. Semantic Scholar remains disabled. A separate probe also passed 40 Adam training steps, cross-container import of `emoji==2.14.1` from `/runtime/python`, persistent caches outside research Git, and read-only evidence access. The viewer on port 8920 returns its waiting state, and no formal experiment manifest exists.

The final image is `socio-evo-ai-lab:20261114`, immutable ID `sha256:3773049a0729b148e2c6a5a9f84a908c3d5ff0f93ceb978bcfc157728c1ae631`. Its Dockerfile SHA-256 is `83a3f2a8bab120a3caf8b947e396f82c62ce3441a3eba593258599beb0521284`. Acceptance receipts are retained under `preflight/model-client.json`, `preflight/cuda-runtime.json`, `preflight/image-build-config.json` and `runs/lab-seed-20260302/preflight.json`. The initial combined container check failed because OpenBLAS attempted 64 threads; the CUDA image now sets OMP, OpenBLAS, MKL and NumExpr to eight threads, matching its CPU allocation. The failed receipt remains preserved, and the complete check and independent CUDA probe passed after that change. See the [project log](../../docs/logbook/PROJECT_LOG_2026-11-14) for source verification and test scopes.

The verified two-A100 instance is `8sm69kjapr5m8teum8myfhz80`, with SSH `root@115.190.90.101:2936`. The Zenith personal API is `https://zenith.bza.edu.cn/pt/api2`; `/instances/{instanceId}/ssh-access` and `/me/ssh-keys` expose access metadata. Registered key synchronization uses POST `{}` to `/instances/{instanceId}/inject-ssh-keys`, followed by its returned status URL and a real SSH probe. Keep host-key verification enabled and platform credentials outside the researcher environment. The registered keys were synchronized and actual login verified on 2026-11-13.

The historical two-arm deployment remains at `/project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113`, with source `0770bc3`, image `socio-evo-autoresearch:ebf4bb5` and seed `20260302`. Both arms completed day 28 before the stop request; no termination or deletion was necessary. Its viewer remains separate on port 8919. See the [original protocol plan](../../docs/plans/2026-11-13-autoresearch-town-academy.md), [deployment history](../../docs/logbook/PROJECT_LOG_2026-11-13) and [completion record](../../docs/logbook/PROJECT_LOG_2026-11-14). The earlier 14-day local-model pilot remains in the [pilot archive](../../docs/archive/research-pilot.md).
