# Repository operating notes (next-run opt-in)

`tasks.repository_guidance: true` enables environment preflight and shared operating
notes in each task specification. The Lite and Verified community templates enable it;
older configurations default to false. All code changes are local until explicitly
deployed. Existing running experiments use their original code and configuration.

Before starting the next run on a host with Docker and the configured dataset:

```bash
python -m tasks.swebench.preflight experiments/configs/community/verified.yaml \
  --seed 0 --out /path/to/new-preflight-directory
```

Use the same configuration and seed for the experiment. The CLI checks the actual first
morning's draw without calling the model or creating an experiment. Runtime also checks
each newly selected issue before publication, including replacements on later days.
The preflight output directory must be new, preserving earlier diagnostic reports.

Django: validate `tests/runtests.py --help`, presence of `tests/test_sqlite.py`, and Django
initialization with that settings module. Notes explain:

```bash
python tests/runtests.py --settings=test_sqlite <test-label>
```

Residents select a real label under `tests/`; this is not a hint to the issue's hidden tests.
Other repositories: validate the installed `python -m pytest --version` and `--help`.
Notes explain `python -m pytest <test-path>` without inventing a repository-specific path.
A repository needing another launcher fails preflight instead of receiving an unverified
recipe. Add a tested recipe before using such repositories.

The check verifies the basic launcher/environment, not all collection dependencies,
services, every test, or repair correctness. Reports include exit status and output;
infrastructure failures stop the run rather than being graded as failed repairs. Preflight
does not install packages or relax isolation. Official submission grading is unchanged.

All terminal commands in the new code enable Bash `pipefail`. Thus `false | tail -1`
returns nonzero. This does not establish that tests ran, detect errors explicitly ignored
with `|| true`, or override a resident explicitly changing shell options. Early pipe closure
(e.g. `head`) may generate SIGPIPE; residents must interpret the actual output.

Commands run offline in `/testbed` in the testbed Python environment. In community mode,
only changes captured in the repository patch persist; no shell variables, installed
packages or background processes survive between actions. Each command retains its
configured timeout (60 seconds by default) and 16000-character output limit.
