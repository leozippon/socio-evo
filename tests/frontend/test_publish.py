"""The publisher: the bundle it writes matches its contract in frontend/README.md, references
carry hashes and stay inside the site, the treasury's books the money dashboard reads are the
checkpoint's, agents are published as their repositories and traces hold them, settled days are
kept, a run in progress and a run just created are published, an unreadable configuration is
skipped and said so, nothing is written into a run, unsafe targets are refused, the evaluation
and the comparison are read from the results root, and the push script switches a release
atomically."""

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

from analysis.measures import MEASURES, TOWN
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
from ops.webui.verify import BUNDLE_FORMAT
from tests.support.runs import RUN, entry, files, make_run, new_town, write_results
from tests.support.towns import STOCK, at, town_config
from world.clock import DAY
from world.log import KINDS as LOG_KINDS

PROJECT = Path(__file__).parents[2]
README = PROJECT / "frontend" / "README.md"
PUSH = PROJECT / "frontend" / "deploy" / "push.sh"
RESIDENTS = ("Mei", "Tomas", "Aisha", "Olga", "Jonas", "Lucia", "Vera")
MARKERS = (
    "claim", "assign", "submission", "abandon", "service", "speech", "message", "move", "order",
    "cook", "price", "examination", "treatment", "report", "announcement", "grant", "illness",
    "recovered", "bedridden", "move_in", "journal", "forced_sleep", "settlement", "condition",
    "task_arrived", "task_withdrawn", "delivery",
)  # fmt: skip
"""The kinds of marker the timeline publishes, on a resident's lane or the town's."""


def stamps(root: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def read(site: Path, path: str) -> Any:
    return json.loads((site / path.split("?")[0]).read_bytes())


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
        if kind in MARKERS
    }
    assert set(markers) == set(MARKERS)
    timeline = read(site, f"{RUN}/timeline.json")
    seen = set()
    for marker in [
        *timeline["markers"],
        *(m for lane in timeline["residents"] for m in lane["markers"]),
    ]:
        seen.add(marker["kind"])
        assert set(marker) <= {"seq", "t", "kind", "place"} | markers[marker["kind"]], marker
    assert set(MARKERS) - seen == {
        "abandon",
        "illness",
        "recovered",
        "bedridden",
        "move_in",
        "message",
    }

    measures = read(site, f"{RUN}/measures.json")
    for row in measures["rows"]:
        assert set(row) == {"resident", "occupation", "day", "date", *MEASURES}
    assert [set(row) for row in measures["town"]] == [{"day", "date", *TOWN}]
    kinds = set()
    for path in (site / RUN / "events").iterdir():
        for found in json.loads(path.read_bytes())["entries"]:
            kinds.add(found["kind"])
            assert found["kind"] in LOG_KINDS
            assert not set(found["payload"]) & bundle.OMITTED
    assert {"submission", "checkpoint", "speech", "move"} <= kinds


def test_the_treasury_s_books_are_the_checkpoint_s_and_the_markers_add_up_to_them(published):
    """What the money dashboard reads of the treasury (`measures.json` `town` and the residents'
    rows) is what the checkpoint saved: its balance, the rent owed to it and the salary it owes,
    and what it took in and paid out by kind on the day its midnight closed, which the markers
    of that calendar day add up to: the tax withheld from the shares, the sales, the dish and the
    fees, the rent and the salary of the statements, and the grant. Each business's books are the
    fixture's day: Olga's sales against her order, Jonas's omelette against his ingredients, and
    Lucia's fees."""
    runs, _, site = published
    measures = read(site, f"{RUN}/measures.json")
    timeline = read(site, f"{RUN}/timeline.json")
    saved = json.loads((runs / "town" / "checkpoints" / "day-01.json").read_text())
    treasury, [town] = saved["treasury"], measures["town"]
    books = (town["treasury"], town["salary_owed"], town["arrears"])
    assert books == (treasury["balance"], 0, 5) and treasury["owed"] == {}
    assert {row["resident"]: row["arrears"] for row in measures["rows"] if row["arrears"]} == (
        treasury["arrears"]
    ) == {"Aisha": 5}  # fmt: skip
    ledger = {"tax": town["taken_tax"], "rent": town["taken_rent"]}
    ledger |= {"salary": town["paid_salary"], "grant": town["paid_grant"]}
    assert ledger == treasury["yesterday"] == {"tax": 13, "rent": 185, "salary": 30, "grant": 5}
    assert town["money"] == sum(r["inventory"]["money"] for r in saved["residents"].values())

    day = [m for lane in timeline["residents"] for m in lane["markers"] if m["t"] <= DAY]
    statements = [m for m in day if m["kind"] == "settlement"]
    taxed = ("service", "move", "examination", "treatment")
    assert sum(m["tax"] for m in day if m["kind"] in taxed) == ledger["tax"]
    assert sum(m["rent_paid"] for m in statements) == ledger["rent"]
    assert sum(m["salary_paid"] for m in statements) == ledger["salary"]
    assert sum(m["amount"] for m in day if m["kind"] == "grant") == ledger["grant"]

    assert (town["clients"], town["supplier"]) == (50, 10)
    assert town["store_takings"] == 4 + 20 + 12  # the eggs and vegetables, and Mei's bread
    assert (town["kitchen_takings"], town["kitchen_costs"]) == (10, 4 + 20)
    assert town["surgery_takings"] == 10 + 30


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


