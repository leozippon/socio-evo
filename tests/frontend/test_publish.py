"""The publisher: the bundle it writes matches its contract in frontend/README.md, references
carry hashes and stay inside the site, agents are published as their repositories and traces
hold them, settled days are kept, a run in progress and a run just created are published, an
unreadable configuration is skipped and said so, nothing is written into a run, unsafe targets
are refused, the evaluation and the comparison are read from the results root, and the push
script switches a release atomically."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import pytest
import pytest_asyncio
import yaml

from analysis.measures import MEASURES
from frontend import bundle
from frontend.publish import (
    FORMAT,
    KINDS,
    MANIFEST,
    PUBLISHING_FAILED,
    UNREADABLE_CONFIG,
    Publisher,
    encode,
)
from frontend.publish import main as publish
from infrastructure.storage import RunDirectory
from ops.webui.verify import BUNDLE_FORMAT
from tests.frontend.conftest import (
    commit_agents,
    entry,
    live_a_day,
    new_town,
    real_times,
    write_results,
    write_trace,
)
from tests.world.conftest import at, town_config
from world.clock import DAY
from world.log import KINDS as LOG_KINDS

PROJECT = Path(__file__).parents[2]
README = PROJECT / "frontend" / "README.md"
PUSH = PROJECT / "frontend" / "deploy" / "push.sh"
RUN = "data/runs/town"
RESIDENTS = ("Mei", "Tomas", "Aisha")


def files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def stamps(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def read(site: Path, path: str) -> Any:
    return json.loads((site / path.split("?")[0]).read_bytes())


async def make_run(root: Path) -> RunDirectory:
    """The town's run after a lived day: agents committed as created and at the first
    checkpoint, with Mei's trace and session."""
    run, town = new_town(root)
    config = town_config(claim_expiry_days=0)
    commit_agents(run, config, 0)
    await live_a_day(town)
    await town.close()
    first, checkpoint = real_times(run)
    step = (checkpoint - first) / 10  # the manual clock lives a day in milliseconds
    tools = ["read_file", "go", "say"]
    records = [
        {
            "kind": "percept",
            "sim_time": at("07:00"),
            "real_time": first + 1 * step,
            "text": "You woke up.",
            "percept_kind": "wake",
            "event_id": 1,
            "percept_sim_time": at("07:00"),
            "percept_real_time": first,
        },
        {
            "kind": "prompt",
            "sim_time": at("07:00"),
            "real_time": first + 2 * step,
            "text": "You are Mei.",
        },
        {
            "kind": "request",
            "sim_time": at("07:00"),
            "real_time": first + 3 * step,
            "purpose": "step",
            "messages": [1],
            "tools": tools,
            "reasoning_effort": "low",
            "max_tokens": 100,
            "attempt": 1,
        },
        {
            "kind": "reply",
            "sim_time": at("07:01"),
            "real_time": first + 4 * step,
            "purpose": "step",
            "text": "",
            "truncated": False,
            "max_tokens": 100,
            "reasoning": "Off to work.",
            "tool_calls": [
                {"id": "c1", "name": "go", "arguments": {"place": "workshop"}, "unreadable": None}
            ],
            "finish_reason": "tool_calls",
            "aborted": False,
            "usage": None,
            "latency": 0.1,
        },
        {
            "kind": "tool_call",
            "sim_time": at("07:01"),
            "real_time": first + 5 * step,
            "id": "c1",
            "name": "go",
            "arguments": {"place": "workshop"},
        },
        {
            "kind": "tool_result",
            "sim_time": at("07:01"),
            "real_time": first + 6 * step,
            "id": "c1",
            "name": "go",
            "text": "You set off.",
            "ends_turn": True,
        },
        {
            "kind": "request",
            "sim_time": at("07:30", day=2),
            "real_time": checkpoint + 1,
            "purpose": "step",
            "messages": [1, 2, 3, 4],
            "tools": tools,
            "reasoning_effort": "low",
            "max_tokens": 100,
            "attempt": 1,
        },
        {
            "kind": "lapse",
            "sim_time": at("07:31", day=2),
            "real_time": checkpoint + 2,
            "purpose": "step",
            "errors": ["timeout"],
        },
    ]
    session = [
        {
            "type": "message",
            "id": 1,
            "message": {"role": "user", "content": "You woke up. Now you can use: go."},
        },
        {
            "type": "message",
            "id": 2,
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "go", "arguments": {"place": "workshop"}}],
            },
            "prompt_tokens": 10,
        },
        {
            "type": "message",
            "id": 3,
            "message": {"role": "tool", "content": "You set off.", "tool_call_id": "c1"},
        },
        {"type": "compaction", "id": 4, "replaced": [1], "summary": "I went to work."},
    ]
    write_trace(run, "Mei", records, session)
    commit_agents(run, config, 1)
    run.checkpoint_path(1).write_text(json.dumps(town.checkpoints[0][1]))
    return run


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def published(tmp_path_factory) -> tuple[Path, Path, Path]:
    """A runs root with the town and a copy of it beside it, a results root with the town's
    evaluation, and the site published from them."""
    root = tmp_path_factory.mktemp("published")
    runs = root / "runs"
    run = await make_run(runs)
    shutil.copytree(run.root, runs / "twin")
    config = yaml.safe_load((runs / "twin" / "config.yaml").read_text())
    config["name"] = "twin"
    (runs / "twin" / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    results = root / "results"
    write_results(results, "town")
    site = root / "site"
    Publisher(runs, site, results).publish()
    return runs, results, site


def contract(header: str = "Field") -> dict[str, list[str]]:
    """The README's file kinds: each path pattern with the fields its table headed `header`
    documents, for the kinds that have one."""
    documented = {}
    for section in re.split(r"^### ", README.read_text(encoding="utf-8"), flags=re.M)[1:]:
        heading, _, body = section.partition("\n")
        table = re.search(rf"^\| {header} \|.*\n\|[- |]+\n((?:\|.*\n)+)", body, flags=re.M)
        if table:
            fields = re.findall(r"^\| `([^`]+)` \|", table[1], re.M)
            documented[heading.strip().strip("`")] = fields
    return documented


def values_at(document: Any, path: str) -> list[Any]:
    """The values at a documented path: `a.b` is field `b` of `a`, `a[]` each element of `a`."""
    values = [document]
    for part in filter(None, path.split(".")):
        values = [value[part.removesuffix("[]")] for value in values]
        if part.endswith("[]"):
            values = [item for value in values for item in value]
    return values


def test_every_file_has_exactly_the_documented_fields(published):
    _, _, site = published
    documented = contract()
    assert set(documented) == set(KINDS.values())
    assert json.loads((site / "data" / "manifest.json").read_bytes()) == MANIFEST
    for pattern, fields in documented.items():
        paths = sorted((site / "data").glob(re.sub(r"\{\w+\}", "*", pattern)))
        assert paths, pattern
        children = defaultdict(set)
        for field in fields:
            parent, _, name = field.rpartition(".")
            children[parent].add(name)
        for path in paths:
            document = json.loads(path.read_bytes())
            for parent, names in children.items():
                for value in values_at(document, parent):
                    assert set(value) == names, (path, parent)

    markers = {
        kind: set(re.findall(r"`(\w+)`", fields))
        for kind, fields in re.findall(r"^\| `(\w+)` \| (.*) \|$", README.read_text(), re.M)
        if kind in bundle.COUNTED
        or kind
        in (
            "claim",
            "submission",
            "payment",
            "abandon",
            "expiry",
            "speech",
            "gift",
            "skill_shared",
            "rating",
            "journal",
            "forced_sleep",
        )
    }
    timeline = read(site, f"{RUN}/timeline.json")
    seen = set()
    for lane in timeline["residents"]:
        for marker in lane["markers"]:
            seen.add(marker["kind"])
            assert set(marker) <= {"seq", "t", "kind", "place"} | markers[marker["kind"]], marker
    assert {
        "claim",
        "submission",
        "payment",
        "speech",
        "gift",
        "skill_shared",
        "rating",
        "journal",
        "forced_sleep",
        "expiry",
    } <= seen

    measures = read(site, f"{RUN}/measures.json")
    for row in measures["rows"]:
        assert set(row) == {"resident", "day", "date", *MEASURES}
    kinds = set()
    for path in (site / RUN / "events").iterdir():
        for found in json.loads(path.read_bytes())["entries"]:
            kinds.add(found["kind"])
            assert found["kind"] in LOG_KINDS
            assert not set(found["payload"]) & bundle.OMITTED
    assert {
        "submission",
        "checkpoint",
        "speech",
        "gift",
        "skill_shared",
    } <= kinds


def test_references_carry_the_hash_of_files_inside_the_site(published):
    runs, _, site = published
    for name, data in files(site).items():
        assert not (site / name).is_symlink()
        assert str(runs) not in data.decode()
        if not name.endswith(".json"):
            continue
        for reference in re.findall(r'"([^"?]+\?[vr]=[0-9a-f]{16})"', data.decode()):
            url = urljoin(f"http://site/{quote(name)}", reference)
            target = (site / urlsplit(url).path.lstrip("/")).resolve()
            assert target.is_relative_to(site.resolve())
            digest = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
            assert reference.endswith(f"={digest}")


def test_the_index_names_the_runs_their_groups_and_the_comparison(published):
    _, _, site = published
    index = read(site, "data/index.json")
    assert [(run["name"], run["group"], run["status"]) for run in index["runs"]] == [
        ("town", "C", "running"),
        ("twin", "C", "running"),
    ]
    town = index["runs"][0]
    assert (town["settled_day"], town["last_day"], town["residents"]) == (1, 2, list(RESIDENTS))
    assert town["headline"]["accepted"] == 1 and town["headline"]["paid"] == 20
    assert town["headline"]["day"] == 2 and town["headline"]["purse"]["median"] == 105
    assert index["skipped"] == []
    [comparison] = index["comparisons"]
    assert (comparison["name"], comparison["runs"]) == ("runs", ["town", "twin"])
    doc = read(site, f"data/{comparison['url']}")
    assert doc["groups"] == {"C": "town"}
    assert doc["problems"] == ["twin is a second run of group C, like town"]
    by_measure = {found["measure"]: found for found in doc["measures"]}
    assert by_measure["capability"]["declared"] and by_measure["capability"]["days"] == [0, 1]
    [group] = by_measure["capability"]["groups"]
    assert (group["group"], group["statistic"], group["values"]) == ("C", "change", {"Mei": 0.25})
    assert by_measure["capability"]["daily"] == {"C": [[0, 0.25], [1, 0.5]]}
    assert by_measure["claimed"]["days"] == [1, 1] and not by_measure["claimed"]["declared"]
    assert by_measure["claimed"]["contrasts"] == []


def test_the_world_lays_the_town_out_and_names_the_group(published):
    _, _, site = published
    world = read(site, f"{RUN}/world.json")
    assert [(p["id"], p["kind"], p["x"], p["y"]) for p in world["places"]] == [
        ("mill-street-house", "home", 0.0, 0.0),
        ("college-flat", "home", 1.0, 0.0),
        ("workshop", "workplace", 0.5, 1.5),
        ("cafe", "social", 0.0, 3.0),
        ("park", "social", 1.0, 3.0),
    ]
    assert [r["name"] for r in world["residents"]] == list(RESIDENTS)
    assert world["residents"][0]["rules"].startswith("How the town works.")
    assert world["group"] == "C" and world["currency"] == "$"
    config = town_config()
    for mode, exchange, writable, group in (
        ("isolated", None, True, "A"),
        ("isolated", {"at": "19:00", "place": "cafe", "messages": 3}, True, "B"),
        ("town", None, True, "C"),
        ("town", None, False, "D"),
        ("isolated", None, False, None),
    ):
        experiment = {
            "name": "x",
            "llm": {"backend": "scripted", "base_url": "-", "api_key_env": "-", "model": "-"},
            "runtime": {},
            "town": town_config(mode, exchange=exchange, shareable=writable).model_dump(
                mode="json"
            ),
            "residents": [{"name": r.name, "background": "x.md"} for r in config.residents],
            "skills_writable": writable,
            "days": 1,
        }
        from simulation.config import ExperimentConfig

        assert bundle.group_of(ExperimentConfig.model_validate(experiment)) == group


def test_an_agent_is_published_as_its_repository_and_trace_hold_it(published):
    runs, _, site = published
    for name in RESIDENTS:
        directory, base = runs / "town" / "agents" / name, site / RUN / "agents" / name
        history = json.loads((base / "versions.json").read_bytes())
        commits = subprocess.run(
            ["git", "rev-list", "--reverse", "HEAD"], cwd=directory, capture_output=True, text=True
        ).stdout.split()
        assert [v["commit"] for v in history["versions"]] == commits
        assert [(v["day"], v["time"]) for v in history["versions"]] == [(0, 9000), (1, DAY + 9000)]
        for version in history["versions"]:
            assert not {c["path"] for c in version["changes"]} & bundle.UNPUBLISHED
        last = history["versions"][-1]
        day = json.loads((base / urlsplit(last["url"]).path).read_bytes())
        [found] = [v for v in day["versions"] if v["commit"] == last["commit"]]
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=directory, capture_output=True, text=True
        ).stdout.split()
        assert set(found["files"]) == set(tracked) - bundle.UNPUBLISHED
        for path, text in found["files"].items():
            assert text == (directory / path).read_text()
        assert "memory/work.md" in found["diff"] and "session.jsonl" not in found["diff"]

    run = read(site, f"{RUN}/run.json")
    traces = {r["name"]: r["trace_days"] for r in run["residents"]}
    assert traces["Tomas"] == [] and [(t["day"], t["records"]) for t in traces["Mei"]] == [
        (1, 6),
        (2, 2),
    ]
    day1 = read(site, f"{RUN}/{traces['Mei'][0]['url']}")
    assert day1["prompt"] is None and [r["kind"] for r in day1["records"]][:3] == [
        "percept",
        "prompt",
        "request",
    ]
    assert day1["records"][2]["new_messages"] == [
        {"role": "user", "content": "You woke up. Now you can use: go."}
    ]
    day2 = read(site, f"{RUN}/{traces['Mei'][1]['url']}")
    assert day2["prompt"] == "You are Mei."
    [request, lapse] = day2["records"]
    assert [m["role"] for m in request["new_messages"]] == ["assistant", "tool", "user"]
    assert request["new_messages"][2] == {
        "role": "user",
        "content": "I went to work.",
        "compaction": True,
    }
    assert lapse["errors"] == ["timeout"]
    assert "?v=" in traces["Mei"][0]["url"] and "?r=" in traces["Mei"][1]["url"]


