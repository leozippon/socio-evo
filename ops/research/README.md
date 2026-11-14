# Preparing and running the AI institute

This guide owns deployment procedures; the [research protocol](../../docs/research.md) owns the scientific design. The current target is one institute of four PhD peers, with local Qwen inference on host GPU 0 and CUDA/PyTorch research on host GPU 1. Preparation and acceptance probes do not start the formal experiment.

All source deployment, runtime state, probes and generated reports stay on Zenith under `/project_c20250210/260903018`. The launcher refuses local or relative run roots. The new deployment root is `/project_c20250210/260903018/socio-evo-ai-lab/deployment-20261115-r1`. The interrupted initial laboratory and completed town/academy pair are preserved separately.

## Prepare services

Install the committed source with Python 3.11+ and `pip install -e '.[research,dev]'`. The existing serving interpreter is `/personal_fast_storage/qwen-serving/venv/bin/python`; it reads Qwen3.8-27B-FP8 weights from `/public_fast_storage/lty26/models/Qwen3.8-27B-FP8`. Check the selected GPUs before starting services. From the deployed checkout, the current serving command is:

```sh
DEPLOY=/project_c20250210/260903018/socio-evo-ai-lab/deployment-20261115-r1
LD_LIBRARY_PATH=/personal_fast_storage/qwen-serving/cuda-compat/usr/local/cuda-12.9/compat \
  /personal_fast_storage/qwen-serving/venv/bin/python -m ops.research.model_service \
  --root "$DEPLOY" --gpus 0 --port 8041 --max-model-len 262144 \
  --max-num-seqs 8 --kv-cache-dtype auto
```

Keep the foreground service in a persistent remote terminal or process supervisor. Tensor parallelism follows the single selected GPU; the server can hold eight sequences while the laboratory has four concurrent residents. The service writes `model-status.json`, `model.log` and mode-0600 `model.env`/`model-api-key` under the deployment root. A `ready` state includes a real tool-call/continuation probe. A process lock prevents concurrent owners of that root. After observing a run in the running state, the service stops when all watched runs are terminal; pre-existing completed or interrupted manifests do not stop a freshly restarted service during resume preflight.

Build the research image independently of the model-serving environment:

```sh
docker build -t socio-evo-ai-institute:20261115 -f ops/research/Dockerfile.paper .
```

The paper image extends the validated `socio-evo-ai-lab:20261114` CUDA image and adds `latexmk`, pdfLaTeX, BibTeX and common mathematics, algorithm, table and figure packages. The base image is built with `Dockerfile.cuda` when needed; extending it avoids downloading PyTorch again. Build-time temporary files use `/tmp`; the running container retains its persistent `/runtime` paths. Research containers mount shared files at `/research`, read-only evidence at `/records`, and a separate persistent runtime at `/runtime`. Ordinary `pip install` targets `/runtime/python`; model downloads and caches also live outside research Git. The scientific state required for a result must stay under `/research`, including training checkpoints and environment/version records.

Load `TAVILY_API_KEY` and `LIGHTING_API_KEY` from the deployment's private mode-0600 `credentials.env`, and the local model credential from `model.env`. Credentials stay outside the source checkout and research containers:

```sh
set -a
. "$DEPLOY/credentials.env"
. "$DEPLOY/model.env"
set +a
export PYTHONDONTWRITEBYTECODE=1
```

Every normal launch first runs preflight with the actual profile: actor tool calling and continuation, a structured external judge reply, Tavily, curl, host-GPU identity, a CUDA optimizer step and saved tensor loading in another container. Conference profiles additionally compile a LaTeX document containing a generated figure, table, algorithm, cross-reference and BibTeX citation, and check the PDF and resolved references. `--preflight-only` is available for isolated diagnostics; it need not precede a normal launch. Separate acceptance probes verify the exact resident-facing CUDA example and a real conference review with grounded citations. Semantic Scholar is recorded as disabled, not passed. A failed check prevents launch. Acceptance requires those concrete operations, not merely `nvidia-smi` or successful package imports.

## Start and resume

After preparation is accepted, the default profile runs through the day-70 checkpoint:

