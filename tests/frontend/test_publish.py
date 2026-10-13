import hashlib
import json
import re
import shutil
import subprocess
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import urlopen

import pytest
import yaml

from analysis import measure, read_run, run_usage
from core.agent.evolution import History
from core.agent.prompts import REPLY
from core.interaction import DAY_ONE, EventKind
from frontend import bundle
from frontend.publish import FORMAT, KINDS, Publisher, encode
from frontend.publish import main as publish
from frontend.server import DevServer
from infrastructure.storage import RunDirectory
from ops.webui.verify import BUNDLE_FORMAT
from tests.analysis.test_measures import old_shape, truncate_mid_day
from tests.conftest import TOWN

PROJECT = Path(__file__).parents[2]
README = PROJECT / "frontend" / "README.md"
PUSH = PROJECT / "frontend" / "deploy" / "push.sh"
RUN = "data/runs/town/seed-0007"
ARMS = ("selection-comfortable", "assignment-comfortable")
SHARED = {"Count": "counts", "Share": "shares", "Column": "values"}
"""The README's tables of fields that several objects share, by the field that holds them."""
OLD_MEASURES = {
    "runs/v1/pilot/seed-0000": "1ed6c738eb85fe95",
    "runs/v1/smoke/seed-0000": "087742a7084d5432",
}
"""The first 16 hex digits of the SHA-256 of the published measures of the runs of the first
town, archived under runs/v1 on the machine where they ran, as they were before the second town."""
LATER_KINDS = ("vote", "apply", "hire", "dismiss", "resign")
"""Kinds of decision added since the first town, which its measures count as none."""
LATER_FIELDS = {
    "agents": {
        "position": "freelance",
        "wages_received": 0,
        "wages_paid": 0,
        "attended": 0,
        "applied": 0,
        "hired": 0,
        "dismissed": 0,
        "resigned": 0,
    },
    "society": {
        "wages": 0,
        "attendance": 0,
        "applications": 0,
        "hires": 0,
        "dismissals": 0,
        "notices": 0,
    },
}
"""Fields of the measures added since the first town, with the values its measures hold."""


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


@pytest.fixture(scope="module")
def published(town, tmp_path_factory) -> tuple[Path, Path]:
    """A runs root holding the town and a study of two arms, each the town again, and the
    study's file."""
    root = tmp_path_factory.mktemp("published")
    runs = root / "runs"
    for experiment in ("town", *(f"pair-{arm}" for arm in ARMS)):
        shutil.copytree(town, runs / experiment / "seed-0007")
    study = root / "pair.yaml"
    arms = {arm: [] for arm in ARMS}
    study.write_text(yaml.safe_dump({"name": "pair", "arms": arms}, sort_keys=False))
    return runs, study