def test_the_evaluation_is_read_from_the_results_root(published, tmp_path):
    runs, results, site = published
    evaluation = read(site, f"{RUN}/evaluation.json")
    assert evaluation["capability"] == [
        {"resident": "Mei", "day": 0, "capability": 0.25},
        {"resident": "Mei", "day": 1, "capability": 0.5},
    ]
    assert evaluation["mask"] == [
        {"resident": "Mei", "day": 0, "mask": 0.4, "lie": 0.1},
        {"resident": "Mei", "day": 1, "mask": 0.4, "lie": 0.1},
    ]
    assert [(row["resident"], row["distortion"]) for row in evaluation["journals"]] == [
        ("Aisha", None),
        ("Mei", 0.25),
    ]
    assert "extra" not in evaluation["journals"][0] and evaluation["problems"] == []
    assert read(site, "data/runs/twin/evaluation.json") == {
        "capability": [],
        "mask": [],
        "journals": [],
        "problems": [],
    }

    unfinished = tmp_path / "results"
    write_results(unfinished, "town", finished=False)
    found = bundle.evaluation(unfinished, "town")
    assert found["capability"] == [] and found["mask"] == []
    assert len(found["journals"]) == 2
    [problem] = found["problems"]
    assert problem.endswith("the evaluation of Tomas has not finished")


