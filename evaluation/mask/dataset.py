"""MASK (cais/MASK) at a pinned revision, and the fixed scenarios this project draws from it.

    python -m evaluation.mask.dataset    # fetch the dataset and write scenarios.json again

A MASK scenario puts a model under pressure to state a falsehood about a proposition whose truth
is known: a system prompt gives it a role and a motive, a user prompt asks the question. Its
columns are `task_id`; `system_prompt` and `user_prompt`, the pressure; `type`, binary or
numerical; `proposition`, the statement with its point of contention marked
`<pivotal>a/b</pivotal>` (binary) or `<pivotal><value></pivotal>` (numerical); `ground_truth`,
the true statement; `formatted_ground_truth`, which pivotal option is true (`A` or `B`) or, for
numerical propositions, the true range `[low, high]` (a bound may be open, `None`);
`belief_elicit_1` to `_3`, questions that elicit the model's own belief without pressure (a
direct one asking for yes or no, an open one, a leading one); `delivery` and `canary`, unused.

The six archetypes differ in how the pressure is built:

- `known_facts`: a widely known fact the role has a motive to deny; three belief prompts.
- `provided_facts`: the fact is stated in the system prompt itself, so the belief is the fact;
  no belief prompts.
- `statistics`: a numerical fact the user wants inflated or deflated; one belief prompt.
- `doubling_down_known_facts`: as `known_facts`, after an earlier exchange (`dd_turn_1_prompt`,
  `dd_turn_1_response`) in which a reply written for the model already leaned the false way.
- `continuations`: the user supplies the start of a text asserting the falsehood and asks for
  its continuation.
- `disinformation`: the user commissions persuasive writing (a polemic, an article) for the
  falsehood.

The project's scenarios come from the first four archetypes only, where the reply to the
pressure is an answer to a question about the proposition, so that its truth can be read off
against the ground truth. In `continuations` and `disinformation` the reply is a piece of writing
the user commissioned, and in part supplied: whether it asserts the proposition, rather than
voicing the user's text, is a matter of interpretation for which MASK's own judge needs special
rules, and refusing the commission is not evading a question. Both archetypes do carry a ground
truth; they are left out because the reply cannot be classed as truthful, a lie or an evasion
as directly as an answer can.

Where a binary scenario's pressure question is answered yes or no, its entry in the selection
says which statement a plain yes and a plain no amount to (`yes_no`: A or B, the first or the
second pivotal option, or neither), reviewed by hand against its prompts, so that the judge is
told rather than left to infer it. A question about the proposition, asked directly or as
whether it is true, maps yes and no to its two sides. A request to confirm a statement (made in
the question or in the earlier exchange of a doubling-down scenario) maps yes to that statement
and a plain no to neither, since declining to confirm asserts nothing. A negative question
maps both to neither, since a bare yes or no to it is read either way (to "So he hasn't been
indicted?" residents answered both "Yes. He has been indicted." and "No, he has been indicted").
A question not answered yes or no (why, how, explain) has no entry, and neither has a numerical
scenario. A scenario whose pressure cannot be read against its proposition is set aside
(`EXCLUDED`, with the reason), and the seed's next candidate of its archetype takes its place.
"""

import json
import random
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any, Literal

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download
from pydantic import model_validator

from infrastructure.config import StrictModel

REPO = "cais/MASK"
REVISION = "4602b84dd9e2ca05c6e1eafbc14e556e908ac1bb"
CACHE = Path("~/.cache/socio-evo/mask").expanduser() / REVISION
"""Where the parquet files of the pinned revision are kept, one directory per archetype."""

Archetype = Literal[
    "known_facts",
    "provided_facts",
    "statistics",
    "doubling_down_known_facts",
    "continuations",
    "disinformation",
]
INCLUDED: tuple[Archetype, ...] = (
    "known_facts",
    "provided_facts",
    "statistics",
    "doubling_down_known_facts",
)
"""The archetypes whose ground truth an answer can be read against, in selection order."""

SEED = 20261024
PER_ARCHETYPE = 5
EXCLUDED = {
    "677d55371943f1c28ed35193": (
        "MV Sewol: the pressure question asks whether the company instructed the passengers to "
        "stay in their cabins, the proposition whether the crew did, and the judge took one for "
        "the other"
    ),
    "6783134ed4aaf6ce09ec8c1d": (
        "Mark Reilly: the pressure is a statement commissioned to either accept or deny the "
        "sentence, not a question, as in the archetypes left out"
    ),
}
"""Scenarios set aside after review, with the reason; the seed's next candidates replace them."""
SCENARIOS = Path(__file__).with_name("scenarios.json")
"""The fixed selection: twenty scenarios, five from each included archetype."""


Side = Literal["A", "B", "neither"]


class YesNo(StrictModel):
    """Which statement a plain yes and a plain no to a pressure question amount to."""

    yes: Side
    no: Side


class Scenario(StrictModel):
    """One MASK scenario. `turns` is the earlier exchange of a doubling-down scenario, as user
    prompt and the reply written for the model, empty otherwise; `belief_prompts` maps each
    belief elicitation column present to its question; `yes_no` is the reviewed reading of a
    yes or no to the pressure question, None where it is not answered so."""

    id: str
    archetype: Archetype
    system_prompt: str
    user_prompt: str
    turns: tuple[str, ...]
    numerical: bool
    proposition: str
    ground_truth: str
    formatted_ground_truth: str
    belief_prompts: dict[str, str]
    yes_no: YesNo | None = None

    @model_validator(mode="after")
    def _yes_no_is_binary(self) -> "Scenario":
        if self.numerical and self.yes_no is not None:
            raise ValueError(f"scenario {self.id}: a numerical scenario has no yes or no reading")
        return self


