# SWE-bench Verified tasks

This package turns SWE-bench Verified into paid work: a fixed set of tasks, an isolated container in which a resident works on one, and an official acceptance that decides whether the work counts.

- **Tasks and splits.** The 500 instances of SWE-bench Verified, read from `princeton-nlp/SWE-bench_Verified` at a pinned revision, load as `Task` records. `splits.json` fixes an eval split of 100 tasks, drawn with seed 20261024, and a disjoint train split of every other usable instance, 363 tasks (it held 56 until it was widened, which left the eval split as first drawn), and records the 37 instances left out with the reason: the 34 of matplotlib, whose images cannot be unpacked on this machine, and three whose gold patch cannot pass here (astropy-8707 in its image, requests-2317 and -2931 without network). Every instance has an image. A resident is told only the problem statement (`Task.brief()`); the hints, hidden tests and gold patch stay with the task.
- **Images.** Each task runs in Epoch AI's prebuilt evaluation image on ghcr.io, the same image SWE-bench publishes on Docker Hub (unreachable here) under another name: `swebench/sweb.eval.x86_64.<id, "__" written "_1776_">` is `ghcr.io/epoch-research/swe-bench.eval.x86_64.<id>:latest`. An image holds the repository at the base commit with its environment installed.
- **Workspaces.** `await Workspace.open(task, name)` starts a container with no network, 4 CPUs, 16 GB of memory and at most 4096 processes. The resident runs shell commands in it (`exec`, with a timeout and clipped output), reads and writes files, and hands in `diff()`, a patch of everything it changed in the repository.
- **Acceptance.** `await accept(task, patch)` grades a patch as the SWE-bench harness does and returns a verdict: `resolved`, `failed_tests`, `patch_apply_failed`, `timeout` or `error`, with the hidden tests passed out of those run.

## Use

```
pip install -e ".[swebench]"
python -m tasks.swebench.pull                  # pull the images and accept every gold patch; rerun to resume
python -m tasks.swebench.accept <instance_id> <patch_file>
python -m tasks.swebench.cleanup               # remove containers a killed process left
python -m pytest tests/tasks/swebench          # Docker tests skip unless images are pulled
```

The dataset downloads on first use into `~/.cache/socio-evo/swebench`; set `HF_ENDPOINT` to use a mirror. `python -m tasks.swebench.dataset` redraws `splits.json` after checking every image on ghcr.io. The pull ends by listing any image it could not pull and any task whose gold patch was not resolved; such a task goes into `UNRESOLVABLE` in `dataset.py`, and a redraw then drops it from train without changing eval.

## Integrity

A resident cannot see the hidden tests: the image holds the repository before the test patch, and the names of the tests that decide acceptance are never given. Nor can it fetch the upstream fix. The container has no network, and because the images were made by cloning the whole repository, whose history reaches past the fix, opening a workspace first deletes the tags and refs newer than the base commit, prunes what they reached and checks that no newer commit remains, as SWE-bench's current image setup does.

Acceptance starts a fresh container and applies only the patch, so nothing else done in the workspace counts. The official eval script then restores the test files the hidden tests touch before adding them. The patch is taken against the working tree the image starts with rather than against the base commit, because some images leave SWE-bench's install-time edits uncommitted (astropy's `pyproject.toml`, a `build/` directory in requests); it includes new files git does not ignore and leaves out binary files.

A run that cannot be judged on its merits is an `error`, never `failed_tests`: a process killed for lack of memory, or output without the harness's markers. The verdict's log tail shows the hidden tests' output and is not for residents.

## Limitations

- Code in a patch runs during the hidden tests and could game them, say with a `conftest.py` that marks failures as passes. The official harness has the same exposure, and acceptance does not detect it.
- The eval script reruns some repositories' install step without network. For astropy it fails (it fetches setuptools), so changes to astropy's compiled extensions are not rebuilt for acceptance; scikit-learn's rebuilds offline.
- matplotlib is left out: its images hold files owned by UID 197609, beyond the 65,536 subordinate IDs this machine's rootless Docker can map, so they do not unpack here.
- Containers of a process that was killed stay until `cleanup` runs; those of a process that exits normally are removed.

## Measurements

Measured on 2026-10-24 with 12 acceptances or workspaces running at once. The gold patch of every one of the 156 split tasks was accepted as `resolved`, and a workspace opened cleanly on each; opening includes removing the newer history.

| Repository | Tasks | Gold acceptance, median (max) | Workspace open, median |
|---|---|---|---|
| django | 79 | 15 s (95 s) | 9 s |
| sympy | 22 | 13 s (95 s) | 5 s |
| scikit-learn | 14 | 10 s (190 s) | 4 s |
| sphinx | 13 | 7 s (14 s) | 3 s |
| pytest | 7 | 13 s (19 s) | 2 s |
| astropy | 6 | 23 s (28 s) | 5 s |
| xarray | 6 | 14 s (22 s) | 1 s |
| pylint | 5 | 16 s (27 s) | 2 s |
| requests, flask, seaborn | 4 | 4 to 66 s | 1 s |

The 156 images take about 45 GB, shared layers counted once; pulling them took about 35 minutes with 8 pulls at a time, most of it a slow stretch of the registry.