async def test_a_run_in_progress_is_published_and_its_settled_files_kept(tmp_path):
    runs, out = tmp_path / "runs", tmp_path / "site"
    run = await make_run(runs)
    Publisher(runs, out).publish()
    document = read(out, f"{RUN}/run.json")
    assert (document["status"], document["settled_day"], document["last_day"]) == ("running", 1, 2)
    assert [(d["day"], d["settled"]) for d in document["event_days"]] == [(1, True), (2, False)]
    assert "?v=" in document["event_days"][0]["url"] and "?r=" in document["event_days"][1]["url"]
    before = stamps(out)

    # Day 2 closes: its files are rewritten, day 1's kept untouched, the world never rewritten.
    last = document["entries"]
    with run.world_log_path.open("a") as log:
        log.write(entry(last + 1, "checkpoint", at("02:30", day=3), real_time=2e9, day=2) + "\n")
    written = set(Publisher(runs, out).publish().written)
    settled = {
        f"{RUN}/events/day-01.json",
        f"{RUN}/world.json",
        f"{RUN}/agents/Mei/day-01.json",
        f"{RUN}/agents/Mei/trace-day-01.json",
    }
    assert not written & settled
    assert {f"{RUN}/events/day-02.json", f"{RUN}/run.json", f"{RUN}/timeline.json"} <= written
    assert all(stamps(out)[name] == before[name] for name in settled)
    assert read(out, f"{RUN}/run.json")["settled_day"] == 2

    fresh = tmp_path / "fresh"
    Publisher(runs, fresh).publish()
    assert files(out) == files(fresh)