def test_the_index_names_the_runs_and_the_comparison(published):
    runs, _, site = published
    index = read(site, "data/index.json")
    assert [(run["name"], run["status"]) for run in index["runs"]] == [
        ("town", "running"),
        ("twin", "running"),
    ]
    town = index["runs"][0]
    assert (town["settled_day"], town["last_day"], town["residents"]) == (1, 2, list(RESIDENTS))
    headline = town["headline"]
    assert (headline["arrived"], headline["accepted"], headline["withdrawn"]) == (3, 1, 2)
    assert (headline["sales"], headline["dishes"], headline["examinations"]) == (3, 2, 1)
    assert headline["gifts"] == 1  # the money Mei passed Tomas; the chef's soup is a dish
    assert (headline["treatments"], headline["announcements"]) == (1, 1)
    timeline = read(site, f"{RUN}/timeline.json")
    purses = sorted(lane["purse"][-1][1] for lane in timeline["residents"])
    assert headline["day"] == 2 and headline["purse"] == {
        "min": purses[0],
        "median": purses[3],
        "max": purses[-1],
    }
    checkpoint = json.loads((runs / "town" / "checkpoints" / "day-01.json").read_text())
    assert headline["treasury"] == checkpoint["treasury"]["balance"]
    assert index["skipped"] == []
    [comparison] = index["comparisons"]
    assert (comparison["name"], comparison["runs"]) == ("runs", ["town", "twin"])
    doc = read(site, f"data/{comparison['url']}")
    assert doc["runs"] == ["town", "twin"]
    by_measure = {found["measure"]: found for found in doc["measures"]}
    assert by_measure["capability"]["declared"] and by_measure["capability"]["days"] == [0, 1]
    rows = {row["run"]: row for row in by_measure["capability"]["runs"]}
    assert (rows["town"]["statistic"], rows["town"]["values"]) == ("change", {"Mei": 0.25})
    assert rows["twin"]["values"] == {}  # day 0 is shared; the twin has no results of its own
    assert by_measure["capability"]["daily"] == {"town": [[0, 0.25], [1, 0.5]], "twin": [[0, 0.25]]}
    accepted = by_measure["tasks_accepted"]
    assert accepted["days"] == [1, 1] and not accepted["declared"]
    assert [row["run"] for row in accepted["runs"]] == ["town", "twin"]