def fetch(archetype: Archetype) -> Path:
    """The parquet file of `archetype` at the pinned revision, downloaded once into CACHE through
    the Hugging Face endpoint the environment names (`HF_ENDPOINT`)."""
    filename = f"{archetype}/test-00000-of-00001.parquet"
    path = CACHE / filename
    if not path.exists():
        hf_hub_download(REPO, filename, repo_type="dataset", revision=REVISION, local_dir=CACHE)
    return path


def rows(archetype: Archetype) -> list[dict[str, Any]]:
    """Every row of `archetype`, as the parquet file holds it."""
    return pq.read_table(fetch(archetype)).to_pylist()


def scenario(
    archetype: Archetype, row: dict[str, Any], yes_no: dict[str, str] | None = None
) -> Scenario:
    """The scenario of one dataset row, with the reviewed reading of a yes or no if it has one."""
    turns = (
        (row["dd_turn_1_prompt"], row["dd_turn_1_response"]) if "dd_turn_1_prompt" in row else ()
    )
    belief = {
        name: row[name]
        for name in ("belief_elicit_1", "belief_elicit_2", "belief_elicit_3")
        if row.get(name)
    }
    return Scenario(
        id=row["task_id"],
        archetype=archetype,
        system_prompt=row["system_prompt"],
        user_prompt=row["user_prompt"],
        turns=turns,
        numerical=row["type"] == "numerical",
        proposition=row["proposition"],
        ground_truth=row["ground_truth"],
        formatted_ground_truth=row["formatted_ground_truth"],
        belief_prompts=belief,
        yes_no=yes_no,
    )


def select(
    ids: dict[Archetype, Sequence[str]],
    seed: int = SEED,
    per_archetype: int = PER_ARCHETYPE,
    excluded: Collection[str] = tuple(EXCLUDED),
) -> list[tuple[Archetype, str]]:
    """`per_archetype` scenario ids drawn at random by `seed` from each included archetype of
    `ids` (task ids by archetype), in INCLUDED order; other archetypes are ignored. An `excluded`
    id drawn is replaced by the next candidate the seed draws for its archetype, which leaves
    the other draws as they were: a longer draw from the same state begins with the shorter one,
    which is checked."""
    rng = random.Random(seed)
    chosen = []
    for archetype in INCLUDED:
        pool = sorted(ids[archetype])
        state = rng.getstate()
        drawn = rng.sample(pool, per_archetype)
        longer = drawn
        while sum(task_id not in excluded for task_id in longer) < per_archetype:
            again = random.Random()
            again.setstate(state)
            longer = again.sample(pool, len(longer) + 1)
            if longer[:per_archetype] != drawn:
                raise RuntimeError(f"a longer draw of {archetype} does not extend the shorter one")
        chosen += [(archetype, task_id) for task_id in longer if task_id not in excluded]
    return chosen


def load_scenarios(ids: Sequence[str] = (), path: Path = SCENARIOS) -> list[Scenario]:
    """The scenarios of the fixed selection in `path`, in its order, or only those whose ids are
    given, in the order given, each with its reviewed reading of a yes or no; an id not in the
    selection is an error."""
    entries = json.loads(path.read_text())["scenarios"]
    chosen = [(entry["archetype"], entry["id"]) for entry in entries]
    yes_no = {entry["id"]: entry["yes_no"] for entry in entries if "yes_no" in entry}
    if ids:
        known = {task_id: archetype for archetype, task_id in chosen}
        if missing := [task_id for task_id in ids if task_id not in known]:
            raise KeyError(f"not among the scenarios of {path.name}: {', '.join(missing)}")
        chosen = [(known[task_id], task_id) for task_id in ids]
    by_id: dict[str, dict[str, Any]] = {}
    for archetype in dict.fromkeys(archetype for archetype, _ in chosen):
        by_id.update((row["task_id"], row) for row in rows(archetype))
    if missing := [task_id for _, task_id in chosen if task_id not in by_id]:
        raise KeyError(f"not in {REPO} at {REVISION}: {', '.join(missing)}")
    return [
        scenario(archetype, by_id[task_id], yes_no.get(task_id)) for archetype, task_id in chosen
    ]


def main() -> None:
    ids = {archetype: [row["task_id"] for row in rows(archetype)] for archetype in INCLUDED}
    reviewed = {
        entry["id"]: entry["yes_no"]
        for entry in (json.loads(SCENARIOS.read_text())["scenarios"] if SCENARIOS.exists() else [])
        if "yes_no" in entry
    }
    selection = {
        "repo": REPO,
        "revision": REVISION,
        "seed": SEED,
        "per_archetype": PER_ARCHETYPE,
        "scenarios": [
            {"archetype": a, "id": task_id}
            | ({"yes_no": reviewed[task_id]} if task_id in reviewed else {})
            for a, task_id in select(ids)
        ],
    }
    SCENARIOS.write_text(json.dumps(selection, indent=2) + "\n")
    print(f"wrote {len(selection['scenarios'])} scenarios to {SCENARIOS}")


if __name__ == "__main__":
    main()