@pytest.fixture(scope="module")
def site(published, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("site")
    runs, study = published
    Publisher(runs, out, [study]).publish()
    return out


def in_progress(town: Path, runs: Path) -> Path:
    """A copy of the town under `runs`, stopped in the middle of day 2 while running."""
    root = runs / "town" / "seed-0007"
    shutil.copytree(town, root)
    truncate_mid_day(root, 2)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest.update(status="running", ended_at=None)
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root


def complete(town: Path, root: Path) -> None:
    """Let the copy at `root` run to the end of the town."""
    for name in ("events.jsonl", "manifest.json"):
        shutil.copy(town / name, root / name)
    for checkpoint in (town / "checkpoints").iterdir():
        shutil.copy(checkpoint, root / "checkpoints")


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


def test_every_file_has_exactly_the_documented_fields(site):
    documented = contract()
    assert set(documented) == set(KINDS.values())
    shared = {
        SHARED[header]: set(fields) for header in SHARED for fields in contract(header).values()
    }
    assert set(shared) == set(SHARED.values())
    for pattern, fields in documented.items():
        paths = sorted((site / "data").glob(re.sub(r"\{\w+\}", "*", pattern)))
        assert paths, pattern
        children = defaultdict(set)
        for field in fields:
            parent, _, name = field.rpartition(".")
            children[parent].add(name)
            if name in shared:
                children[field] = shared[name]
        for path in paths:
            document = json.loads(path.read_bytes())
            for parent, names in children.items():
                for value in values_at(document, parent):
                    assert set(value) == names, (path, parent)

    kinds = dict(re.findall(r"^\| `(\w+)` \|[^|]*\|[^|]*\| (.*) \|$", README.read_text(), re.M))
    assert set(kinds) == {str(kind) for kind in EventKind}
    seen = set()
    for path in (site / RUN / "events").iterdir():
        for event in json.loads(path.read_bytes())["events"]:
            seen.add(event["kind"])
            assert set(event["payload"]) <= set(re.findall(r"`(\w+)`", kinds[event["kind"]]))
    assert len(seen) >= 20


def test_references_carry_the_hash_of_files_inside_the_site(site, published):
    for name, data in files(site).items():
        assert not (site / name).is_symlink()
        assert str(published[0]) not in data.decode()
        if not name.endswith(".json"):
            continue
        document = data.decode()
        for reference in re.findall(r'"([^"?]+\?[vr]=[0-9a-f]{16})"', document):
            url = urljoin(f"http://site/{quote(name)}", reference)
            target = (site / urlsplit(url).path.lstrip("/")).resolve()
            assert target.is_relative_to(site.resolve())
            digest = hashlib.sha256(target.read_bytes()).hexdigest()[:16]
            assert reference.endswith(f"={digest}")


def test_the_bundle_holds_no_model_call(site, town):
    calls = [json.loads(line) for line in (town / "llm_calls.jsonl").read_text().splitlines()]
    prompts = [call["request"]["messages"][-1]["content"] for call in calls]
    assert all(REPLY in prompt for prompt in prompts[:10])

    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, list):
            return {key for item in value for key in keys(item)}
        return set()

    for name, data in files(site).items():
        assert REPLY.encode() not in data
        if name.endswith(".json"):
            assert not keys(json.loads(data)) & {"messages", "request", "response", "reasoning"}


def test_an_agent_is_published_as_its_repository_holds_it(site, town):
    log = [json.loads(line) for line in (town / "events.jsonl").read_text().splitlines()]
    for agent in ("Ana", "Ben", "Cai"):
        directory, base = town / "agents" / agent, site / RUN / "agents" / agent
        history = json.loads((base / "versions.json").read_bytes())
        commits = subprocess.run(
            ["git", "rev-list", "--reverse", "HEAD"], cwd=directory, capture_output=True, text=True
        ).stdout.split()
        assert [version["commit"] for version in history["versions"]] == commits
        assert [
            (version["level"], version["trigger"], version["commit"])
            for version in history["versions"]
            if version["level"]
        ] == [
            (event["payload"]["level"], event["payload"]["trigger"], event["payload"]["commit"])
            for event in log
            if event["kind"] == "evolution" and event["actor"] == agent
        ]

        last = history["versions"][-1]
        day = json.loads((base / urlsplit(last["url"]).path).read_bytes())
        [state] = [
            version["state"] for version in day["versions"] if version["commit"] == last["commit"]
        ]
        memory = directory / "memory"
        assert state["policy"] == (directory / "parameters" / "policy.md").read_text()
        skills = {path.stem: path.read_text() for path in sorted(memory.glob("skills/*.md"))}
        assert skills and state["skills"] == skills
        insights = (memory / "insights.jsonl").read_text().splitlines()
        assert state["insights"] == [json.loads(line) for line in insights]
        diary = sorted(memory.glob("diary/day-*.md"))
        assert state["diary"] == [int(path.stem.removeprefix("day-")) for path in diary]
        for entry in history["diary"]:
            holder = json.loads((base / urlsplit(entry["url"]).path).read_bytes())
            [text] = [found["text"] for found in holder["diary"] if found["day"] == entry["day"]]
            assert text == (memory / "diary" / f"day-{entry['day']:04d}.md").read_text()