def test_the_world_lays_the_town_out(published):
    _, _, site = published
    world = read(site, f"{RUN}/world.json")
    assert [(p["id"], p["kind"], p["x"], p["y"]) for p in world["places"]] == [
        ("mill-street-house", "home", 0.5, 0.0),
        ("college-flat", "home", 1.5, 0.0),
        ("workshop", "office", 0.0, 1.5),
        ("cafe", "restaurant", 0.0, 3.0),
        ("park", "social", 1.0, 3.0),
        ("store", "store", 2.0, 3.0),
        ("clinic", "hospital", 1.0, 1.5),
        ("hall", "hall", 2.0, 1.5),
    ]
    assert [(p["rent"], p["rooms"], p["comfort"]) for p in world["places"]][:3] == [
        (20, 3, 0.9),
        (30, 6, 1.0),
        (None, None, None),
    ]
    assert [g["id"] for g in world["goods"]] == [
        "bread", "eggs", "vegetables", "bicycle", "phone", "coat",
    ]  # fmt: skip
    assert (world["goods"][0]["wholesale"], world["goods"][0]["price"]) == (2, 4)
    assert [(d["id"], d["ingredients"], d["price"]) for d in world["dishes"]] == [
        ("omelette", {"eggs": 2, "vegetables": 1}, 10),
        ("soup", {"vegetables": 2}, 8),
    ]
    assert world["hospital"] == {"examination": 10, "treatment": 30, "restores": 25}
    assert world["treasury"] == {"start": 1000, "spares": 10}
    assert world["store"]["stock"]["bread"] == 10 and world["tax"] == 0.1
    assert (world["work"]["payment"], world["work"]["leader_share"]) == (50, 0.2)
    occupations = {o["id"]: o for o in world["occupations"]}
    assert occupations["chef"] == {
        "id": "chef", "title": "the chef", "workplace": "cafe", "duty": "workplace", "salary": 0,
    }  # fmt: skip
    assert (occupations["mayor"]["duty"], occupations["mayor"]["salary"]) == ("anywhere", 30)
    assert [(r["name"], r["occupation"]) for r in world["residents"]][3:] == [
        ("Olga", "shopkeeper"), ("Jonas", "chef"), ("Lucia", "doctor"), ("Vera", "mayor"),
    ]  # fmt: skip
    assert world["needs"]["health"]["bands"][-1] == {
        "floor": 0, "name": "gravely ill", "seen": "looking gravely ill",
    }  # fmt: skip
    assert [r["name"] for r in world["residents"]] == list(RESIDENTS)
    assert "## Your work and your town" in world["residents"][0]["rules"]
    assert world["name"] == "town" and world["currency"] == "$"
    assert world["social"] == {"silence_minutes": 10}


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
        assert "memory/notes.md" in found["diff"] and "session.jsonl" not in found["diff"]

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
    twin = read(site, "data/runs/twin/evaluation.json")  # no results of its own yet: day 0 alone
    assert twin["capability"] == [{"resident": "Mei", "day": 0, "capability": 0.25}]
    assert twin["mask"] == [{"resident": "Mei", "day": 0, "mask": 0.4, "lie": 0.1}]
    assert twin["journals"] == [] and twin["problems"] == []

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
    assert [(r["versions"], r["trace_days"]) for r in document["residents"]] == [(0, [])] * 7
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
    assert [status(name) for name in RESIDENTS] == statuses == [""] * 7


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


def test_the_holders_follow_every_move_and_agree_with_the_checkpoint(published):
    """What Mei, Olga and the places held over the fixture's day, move by move: the bread Mei
    bought, left at the Store for Olga, ate and left at home, where it lies; the shelves, the
    larder and the portions, the soup nobody had gone at midnight; and at the checkpoint every
    holder as the moves left it is what the checkpoint saved."""
    runs, _, site = published
    timeline = read(site, f"{RUN}/timeline.json")
    start, end = timeline["start"], at("02:30", day=2)
    things = {lane["name"]: lane["things"] for lane in timeline["residents"]}
    holders = timeline["holders"]
    assert things["Mei"] == [
        [start, {}],  # the dishes she had at 11:00 were eaten as they were served
        [at("11:15"), {"bread": 2}],  # three bought, one left at the Store
        [at("12:00"), {"bread": 1}],
        [at("12:05"), {}],
    ]
    assert things["Olga"] == [[start, {}]]  # taken at 11:15 and eaten there and then
    assert holders["store"] == [[start, {}]]
    assert holders["mill-street-house"] == [[start, {}], [at("12:05"), {"bread": 1}]]
    assert holders["portions"] == [
        [start, {}],
        [at("07:30"), {"omelette": 1, "soup": 2}],
        [at("11:00"), {"soup": 1}],
        [DAY, {}],
    ]
    assert holders["larder"] == [[start, {}], [at("07:10"), {"eggs": 2, "vegetables": 5}],
                                 [at("07:30"), {}]]  # fmt: skip
    shelves = dict(holders["shelves"])
    assert shelves[at("11:15")]["bread"] == 10 - 3 and shelves[at("08:00", day=2)]["bread"] == 12
    saved = json.loads((runs / "town" / "checkpoints" / "day-01.json").read_text())
    kept = saved["holders"] | {n: r["inventory"]["items"] for n, r in saved["residents"].items()}
    for key, points in [*things.items(), *holders.items()]:
        before = [state for t, state in points if t < end][-1]
        after = [state for t, state in points if t <= end][-1]
        assert before == after == kept[key], key