```sh
python -m ops.research.run_lab --runs-root "$DEPLOY/runs" --seed 20260302 --until-day 70
```

The first seven days remain free of a research commission. The task appears at 07:00 on day 8; the first paper review is day 28, followed by days 49 and 70. There is no proposal reward. The cycle scheduler has no fixed round limit, but this deployment is planned for 70 days, not indefinite operation. Set a longer `days` value before launching if needed. For an explicitly staged run, `--until-day 7` stops before the commission and `--resume --until-day 70` continues with the same frozen configuration. The model service must be available during launch and resume. `--gpu device=1` is already the research default; keep GPU 0 reserved for inference. The laboratory launcher never starts a second institutional arm. It locks the control directory, refuses a live duplicate, freezes its configuration and does not silently restart a failed run.

The control directory is `runs/lab-seed-20260302/`; `preflight.json` there records enabled checks. The actual experiment, once launched, is `runs/ai-institute-seed-20260302/`, with its own manifest, checkpoints, research Git history, resident files, raw judge reviews and persistent runtime. A control directory created by `--preflight-only` is not evidence of a launched experiment. Configuration changes require a new run rather than silently changing a resumed one; changing `days` on an already frozen run is not a supported extension mechanism.

For a separate read-only viewer, use a free remote port and SSH forwarding:

```sh
python -m frontend.research_server --runs-root "$DEPLOY/runs" --site "$DEPLOY/site" --port 8921
```

Forward local port 8921 to remote `127.0.0.1:8921`; the original laboratory viewer remains on 8920. The viewer reads remote files directly and remains waiting before a run exists. Keep viewer data and all later analysis on Zenith; do not mirror experiment outputs into the checkout.

## Deployment status and history

The revised institute is being prepared under `deployment-20261115-r1`. Its source and real provider/container acceptance must be verified before launch; no formal institute run is claimed by this preparation record. The LaTeX image is `socio-evo-ai-institute:20261115`, built from the already accepted CUDA image. Build logs and later acceptance receipts remain under the new deployment's `build/` and `preflight/` directories.

The initial experiment `ai-lab-seed-20260302`, in `deployment-20261114-r1`, was stopped at the user's request on 2026-11-14 16:58:24 UTC (2026-11-15 00:58:24 Beijing time). Its manifest is `interrupted`, with no active PID, and its last completed checkpoint is day 12. All records, including subsequent day-13 activity, remain preserved. The stop receipt is `stop-request-20261115.json`. The old model supervisor then exited through its existing automatic lifecycle; start the model service before the new institute's preflight. The previous source was `1c60e9784c3c53fd98cda3029a6ed3fa202ee311`, and its retained CUDA image is `sha256:3773049a0729b148e2c6a5a9f84a908c3d5ff0f93ceb978bcfc157728c1ae631`. Earlier startup and CUDA acceptance details remain in the [2026-11-14 project log](../../docs/logbook/PROJECT_LOG_2026-11-14).

The verified two-A100 instance is `8sm69kjapr5m8teum8myfhz80`, with SSH `root@115.190.90.101:2936`. The Zenith personal API is `https://zenith.bza.edu.cn/pt/api2`; `/instances/{instanceId}/ssh-access` and `/me/ssh-keys` expose access metadata. Registered key synchronization uses POST `{}` to `/instances/{instanceId}/inject-ssh-keys`, followed by its returned status URL and a real SSH probe. Keep host-key verification enabled and platform credentials outside the researcher environment. The registered keys were synchronized and actual login verified on 2026-11-13.

The historical two-arm deployment remains at `/project_c20250210/260903018/socio-evo-autoresearch/deployment-20261113`, with source `0770bc3`, image `socio-evo-autoresearch:ebf4bb5` and seed `20260302`. Both arms completed day 28 before the stop request; no termination or deletion was necessary. Its viewer remains separate on port 8919. See the [original protocol plan](../../docs/plans/2026-11-13-autoresearch-town-academy.md), [deployment history](../../docs/logbook/PROJECT_LOG_2026-11-13) and [completion record](../../docs/logbook/PROJECT_LOG_2026-11-14). The earlier 14-day local-model pilot remains in the [pilot archive](../../docs/archive/research-pilot.md).
