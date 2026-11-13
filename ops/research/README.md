# Running the AutoResearch pair

Run the town and academy on the Zenith developer host with Python 3.11+, Docker, and this committed source checkout. All run state, probes and logs stay under `/project_c20250210/260903018`. The helper refuses local or relative run paths. The protocol and scientific comparison are described in [the research documentation](../../docs/research.md).

Install the package with `pip install -e '.[research,dev]'`, then build the research image:

```sh
docker build -t socio-evo-research:local -f ops/research/Dockerfile .
```

Load credentials from a private, mode-0600 file outside the checkout. The default profiles require `LIGHTING_API_KEY` for the actor and judge, and `TAVILY_API_KEY` for web search; `SEMANTIC_SCHOLAR_API_KEY` is optional. Credentials are read by the service process and are not passed into research containers. Keep this shell attached through a terminal multiplexer for the foreground controller:

```sh
set -a
. /absolute/private/path/credentials.env
set +a
export PYTHONDONTWRITEBYTECODE=1
RUNS=/project_c20250210/260903018/socio-evo-autoresearch/runs
python -m ops.research.run_pair --runs-root "$RUNS" --preflight-only
python -m ops.research.run_pair --runs-root "$RUNS" --until-day 7
python -m ops.research.run_pair --runs-root "$RUNS" --resume --until-day 28
```

Each invocation verifies real actor tool calling and continuation, a structured judge reply, Tavily, Semantic Scholar, curl, and one research container command per distinct resource profile. A failure prevents either experiment from starting. The helper has no scripted research dry run. Preflight checks do not establish scientific quality or long-run stability.

The default seed is `20260302`; use `--seed N` to run another matched pair. Names end in `-seed-N`. The `pair-seed-N/` control directory retains frozen launch profiles, preflight status, separate process logs and exit codes; each experiment also owns its normal manifest and checkpoints. `--resume` requires identical frozen settings, refuses a live process, and skips an arm that already reached the requested checkpoint. A failed arm is not restarted automatically. Terminating the controller forwards termination to both experiment processes.

The research shell has internet access and configurable CPU, memory and command duration. The new protocol uses 8 CPU cores, 32 GiB and 600 seconds per command; shared files persist between commands. GPU access is opt-in: after verifying resources are free, pass `--town-gpu device=0 --academy-gpu device=1` on both launch and resume. These options expose NVIDIA devices and preflight them with `nvidia-smi`; the image supplies numerical Python libraries, but does not bundle a deep-learning framework. Install additional packages into the persistent workspace or build an appropriate image. The helper does not stop existing model servers or other experiments.