def test_a_run_in_progress_is_published_and_completed_by_a_later_publish(town, tmp_path):
    runs, out = tmp_path / "runs", tmp_path / "site"
    root = in_progress(town, runs)
    Publisher(runs, out).publish()
    run = json.loads((out / RUN / "run.json").read_bytes())
    assert (run["status"], run["settled_day"], run["last_day"]) == ("running", 1, 2)
    assert [(day["day"], day["settled"]) for day in run["event_days"]] == [(1, True), (2, False)]
    assert "?v=" in run["event_days"][0]["url"] and "?r=" in run["event_days"][1]["url"]
    before = stamps(out)

    complete(town, root)
    written = set(Publisher(runs, out).publish().written)
    settled = {
        f"{RUN}/events/day-0001.json",
        f"{RUN}/world.json",
        *(f"{RUN}/agents/{agent}/day-0001.json" for agent in ("Ana", "Ben", "Cai")),
    }
    assert not written & settled
    assert {f"{RUN}/events/day-0002.json", f"{RUN}/events/day-0003.json"} <= written
    assert all(stamps(out)[name] == before[name] for name in settled)

    fresh = tmp_path / "fresh"
    Publisher(town.parents[1], fresh).publish()
    assert files(out) == files(fresh)


def test_a_run_just_created_is_published_before_its_first_checkpoint(tmp_path):
    runs = tmp_path / "runs"
    run = RunDirectory.create(runs, TOWN.name, 7, config=TOWN, code_revision="test")
    History.init(run.agent_dir("Ana"), "Ana", DAY_ONE)  # its first commit is still to come
    Publisher(runs, tmp_path / "site").publish()
    document = json.loads((tmp_path / "site" / RUN / "run.json").read_bytes())
    assert (document["settled_day"], document["last_day"], document["events"]) == (0, 0, 0)
    assert document["event_days"] == []
    assert [agent["versions"] for agent in document["agents"]] == [0, 0, 0]


def test_republishing_an_unchanged_run_rewrites_nothing(town, tmp_path, capsys):
    out = tmp_path / "site"
    publish(["--runs-root", str(town.parents[1]), "--out", str(out)])
    before = stamps(out)
    publisher = Publisher(town.parents[1], out)
    assert publisher.publish().written == []
    assert publisher.publish().written == []
    publish(["--runs-root", str(town.parents[1]), "--out", str(out)])
    assert capsys.readouterr().out.splitlines()[-1].endswith(": 0 written, 0 removed")
    assert stamps(out) == before


def test_publishing_never_modifies_the_run(town, tmp_path):
    def status(agent: str) -> str:
        command = ["git", "status", "--porcelain", "--untracked-files=all"]
        return subprocess.run(
            command, cwd=town / "agents" / agent, capture_output=True, text=True, check=True
        ).stdout

    agents = ("Ana", "Ben", "Cai")
    statuses = [status(agent) for agent in agents]  # refreshes the index: before the snapshot
    before = stamps(town)
    Publisher(town.parents[1], tmp_path / "site").publish()
    assert stamps(town) == before
    assert [status(agent) for agent in agents] == statuses == ["", "", ""]


def test_publishing_refuses_unsafe_targets_and_malformed_runs(town, tmp_path):
    runs = tmp_path / "runs"
    root = runs / "town" / "seed-0007"
    shutil.copytree(town, root)
    with pytest.raises(ValueError, match="inside the runs root"):
        Publisher(runs, runs / "site")
    stranger = tmp_path / "stranger"
    stranger.mkdir()
    (stranger / "notes.txt").write_text("mine")
    with pytest.raises(FileExistsError):
        Publisher(runs, stranger).publish()
    assert files(stranger) == {"notes.txt": b"mine"}

    log = root / "events.jsonl"
    lines = log.read_bytes().split(b"\n")
    lines[3] = lines[3].replace(b'"seq": 3,', b'"seq": "three",')
    log.write_bytes(b"\n".join(lines))
    with pytest.raises(ValueError, match="events.jsonl:4") as error:
        Publisher(runs, tmp_path / "site").publish()
    assert any(str(root) in note for note in error.value.__notes__)