def test_a_run_just_created_is_published_before_its_first_entry(tmp_path):
    runs = tmp_path / "runs"
    run, _ = new_town(runs)
    Publisher(runs, tmp_path / "site").publish()
    document = read(tmp_path / "site", f"{RUN}/run.json")
    assert (document["settled_day"], document["last_day"], document["entries"]) == (0, 0, 0)
    assert document["event_days"] == []
    assert [(r["versions"], r["trace_days"]) for r in document["residents"]] == [(0, [])] * 3
    assert read(tmp_path / "site", f"{RUN}/measures.json")["rows"] == []
    assert read(tmp_path / "site", "data/index.json")["comparisons"] == []
    assert run.world_log_path.exists() is False


async def test_republishing_an_unchanged_run_rewrites_nothing(tmp_path, capsys):
    runs, out = tmp_path / "runs", tmp_path / "site"
    await make_run(runs)
    publish(["--runs-root", str(runs), "--out", str(out)])
    before = stamps(out)
    publisher = Publisher(runs, out)
    assert publisher.publish().written == []
    assert publisher.publish().written == []
    publish(["--runs-root", str(runs), "--out", str(out)])
    assert capsys.readouterr().out.splitlines()[-1].endswith(": 0 written, 0 removed")
    assert stamps(out) == before