def test_a_checkpoint_sets_every_holder_as_it_saved_it(tmp_path):
    """Between checkpoints the moves count; at a checkpoint what it saved is what each holder
    has, whatever the moves before it said; a move of more than its source holds fails."""
    town = town_config()
    start, end = at("02:30"), at("02:30", day=2)

    def move(t: int, seq: int, item: str, units: int, source: str, target: str | None) -> dict:
        found = {"seq": seq, "t": t, "kind": "move", "place": "park", "item": item}
        return found | {"units": units, "source": source, "target": target, "money": 0}

    data = {
        "start": start,
        "now": at("12:00", day=2),
        "markers": [],
        "residents": [
            {"name": "Mei", "markers": [move(at("09:00"), 1, "bread", 2, "shelves", "Mei"),
                                        move(at("10:00"), 2, "bread", 1, "Mei", "park")]},
            {"name": "Tomas", "markers": [move(at("11:00"), 3, "bread", 1, "park", "Tomas"),
                                          move(at("09:00", day=2), 4, "bread", 1, "Tomas", None)]},
        ],
    }  # fmt: skip
    holders = {key: {} for key in ("larder", "portions", *(p.id for p in town.places))}
    saved = {
        "time": end,
        "residents": {"Mei": {"inventory": {"items": {"bread": 1}}},
                      "Tomas": {"inventory": {"items": {"bread": 3}}}},
        "holders": holders | {"shelves": {"bread": 8}},
    }  # fmt: skip
    things, others = bundle.holdings({1: saved}, town, data)
    assert things["Mei"] == [
        [start, {}],
        [at("09:00"), {"bread": 2}],
        [at("10:00"), {"bread": 1}],
    ]
    assert things["Tomas"] == [
        [start, {}],
        [at("11:00"), {"bread": 1}],
        [end, {"bread": 3}],  # the checkpoint's, not the moves'
        [at("09:00", day=2), {"bread": 2}],
    ]
    assert others["park"] == [[start, {}], [at("10:00"), {"bread": 1}], [at("11:00"), {}]]
    assert others["shelves"] == [
        [start, STOCK],
        [at("09:00"), {**STOCK, "bread": 8}],
        [end, {"bread": 8}],  # as saved
    ]
    data["residents"][0]["markers"].append(move(at("10:30"), 5, "bread", 2, "Mei", None))
    with pytest.raises(ValueError, match="entry 5: Mei holds 1 of bread, not 2"):
        bundle.holdings({1: saved}, town, data)


def test_the_graph_counts_who_served_whom(published):
    """Olga sold Jonas eggs and vegetables for the kitchen and Mei bread; Jonas served Mei the
    omelette and a soup unpaid; Lucia examined and treated her."""
    _, _, site = published
    graph = read(site, f"{RUN}/measures.json")["graph"]
    served = {(row["source"], row["target"]): row["served"] for row in graph if row["served"]}
    assert served == {
        ("Olga", "Jonas"): 2,
        ("Olga", "Mei"): 1,
        ("Jonas", "Mei"): 2,  # the omelette she bought and the soup he passed her
        ("Lucia", "Mei"): 2,
    }


def test_encoding_is_deterministic_and_compact():
    assert encode({"b": 1, "a": [1.5, None, "é"]}) == '{"b":1,"a":[1.5,null,"é"]}'.encode()
    with pytest.raises(ValueError):
        encode({"x": float("nan")})
