# SWE-bench Verified pilot

This standalone repository-repair pilot is not yet a town experiment or frontend replay. It leaves the LiveCodeBench provider intact.

## Components

- `tasks/swebench/pilot.py`: bounded Qwen repair loop; writes official-format predictions.
- `tasks/swebench/docker_exec.py`: detached Docker exec adapter for the Zenith proxy.
- `tasks/swebench/evaluate.py`: official SWE-bench evaluator with that transport adapter.
- `experiments/configs/zenith/swebench-pilot.yaml`: three Verified tasks, temperature 0, 20 actions each.

## Zenith commands

Existing interpreter: `/personal_fast_storage/qwen-serving/venv/bin/python`. Additional dependencies (`swebench==4.1.0`, `docker==7.1.0`, `pyarrow==24.0.0`) are in `/personal_fast_storage/qwen-serving/tools/swebench-pilot`. The existing `run-socio.sh` loads only the model-service environment, not management credentials.

```bash
cd /personal_fast_storage/code/socio-evo
export PYTHONPATH=/personal_fast_storage/qwen-serving/tools/swebench-pilot
/personal_fast_storage/qwen-serving/run-socio.sh -m tasks.swebench.pilot \
  --config experiments/configs/zenith/swebench-pilot.yaml \
  --dataset /personal_fast_storage/datasets/swebench-verified/verified.json \
  --out pilot-runs/UNIQUE-RUN-NAME

/personal_fast_storage/qwen-serving/venv/bin/python -m tasks.swebench.evaluate \
  --dataset_name /personal_fast_storage/datasets/swebench-verified/verified.json \
  --predictions_path pilot-runs/UNIQUE-RUN-NAME/predictions.jsonl \
  --instance_ids pallets__flask-5014 psf__requests-2317 astropy__astropy-12907 \
  --max_workers 1 --timeout 300 --cache_level instance --run_id UNIQUE-EVAL-ID
```

Use unique run/evaluation IDs to avoid reusing cached reports for changed patches. For a separate environment positive control, use `--predictions_path gold`; never give gold data to the model. Docker is required; the runner does not fall back to executing agent commands directly on the development machine.

## Outputs

Each issue has `llm_calls.jsonl`, `commands.jsonl`, `image.json`, `baseline.json`, `model.patch`, and `result.json`. The root has `manifest.json` and `predictions.jsonl`. `submitted` means a patch was produced, not that the issue was fixed. Only official `report.json` with `resolved: true` confirms success. Official evaluation writes logs under `logs/run_evaluation/<run-id>/...` in its working directory.

Dataset: `princeton-nlp/SWE-bench_Verified`, revision `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`. Source parquet SHA256: `a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd`. Source metadata is retained next to the dataset. Official images use `swebench/sweb.eval.x86_64.<instance with __ replaced by _1776_>:latest`; the exact image IDs/digests are recorded per run.

## Completed pilot

See [2026-10-12 results](swebench-pilot-results-20261012.md): two officially resolved tasks, one generation failure, and a separate Requests control timeout.
