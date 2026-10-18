# Active recall and shared context budgets

These features are opt-in so existing runs and ablations retain their original cognition.
Use `experiments/configs/context/swebench-active-context.yaml` for a new three-day SWE-bench
pilot, or add the following to a new experiment configuration:

```yaml
cognition:
  active_recall:
    enabled: true
    max_queries: 2
    max_results: 5
    snippet_chars: 1200
  context_budget:
    enabled: true
    context_tokens: 32768
    input_tokens: 24000
    output_tokens: 4096
    safety_tokens: 1024
    tokenizer_path: null
```

Set `context_tokens` to the actual serving limit, not the model's advertised maximum.
`output_tokens` supplies a request default; an explicit per-agent max_tokens is respected
and reserved instead. Input allowance is the smaller of input_tokens and the context window
minus output and safety reserves. Provider defaults cannot silently increase output because
enabled requests set max_tokens explicitly.

## Active recall

Before an external decision, the resident may answer `recall something` with a short query
instead of choosing an external action. Automatic recency/lexical retrieval still runs.
The system searches only this resident's current episodic stream, insights, diary entries
from prior days, and skill notes. Long documents are searched in overlapping chunks, not
only their prefixes. Results include a source description, town-calendar date/time where recorded,
and an excerpt. Exact file/record references are retained in audit metadata rather than
exposing simulator filenames to residents. Skill notes have no creation timestamp, so their label explicitly states
that and reports the read day. Git archives, truth logs, other residents' files, hidden tests,
and arbitrary paths supplied in a query are never searched. Symlinked memory files and
subdirectories are excluded.

The next decision is rebuilt with the returned material. Repeated normalized queries do
not trigger a second search; empty results are stated explicitly. After max_queries the
reply schema offers only the original allowed external actions. Recall never advances town
time, executes a command, or writes a fake external action into the resident's experience.
It does consume model calls and is not itself guaranteed to improve task performance.

## Budgeting

Identity, current principles, current situation/task view, and reply contract are mandatory.
Other content shares the remaining allowance, rather than owning fixed-size partitions:

1. Current command/test/desk evidence; recent work evidence.
2. Active-recall excerpts and new observations.
3. Relevant skills, recent history, beliefs, older history, notebook index.

A small dynamic floor (at most 192 counted units per block) is shared among current
observations, recent evidence and requested recollections before allocating the remaining
space by priority. This prevents a verbose traceback from starving a just-requested memory
when space permits. Within a priority, newer material is considered first. Selected historical material is
rendered in time order. Exact duplicate text is removed. Long optional excerpts retain their
start and end with an explicit shortening marker; this is deterministic excerpt selection,
not an LLM-written summary or a claim that every important middle line survives. Unused
space flows to the remaining blocks. Complete files are not modified or deleted by packing.
The implementation does not create a new persistent task-progress notebook.

Nightly diary, reflection, skill, policy and free-revision calls also separate instructions
and current principles from optional evidence and share a budget. All enabled completions,
including invalid-answer retries, pass a final guard. Oversized retry pairs are discarded
before the original packed request is touched. Mandatory material that cannot fit produces
ContextOverflow before any backend call; it is not silently truncated. This may require a
larger configured window or a more targeted task view for unusually large tasks.

## Counting and diagnostics

With tokenizer_path unset, UTF-8 byte length plus message overhead is used as an explicitly
labelled conservative estimate for byte-level model tokenizers. This is not an exact token
measurement and usually underuses the window. For local chat-template accounting, install
`pip install -e '.[context]'` and set tokenizer_path to an already downloaded model directory.
On the development machine the existing model directory is:
`/public_fast_storage/lty26/models/Qwen3.8-27B-FP8`.
Loading uses local_files_only=True and trust_remote_code=False; missing/incompatible
tokenizers fail rather than silently downloading or changing counting methods. The template
must match the serving setup; the safety reserve covers additional server formatting.
Response schemas are counted conservatively even when the backend enforces them out-of-band.

Existing llm_calls.jsonl records capture metadata.active_recall (queries, duplicates,
source/time results), metadata.context_budget (block retention and initial count), and
metadata.context_usage (final counted input, allowance, output reserve and counting method).
No extra truth information is injected through these logs.

## Running a new pilot

From the repository on a configured machine:

```bash
python -m experiments.run experiments/configs/context/swebench-active-context.yaml --seeds 0
```

Inspect the runner's help for run-root/resume options. Do not resume an old experiment with
new cognition settings and treat it as the original baseline. No existing remote run was
changed or restarted by this implementation.

## Validation

The focused suite tests recall-to-action continuation, bounded/repeated and empty queries,
private sources and symlink rejection, tail-of-document retrieval, chronological rendering,
priority retention, output/schema accounting, retry overflow, and nightly/free evolution.
Tests use deterministic clients; no claim of improved SWE-bench success is made until a
matched real-model comparison is run.