def test_the_dev_server_serves_exactly_the_published_site(published, site, tmp_path):
    runs, study = published
    server = DevServer(("127.0.0.1", 0), Publisher(runs, tmp_path / "served", [study]), 0.1)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"

    def get(path: str) -> tuple[int, bytes, str | None]:
        try:
            with urlopen(urljoin(base, path)) as response:
                return response.status, response.read(), response.headers["Cache-Control"]
        except HTTPError as error:
            return error.code, b"", None

    try:
        published = files(site)
        for name, data in published.items():
            assert get(quote(name))[:2] == (200, data)
        assert get("")[1] == published["index.html"]
        run = json.loads(published[f"{RUN}/run.json"])
        assert get(f"{RUN}/{run['world']}")[2] == "public, max-age=31536000, immutable"
        assert get("data/index.json")[2] == "no-store"
        for missing in ("data/", "data/runs/", "%2e%2e/%2e%2e/etc/passwd", "data/nothing.json"):
            assert get(missing)[0] == 404
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="GNU coreutils are missing")
def test_push_uploads_only_what_changed_and_switches_the_site_at_once(town, tmp_path):
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

    root = in_progress(town, runs)
    Publisher(runs, out).publish()
    first = files(out)
    assert push().startswith(f"{len(first)} files uploaded")
    assert files(server / "site") == first
    old = (server / "site").resolve()

    complete(town, root)
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


def test_a_study_and_the_traits_of_its_runs_are_published(site):
    index = json.loads((site / "data" / "index.json").read_bytes())
    [entry] = index["studies"]
    assert (entry["study"], entry["dry_run"]) == ("pair", False)
    assert entry["arms"] == [{"arm": arm, "experiment": f"pair-{arm}"} for arm in ARMS]
    study = json.loads((site / "data" / urlsplit(entry["url"]).path).read_bytes())
    assert [(w["name"], w["first"], w["last"]) for w in study["windows"]] == [
        ("main", 1, 1),
        ("late", 2, None),
    ]
    assert [(row["arm"], row["seed"], row["window"]) for row in study["runs"]] == [
        (arm, 7, window) for arm in ARMS for window in ("main", "late")
    ]
    between = [row for row in study["contrasts"] if row["contrast"].startswith("selection")]
    assert {row["window"] for row in between} == {"main", "late"}
    for row in between:  # the two arms are the same run
        assert row["differences"] in ([], [{"seed": 7, "difference": 0}])
        assert row["p"] in (None, 1.0)

    run = json.loads((site / RUN / "run.json").read_bytes())
    traits = json.loads((site / RUN / urlsplit(run["traits"]).path).read_bytes())
    assert [(w["name"], w["first_day"], w["last_day"]) for w in traits["windows"]] == [
        ("run", 1, 3),
        ("phase-1", 1, 1),
        ("phase-2", 2, 3),  # the rent rose at 13:00 on day 2
    ]
    world = json.loads((site / RUN / urlsplit(run["world"]).path).read_bytes())
    assert {(a["name"], a["initial_balance"], a["obligation"]) for a in world["agents"]} == {
        (agent, 100, 0) for agent in ("Ana", "Ben", "Cai")
    }


def test_a_run_recorded_before_tasks_had_parts_is_published_without_traits(town, tmp_path):
    runs = tmp_path / "runs"
    root = runs / "pair-solo" / "seed-0007"
    shutil.copytree(town, root)
    log = root / "events.jsonl"
    records = [old_shape(json.loads(line)) for line in log.read_text().splitlines()]
    log.write_text("".join(json.dumps(record) + "\n" for record in records))
    config = yaml.safe_load((root / "config.yaml").read_text())
    conditions = config["environment"]["conditions"]
    conditions["tasks_per_day"] = conditions.pop("one_part_tasks")
    del conditions["two_part_tasks"]
    del config["environment"]["setting"]  # nor did towns have a setting
    (root / "config.yaml").write_text(yaml.safe_dump(config))
    Publisher(runs, tmp_path / "site").publish()
    published = tmp_path / "site" / "data/runs/pair-solo/seed-0007"
    run = json.loads((published / "run.json").read_bytes())
    assert run["traits"] is None and not (root.parent / "traits.json").exists()
    world = json.loads((published / urlsplit(run["world"]).path).read_bytes())
    assert world["setting"] == {
        "name": None,
        "backdrop": "",
        "currency": {"unit": "crown", "units": "crowns", "symbol": None},
        "start_date": "2001-01-01",
        "newcomers": True,
    }

    study = tmp_path / "pair.yaml"
    study.write_text(yaml.safe_dump({"name": "pair", "arms": {"solo": []}}))
    with pytest.raises(ValueError, match="before tasks had parts"):
        Publisher(runs, tmp_path / "other", [study]).publish()