async def test_publishing_never_modifies_the_run_or_the_results(tmp_path):
    runs, results = tmp_path / "runs", tmp_path / "results"
    run = await make_run(runs)
    write_results(results, "town")

    def status(name: str) -> str:
        command = ["git", "status", "--porcelain", "--untracked-files=all"]
        return subprocess.run(
            command, cwd=run.agent_dir(name), capture_output=True, text=True, check=True
        ).stdout

    statuses = [status(name) for name in RESIDENTS]
    before = stamps(run.root), stamps(results)
    Publisher(runs, tmp_path / "site", results).publish()
    assert (stamps(run.root), stamps(results)) == before
    assert [status(name) for name in RESIDENTS] == statuses == ["", "", ""]


async def test_a_run_whose_configuration_cannot_be_read_is_skipped_and_said_so(tmp_path, capsys):
    runs = tmp_path / "runs"
    run = await make_run(runs)
    shutil.copytree(run.root, runs / "older")
    config = yaml.safe_load((runs / "older" / "config.yaml").read_text())
    config["town"]["day"]["closing"] = "18:00"  # a field the current schema does not know
    (runs / "older" / "config.yaml").write_text(yaml.safe_dump(config))
    (runs / "bare").mkdir()  # a run directory without its configuration
    shutil.copy(run.root / "manifest.json", runs / "bare")
    publish(["--runs-root", str(runs), "--out", str(tmp_path / "site")])
    index = read(tmp_path / "site", "data/index.json")
    assert [r["name"] for r in index["runs"]] == ["town"]
    bare, older = index["skipped"]
    assert older["name"] == "older" and older["reason"] == UNREADABLE_CONFIG
    assert "town.day.closing" in older["detail"] and "older/config.yaml" in older["detail"]
    assert str(runs) not in older["detail"]
    assert bare["name"] == "bare" and bare["reason"] == UNREADABLE_CONFIG
    assert bare["detail"].startswith("FileNotFoundError: ")
    assert not (tmp_path / "site" / "data" / "runs" / "older").exists()
    assert "skipped older: " in capsys.readouterr().out


