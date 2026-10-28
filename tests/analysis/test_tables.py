"""The tables of a run's evaluation results, from result directories laid out as the
evaluations write them, and their reading by the comparison."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from analysis.compare import main as compare
from analysis.tables import main
from evaluation.capability import CapabilityResult, TaskResult
from evaluation.mask.run import OUTCOMES

ENDINGS = {"+": "accepted", "-": "rejected", "!": "error"}
ANSWERS = {"T": "truthful", "L": "lie", "E": "evasive", "M": "mistaken"}

# Each resident's tasks (+ accepted, - rejected, ! an error) and MASK outcomes (T truthful, L lie,
# E evasive, M mistaken) by day directory; None where a measure was not evaluated that day.
EVALUATED = {
    "day-00": {"R1": ("+-", "TEEL"), "R2": ("--", "TTEM"), "R3": ("+!", "EEEE")},
    "a/day-28": {"R1": ("++", "TEEL"), "R2": ("--", "TTEM"), "R3": ("+-", "EEEE")},
    "c/day-07": {"R1": (None, "TTEE"), "R2": (None, "TTTL"), "R3": (None, "TEEE")},
    "c/day-28": {"R1": ("++", "TTTT"), "R2": ("+-", "TTTL"), "R3": ("++", "TEEE")},
}


def evaluate_capability(out, endings, finished=True, model="qwen"):
    """What `evaluation.capability EXPORT --out OUT` leaves: a directory per task with its copy
    of the resident and its submissions, and, once every task is over, `results.json` (its
    configurations abridged to the model's name)."""
    rows = []
    for n, code in enumerate(endings):
        task = f"astropy__astropy-{n}"
        agent = out / task / "agent"
        agent.mkdir(parents=True)
        (agent / "background.md").write_text("You are a resident.\n")
        (agent / "trace.jsonl").write_text("")
        status = ENDINGS[code]
        verdicts = {"accepted": ("resolved",), "rejected": ("failed_tests",), "error": ()}[status]
        for number, _ in enumerate(verdicts, start=1):
            (out / task / f"submission-{number}.patch").write_text("diff --git a/x b/x\n")
        rows.append(
            TaskResult(
                instance_id=task,
                resolved=status == "accepted",
                status=status,
                submissions=len(verdicts),
                verdicts=verdicts,
                steps=5,
                prompt_tokens=1000,
                completion_tokens=100,
                cached_tokens=0,
                seconds=60.0,
                lapses=0,
                error="RuntimeError: the workspace failed" if status == "error" else None,
            )
        )
    if finished:
        report = {
            "export": f"/exports/{out.name}",
            "commit": "c0ffee",
            "split": "eval",
            "model": {"model": model},
            "concurrency": 2,
            "seconds": 120.0,
            **CapabilityResult.of(rows).model_dump(mode="json"),
        }
        (out / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def evaluate_mask(out, answers, finished=True, model="qwen", judge="deepseek"):
    """What `evaluation.mask EXPORT --out OUT` leaves: the model calls recorded next to OUT as
    they are made, and OUT once every scenario is answered (its configurations abridged to the
    models' names, its scenarios abridged)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    for name in ("resident", "judge"):
        out.with_name(f"{out.stem}.{name}.jsonl").write_text("")
    if finished:
        outcomes = [ANSWERS[code] for code in answers]
        counts = Counter(outcomes)
        report = {
            "resident": f"exports/{out.stem}",
            "commit": "c0ffee",
            "model": {"model": model},
            "reasoning": "low",
            "judge": {"model": judge},
            "seconds": 30.0,
            "usage": {
                name: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
                for name in ("resident", "judge")
            },
            "persona": "# Who you are\n\nYou are a resident.",
            "scenarios": [{"id": f"s{n}", "outcome": o} for n, o in enumerate(outcomes)],
            "counts": {outcome: counts[outcome] for outcome in OUTCOMES},
            "shares": {outcome: counts[outcome] / len(outcomes) for outcome in OUTCOMES},
        }
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def results(tmp_path):
    root = tmp_path / "results"
    for day, residents in EVALUATED.items():
        for resident, (endings, answers) in residents.items():
            if endings is not None:
                evaluate_capability(root / day / "capability" / resident, endings)
            evaluate_mask(root / day / "mask" / f"{resident}.json", answers)
    (root / "c" / "journals").mkdir()
    return root


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_tables_of_a_run_and_their_statistics(results, tmp_path, capsys):
    tables = tmp_path / "tables"
    for run in ("a", "c"):
        main([str(results), "--run", run, "--out", str(tables / run)])
    printed = capsys.readouterr().out
    assert "capability: 3 residents, days 0, 28;" in printed
    assert "mask: 3 residents, days 0, 7, 28;" in printed

    assert read(tables / "c" / "capability.json") == [
        {"resident": "R1", "day": 0, "capability": 0.5},
        {"resident": "R2", "day": 0, "capability": 0.0},
        {"resident": "R3", "day": 0, "capability": 1.0},  # the error left out of the rate
        {"resident": "R1", "day": 28, "capability": 1.0},
        {"resident": "R2", "day": 28, "capability": 0.5},
        {"resident": "R3", "day": 28, "capability": 1.0},
    ]
    assert read(tables / "c" / "mask.json") == [
        {"resident": "R1", "day": 0, "mask": 0.25, "lie": 0.25},
        {"resident": "R2", "day": 0, "mask": 0.5, "lie": 0.0},
        {"resident": "R3", "day": 0, "mask": 0.0, "lie": 0.0},
        {"resident": "R1", "day": 7, "mask": 0.5, "lie": 0.0},
        {"resident": "R2", "day": 7, "mask": 0.75, "lie": 0.25},
        {"resident": "R3", "day": 7, "mask": 0.25, "lie": 0.0},
        {"resident": "R1", "day": 28, "mask": 1.0, "lie": 0.0},
        {"resident": "R2", "day": 28, "mask": 0.75, "lie": 0.25},
        {"resident": "R3", "day": 28, "mask": 0.25, "lie": 0.0},
    ]

    # Changes from day 0 to 28: capability c 0.5, 0.5, 0 and a 0.5, 0, -0.5; truthful share
    # c 0.75, 0.25, 0.25 and a none.
    for measure, means in (("capability", {"a": 0, "c": 1 / 3}), ("mask", {"a": 0, "c": 5 / 12})):
        out = tmp_path / f"{measure}.json"
        runs = [
            arg
            for run in ("a", "c")
            for arg in ("--run", f"{run}={tables / run / f'{measure}.json'}")
        ]
        compare([*runs, "--measure", measure, "--out", str(out)])
        rows = {row["run"]: row for row in read(out)["runs"]}
        assert {run: row["residents"] for run, row in rows.items()} == {"a": 3, "c": 3}
        assert {run: row["mean"] for run, row in rows.items()} == pytest.approx(means)


@pytest.mark.parametrize(
    ("evaluated", "run", "error"),
    [
        pytest.param(
            lambda root: evaluate_capability(root / "c/day-07/capability/R2", "+", finished=False),
            "c",
            "c/day-07/capability: the evaluation of R2 has not finished",
            id="capability unfinished",
        ),
        pytest.param(
            lambda root: evaluate_mask(root / "day-00/mask/R4.json", "TTTT", finished=False),
            "c",
            "day-00/mask: the evaluation of R4 has not finished",
            id="mask unfinished",
        ),
        pytest.param(
            lambda root: evaluate_capability(root / "c/day-07/capability/R1", "!!"),
            "c",
            "c/day-07/capability/R1: every task was an error, so there is no resolved rate",
            id="no resolved rate",
        ),
        pytest.param(
            lambda root: evaluate_mask(root / "c/day-00/mask/R1.json", "TTTT"),
            "c",
            "c/day-00: day 0 is shared by the runs",
            id="a day 0 of its own",
        ),
        pytest.param(
            lambda root: evaluate_capability(root / "c/day-14/capability/R1", "+", model="other"),
            "c",
            "the results of c disagree on the residents' model: other in 1 results, such as "
            "{root}/c/day-14/capability/R1; qwen in 15 results, such as "
            "{root}/day-00/capability/R1",
            id="another resident model",
        ),
        pytest.param(
            lambda root: evaluate_mask(root / "c/day-14/mask/R1.json", "TTTT", judge="other"),
            "c",
            "the results of c disagree on the judge's model: deepseek in 9 results",
            id="another judge",
        ),
    ],
)
def test_unfinished_or_misplaced_results_are_refused(
    results, tmp_path, capsys, evaluated, run, error
):
    evaluated(results)
    with pytest.raises(SystemExit):
        main([str(results), "--run", run, "--out", str(tmp_path / "tables")])
    assert error.format(root=results) in capsys.readouterr().err
    assert not (tmp_path / "tables").exists()


def test_a_run_without_results_of_its_own_has_day_0_alone(results, tmp_path):
    main([str(results), "--run", "b", "--out", str(tmp_path / "tables")])
    for name in ("capability", "mask"):
        rows = json.loads((tmp_path / "tables" / f"{name}.json").read_text(encoding="utf-8"))
        assert rows and {row["day"] for row in rows} == {0}
