# Zenith LiveCodeBench tasks

The Zenith smoke and town profiles use the existing LiveCodeBench converter instead of the twelve built-in examples. Their run names are `zenith-livecodebench-smoke` and `zenith-livecodebench-town`; previous run directories and recorded configurations remain unchanged. Upstream generic profiles are kept as upstream defines them; the provider default and dry runs retain the built-in bank for local tests.

## Prepare the data

On the development machine, keep the existing Python environment and download to persistent personal storage:

```bash
cd /personal_fast_storage/code/socio-evo
/personal_fast_storage/qwen-serving/venv/bin/python -m tasks.coding.fetch --data-dir /personal_fast_storage/datasets
```

If Hugging Face is unreachable, use anonymous requests to the mirror (do not source a credentials file):

```bash
env -u HF_TOKEN HF_ENDPOINT=https://hf-mirror.com /personal_fast_storage/qwen-serving/venv/bin/python -m tasks.coding.fetch --data-dir /personal_fast_storage/datasets
```

The converter pins the source revision and validates downloaded files against its SHA-256 constants. It retains supported LeetCode function problems and bounded hidden tests, so these are adapted tasks, not the full official benchmark protocol. By default, difficulty follows the dataset labels; Qwen difficulty calibration is a separate, optional model run and has not been performed by preparing the bank.

Under `/personal_fast_storage/datasets/livecodebench/`, `raw/` holds source data, `pool/` the development pool, `town/` the balanced town selection, and `held-out/` the independent evaluation split. `held-out-impossible/` contains separately altered probe tasks and is not used as town work. The problem-ID split prevents held-out problems appearing in the town bank. Repeated draws of a town problem are still possible: the posting policy is unchanged.

Missing or empty banks fail to load; there is no fallback to the built-in questions. Prepare the data before running a Zenith profile. Never use `--resume` to change the task source of a recorded run.

## Experiment and evaluation configurations

- `experiments/configs/zenith-direct-smoke.yaml`: three residents for three days, now named `zenith-livecodebench-smoke`.
- `experiments/configs/zenith/town.yaml`: eight residents for 42 days, now named `zenith-livecodebench-town`.
- `evaluation/configs/zenith-livecodebench.yaml`: uses the upstream nine-family evaluation, with the bank root `/personal_fast_storage/datasets/livecodebench` containing both `held-out/` and `held-out-impossible/`. The work plan remains `evaluation/work.yaml`; its referenced problem IDs must exist in those banks.

The existing runtime entry remains `/personal_fast_storage/qwen-serving/run-socio.sh`. Once the model service and execution environment are ready, pass one of the experiment configurations to `-m experiments.run`. For subsequent evaluation, pass `--config evaluation/configs/zenith-livecodebench.yaml` to `-m experiments.evaluate` with the new run directory and selected days.

This task-source change does not start an experiment, calibrate model difficulty, or change execution isolation. The Zenith simulation profiles retain their explicit direct-execution setting; evaluation and calibration still use the project's default sandbox, which requires a compatible host. Do not report a dry run or task-loading check as a completed model experiment.

## Upstream merge (2026-10-13)

Merged through `e0fe704`. Legacy `tasks.bank` configurations still load; the canonical format is now `tasks.banks.programming`. SQL and calculation banks remain available through upstream multi-trade routing. The calibration entry is now `python -m tasks.calibrate`. Existing recorded runs and their frozen configurations are not rewritten.

The Zenith evaluation keeps the existing local Qwen judge endpoint; this is a same-model judge, not an independent-family judge. Its nine-family results must not be treated as directly comparable to the former four-probe configuration. No full evaluation was launched by the merge.