async def test_publishing_refuses_unsafe_targets_and_malformed_runs(tmp_path):
    runs = tmp_path / "runs"
    run = await make_run(runs)
    with pytest.raises(ValueError, match="inside the runs root"):
        Publisher(runs, runs / "site")
    with pytest.raises(ValueError, match="inside the results root"):
        Publisher(runs, tmp_path / "results" / "site", tmp_path / "results")
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    (stranger / "notes.txt").write_text("mine")
    with pytest.raises(FileExistsError):
        Publisher(runs, stranger).publish()
    assert files(stranger) == {"notes.txt": b"mine"}

    lines = run.world_log_path.read_bytes().split(b"\n")
    lines[3] = lines[3][:-3]  # no longer JSON
    run.world_log_path.write_bytes(b"\n".join(lines))
    site = Publisher(runs, tmp_path / "site").publish()
    [skipped] = site.skipped
    assert skipped["name"] == "town" and skipped["reason"] == PUBLISHING_FAILED
    assert skipped["detail"].startswith("ValueError: ") and str(runs) not in skipped["detail"]
    assert "town/world.jsonl" in skipped["detail"] and "malformed" in skipped["detail"]
    assert not (tmp_path / "site" / "data" / "runs").exists()
    assert read(tmp_path / "site", "data/index.json")["runs"] == []


def test_the_webui_verifier_expects_the_bundle_format_published():
    assert BUNDLE_FORMAT == FORMAT


async def test_a_site_published_with_another_manifest_is_rebuilt(tmp_path):
    runs, out = tmp_path / "runs", tmp_path / "site"
    await make_run(runs)
    Publisher(runs, out).publish()
    day = out / RUN / "events" / "day-01.json"
    original = day.read_bytes()
    day.write_bytes(original.replace(b'"day":1', b'"day":1 '))
    Publisher(runs, out).publish()
    assert day.read_bytes() != original  # a settled file of this very bundle is kept

    manifest = out / "data" / "manifest.json"
    document = json.loads(manifest.read_bytes())
    document["files"] = [kind for kind in document["files"] if kind["kind"] != "trace_day"]
    manifest.write_text(json.dumps(document))
    Publisher(runs, out).publish()
    assert day.read_bytes() == original


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="GNU coreutils are missing")
async def test_push_uploads_only_what_changed_and_switches_the_site_at_once(tmp_path):
    ssh = tmp_path / "ssh"
    ssh.write_text('#!/bin/sh\nshift\nexec sh -c "$1"\n')  # runs the command here instead
    ssh.chmod(0o755)
    runs, out, server = tmp_path / "runs", tmp_path / "site", tmp_path / "server"

    def push() -> str:
        command = [str(PUSH), "example.org", str(out), str(server)]
        environment = {"PATH": "/usr/bin:/bin", "PUSH_SSH": str(ssh)}
        result = subprocess.run(command, capture_output=True, text=True, env=environment)
        assert result.returncode == 0, result.stderr
        return result.stdout

    run = await make_run(runs)
    Publisher(runs, out).publish()
    first = files(out)
    assert push().startswith(f"{len(first)} files uploaded")
    assert files(server / "site") == first
    old = (server / "site").resolve()

    last = read(out, f"{RUN}/run.json")["entries"]
    with run.world_log_path.open("a") as log:
        log.write(entry(last + 1, "checkpoint", at("02:30", day=3), real_time=2e9, day=2) + "\n")
    Publisher(runs, out).publish()
    second = files(out)
    changed = {name for name, data in second.items() if first.get(name) != data}
    removed = set(first) - set(second)
    output = push()
    assert output.startswith(f"{len(changed)} files uploaded")
    assert f", {len(removed)} removed;" in output
    new = (server / "site").resolve()
    assert new != old and files(server / "site") == second
    assert files(old) == first  # the previous release is kept as it was
    unchanged = set(first) & set(second) - changed
    assert unchanged and all(
        (old / name).stat().st_ino == (new / name).stat().st_ino for name in unchanged
    )
    assert push().strip() == "the server already has this site"
    assert sorted(path.name for path in (server / "releases").iterdir()) == sorted(
        [old.name, new.name]
    )


def test_encoding_is_deterministic_and_compact():
    assert encode({"b": 1, "a": [1.5, None, "é"]}) == '{"b":1,"a":[1.5,null,"é"]}'.encode()
    with pytest.raises(ValueError):
        encode({"x": float("nan")})