def test_a_run_is_published_from_its_own_directory_whatever_became_of_its_bank(
    site, town, tmp_path
):
    """With its task bank gone, a run publishes the traits it did; one recorded before an
    assessment said whether a hand-in writes out the examples publishes that share as
    unknown, over no hand-in judged, and the rest as before."""
    runs = tmp_path / "runs"
    for experiment in ("town", "older"):
        root = runs / experiment / "seed-0007"
        shutil.copytree(town, root)
        config = yaml.safe_load((root / "config.yaml").read_text())
        config["tasks"]["banks"] = {"programming": str(tmp_path / "no-bank")}
        (root / "config.yaml").write_text(yaml.safe_dump(config))
    log = runs / "older" / "seed-0007" / "events.jsonl"
    records = [json.loads(line) for line in log.read_text().splitlines()]
    for record in records:
        if record["kind"] == "work_assessed":
            del record["payload"]["special_cased"]
    log.write_text("".join(json.dumps(record) + "\n" for record in records))
    Publisher(runs, tmp_path / "site").publish()

    def published(site: Path, experiment: str) -> dict[str, Any]:
        run = json.loads((site / f"data/runs/{experiment}/seed-0007/run.json").read_bytes())
        path = f"data/runs/{experiment}/seed-0007/{urlsplit(run['traits']).path}"
        return json.loads((site / path).read_bytes())

    assert published(tmp_path / "site", "town") == published(site, "town")
    recorded = published(site, "town")["windows"][0]["town"]
    before = published(tmp_path / "site", "older")["windows"][0]["town"]
    assert recorded["counts"]["special_cased_judged"] == recorded["counts"]["checked_finished"] > 0
    unknown = {"special_cased_judged": 0, "special_cased": 0}
    assert before["counts"] == {**recorded["counts"], **unknown}
    assert before["shares"] == {**recorded["shares"], "special_cased_share": None}


def test_the_webui_verifier_expects_the_bundle_format_published():
    assert BUNDLE_FORMAT == FORMAT


def test_a_site_published_with_another_manifest_is_rebuilt(town, tmp_path):
    out = tmp_path / "site"
    Publisher(town.parents[1], out).publish()
    day = out / RUN / "events" / "day-0001.json"
    original = day.read_bytes()
    day.write_bytes(original.replace(b'"day":1', b'"day":1 '))
    Publisher(town.parents[1], out).publish()
    assert day.read_bytes() != original  # a settled file of this very bundle is kept

    manifest = out / "data" / "manifest.json"
    document = json.loads(manifest.read_bytes())
    document["files"] = [kind for kind in document["files"] if kind["kind"] != "traits"]
    manifest.write_text(json.dumps(document))
    Publisher(town.parents[1], out).publish()
    assert day.read_bytes() == original


@pytest.mark.parametrize("run", sorted(OLD_MEASURES))
def test_the_measures_of_the_first_town_are_unchanged(run):
    root = PROJECT / run
    if not root.is_dir():
        pytest.skip(f"{run} is not on this machine")
    found = read_run(root)
    document = bundle.measures(measure(found), run_usage(found))
    for table, later in LATER_FIELDS.items():
        for row in document[table]:
            for counts in (row["decisions"], row.get("rejected", {})):
                assert all(counts.pop(kind) == 0 for kind in LATER_KINDS if kind in counts)
            assert all(row.pop(name) == value for name, value in later.items())
    assert hashlib.sha256(encode(document)).hexdigest()[:16] == OLD_MEASURES[run]
