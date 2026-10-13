"""Publish runs as a static site: the viewer, and a bundle of JSON documents under `data/`.

    python -m frontend.publish --runs-root runs --out SITE [--study STUDY ...]
                               [--watch SECONDS]

The site is self-contained and every URL in it is relative, so any static web server can
serve it under any base path; nothing on the server computes anything. `frontend/README.md`
is the contract of the bundle.

Publishing is deterministic and incremental. A file is rewritten only when its bytes change,
the files of settled days are built once and then kept, and every write replaces a file
atomically. Every document is written before the documents that refer to it, and a reference
carries the hash of the content it refers to, so a reader never meets a torn file or a
reference to a file not yet written. Files no longer referred to are removed last. Publishing
reads run directories and never writes into one. `--watch` publishes again every SECONDS,
skipping runs whose files have not changed, until interrupted. Each `--study`, a study file of
`experiments.study`, adds the comparison of its arms over the runs of the study found under
the runs root, and of its dry runs.
"""

import argparse
import fcntl
import hashlib
import json
import os
import re
import time
import traceback
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote

from analysis import (
    Measures,
    RunData,
    Score,
    Traits,
    evaluation_usage,
    measure,
    read_run,
    recorded_with_parts,
    results,
    run_usage,
    scores,
    traits,
)
from analysis.study import Measured, Study, document, read_study, table
from frontend import bundle
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory

FORMAT = 3
"""The version of the bundle format, which a viewer checks before it reads anything. Bump it
whenever a document changes so that a viewer of the previous format would misread it: a field
removed or renamed, or its type or meaning changed. A field or a kind of file added keeps it,
since a viewer ignores what it does not know. Settled files are kept only from a site whose
manifest is exactly the one this publisher writes, so a new kind of file rebuilds them; a
field added to a settled document (a world, an event day, an agent's day) without a new kind
must bump the format, or sites published before would keep the files without it."""
KINDS = {
    "manifest": "manifest.json",
    "index": "index.json",
    "run": "runs/{experiment}/{run}/run.json",
    "world": "runs/{experiment}/{run}/world.json",
    "measures": "runs/{experiment}/{run}/measures.json",
    "evaluation": "runs/{experiment}/{run}/evaluation.json",
    "result": "runs/{experiment}/{run}/evaluation/{label}/{agent}.json",
    "events": "runs/{experiment}/{run}/events/day-{day}.json",
    "versions": "runs/{experiment}/{run}/agents/{agent}/versions.json",
    "agent_day": "runs/{experiment}/{run}/agents/{agent}/day-{day}.json",
    "traits": "runs/{experiment}/{run}/traits.json",
    "study": "studies/{study}.json",
}
"""Every kind of file under `data/`, by the path pattern of its files."""
MANIFEST = {"format": FORMAT, "files": [{"kind": k, "path": p} for k, p in KINDS.items()]}
STATIC = Path(__file__).parent / "static"
_EXPERIMENT = re.compile(r"[\w.-]+")
_SEED = re.compile(r"seed-\d+")


def encode(document: Any) -> bytes:
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def ref(path: str, digest: str, settled: bool) -> str:
    """The reference to the file at `path`, relative to the referring document. `?v=` marks a
    settled file, whose content never changes; `?r=` a file that may change, whose reference
    changes with it."""
    return f"{quote(path)}?{'v' if settled else 'r'}={digest}"


class Site:
    """A published site being updated. It writes each file atomically and only if its bytes
    changed, records every file this publish keeps, and removes the others in `prune`."""

    def __init__(self, root: Path, reuse: bool) -> None:
        self.root = root
        self.reuse = reuse
        """Whether the site already holds a bundle with this manifest, whose settled files
        stay."""
        self.kept: set[str] = set()
        self.written: list[str] = []
        self.removed: list[str] = []

    def put(self, path: str, document: Any) -> str:
        """Write `document` as JSON to `path`, relative to the site; returns its hash."""
        return self.write(path, encode(document))

    def write(self, path: str, data: bytes) -> str:
        self.kept.add(path)
        target = self.root / path
        if not target.is_file() or target.read_bytes() != data:
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = target.with_name(f".{target.name}.tmp")
            staging.write_bytes(data)
            os.replace(staging, target)
            self.written.append(path)
        return _digest(data)

    def keep(self, path: str) -> str:
        """Keep the existing file at `path` as it is; returns its hash."""
        self.kept.add(path)
        return _digest((self.root / path).read_bytes())

    def prune(self) -> None:
        """Remove every file not kept by this publish, then the directories left empty."""
        for path in sorted(self.root.rglob("*"), reverse=True):
            if path.is_dir():
                if not any(path.iterdir()):
                    path.rmdir()
            elif (relative := path.relative_to(self.root).as_posix()) not in self.kept:
                path.unlink()
                self.removed.append(relative)


@dataclass(frozen=True)
class Analysed:
    """A published run as the comparison of a study reads it; `traits` is None for a run
    recorded before tasks had parts."""

    run: RunData
    traits: Traits | None
    measures: Measures
    scores: list[Score]


@dataclass(frozen=True)
class _Published:
    fingerprint: tuple[tuple[str, int, int], ...]
    entry: dict[str, Any]
    paths: frozenset[str]
    analysed: Analysed


class Publisher:
    """Publishes the runs under `runs_root` into the site directory `out`, again and again,
    with the comparison of the arms of each study file in `studies`. Between publishes it
    remembers each run's files, so a run whose files have not changed since is not read
    again."""

    def __init__(self, runs_root: Path, out: Path, studies: Sequence[Path] = ()) -> None:
        self.runs_root = runs_root.resolve()
        self.out = out.resolve()
        if not self.runs_root.is_dir():
            raise FileNotFoundError(f"runs root {runs_root} is not a directory")
        if self.out.is_relative_to(self.runs_root):
            raise ValueError(f"{out} is inside the runs root; publishing never writes there")
        self.studies = [read_study(path) for path in studies]
        self._published: dict[Path, _Published] = {}

    def publish(self) -> Site:
        """Publish every run once; returns the site with what was written and removed.

        Raises FileExistsError if `out` is neither empty nor a published site, and
        RuntimeError while another publish into it is running.
        """
        self.out.mkdir(parents=True, exist_ok=True)
        manifest = self.out / "data" / "manifest.json"
        if any(self.out.iterdir()) and not manifest.is_file():
            raise FileExistsError(f"{self.out} is neither empty nor a published site")
        with _locked(self.out):
            reuse = manifest.is_file() and json.loads(manifest.read_bytes()) == MANIFEST
            if not reuse:
                self._published.clear()
            site = Site(self.out, reuse)
            published = {root: self._run(site, root) for root in _runs(self.runs_root)}
            analysed = {
                (root.parent.name, root.name): found.analysed for root, found in published.items()
            }
            studies = [
                entry
                for study in self.studies
                for dry_run in (False, True)
                if (entry := publish_study(site, study, dry_run, analysed))
            ]
            entries = [found.entry for found in published.values()]
            site.put("data/index.json", {"format": FORMAT, "runs": entries, "studies": studies})
            site.put("data/manifest.json", MANIFEST)
            for path in sorted(STATIC.rglob("*")):
                if path.is_file():
                    site.write(path.relative_to(STATIC).as_posix(), path.read_bytes())
            site.prune()
        return site

    def _run(self, site: Site, root: Path) -> _Published:
        fingerprint = _fingerprint(RunDirectory(root))
        last = self._published.get(root)
        if (
            last is not None
            and last.fingerprint == fingerprint
            and all((site.root / path).is_file() for path in last.paths)
        ):
            site.kept |= last.paths
            return last
        before = set(site.kept)
        try:
            entry, analysed = publish_run(site, root)
        except Exception as error:
            error.add_note(f"while publishing {root}")
            raise
        published = _Published(fingerprint, entry, frozenset(site.kept - before), analysed)
        self._published[root] = published
        return published


def publish_run(site: Site, root: Path) -> tuple[dict[str, Any], Analysed]:
    """Write every file of the run at `root` into `site`; returns its entry in the index and
    the run as the comparison of a study reads it."""
    run = read_run(root)
    experiment, name = root.parent.name, root.name
    base = f"data/runs/{experiment}/{name}"
    manifest = run.manifest.model_dump(mode="json")
    previous = site.root / base / "run.json"
    final = -1
    """The files of the days up to this one were settled when they were written, so they
    stay: the days the last publish of this same run found settled."""
    if site.reuse and previous.is_file():
        last = json.loads(previous.read_bytes())
        if last["started_at"] == manifest["started_at"]:
            final = last["settled_day"]

    def put(path: str, build: Callable[[], Any], day: int | None = None) -> str:
        """Write the document `build` returns to `path`, relative to the run, unless it is
        the file of a `day` that was already settled and it is there; returns its hash."""
        target = f"{base}/{path}"
        if day is not None and day <= final and (site.root / target).is_file():
            return site.keep(target)
        return site.put(target, build())

    event_days = []
    for day, events in bundle.event_days(run).items():
        settled = day <= run.settled_day
        digest = put(f"events/day-{day:04d}.json", partial(dict, day=day, events=events), day)
        event_days.append(
            {
                "day": day,
                "url": ref(f"events/day-{day:04d}.json", digest, settled),
                "events": len(events),
                "first_seq": events[0]["seq"],
                "last_seq": events[-1]["seq"],
                "settled": settled,
            }
        )

    agents = []
    for agent in run.agents:
        versions = bundle.agent_versions(run, agent)
        repository = Repository(run.directory.agent_dir(agent))
        by_day: dict[int, list[bundle.AgentVersion]] = {}
        for found in versions:
            by_day.setdefault(found.day, []).append(found)
        urls = {}
        for day, found in by_day.items():
            path = f"day-{day:04d}.json"
            build = partial(bundle.agent_day, repository, agent, day, found)
            digest = put(f"agents/{agent}/{path}", build, day)
            urls[day] = ref(path, digest, day <= run.settled_day)
        build = partial(bundle.versions_index, agent, versions, urls)
        digest = put(f"agents/{agent}/versions.json", build)
        agents.append(
            {
                "agent": agent,
                "url": ref(f"agents/{agent}/versions.json", digest, False),
                "versions": len(versions),
            }
        )

    found = results(run.directory)
    urls = {}
    for key, result in found.items():
        digest = put(f"evaluation/{key}.json", partial(result.model_dump, mode="json"))
        urls[key] = ref(f"evaluation/{key}.json", digest, False)
    rows = scores(found)
    evaluation = bundle.evaluation(rows, urls, found, evaluation_usage(run))
    measured, usage = measure(run), run_usage(run)
    character = traits(run) if recorded_with_parts(run) else None
    world = bundle.world(run)
    digests = {
        "world": put("world.json", lambda: world, 0),
        "measures": put("measures.json", partial(bundle.measures, measured, usage)),
        "evaluation": put("evaluation.json", lambda: evaluation),
    }
    if character is not None:
        digests["traits"] = put("traits.json", partial(bundle.traits, run, character, measured))
    document = {
        "experiment": experiment,
        "run": name,
        **manifest,
        "days": world["days"],
        "settled_day": run.settled_day,
        "last_day": run.last_day,
        "last_time": run.events[-1].time if run.events else None,
        "events": len(run.events),
        "world": ref("world.json", digests["world"], True),
        "measures": ref("measures.json", digests["measures"], False),
        "evaluation": ref("evaluation.json", digests["evaluation"], False),
        "traits": ref("traits.json", digests["traits"], False) if character else None,
        "event_days": event_days,
        "agents": agents,
    }
    digest = put("run.json", lambda: document)
    entry = {
        "experiment": experiment,
        "run": name,
        "url": ref(f"runs/{experiment}/{name}/run.json", digest, False),
        "seed": manifest["seed"],
        "status": manifest["status"],
        "started_at": manifest["started_at"],
        "ended_at": manifest["ended_at"],
        "days": world["days"],
        "settled_day": run.settled_day,
        "last_day": run.last_day,
        "agents": run.agents,
        "model": world["model"]["name"],
        "dry_run": world["model"]["backend"] == "scripted",
        "headline": bundle.headline(measured.society, usage, found),
    }
    return entry, Analysed(run, character, measured, rows)


def publish_study(
    site: Site, study: Study, dry_run: bool, analysed: dict[tuple[str, str], Analysed]
) -> dict[str, Any] | None:
    """Write the comparison of the arms of `study`, or of its dry runs, over the runs of it in
    `analysed` (by experiment and run name) into `site`; returns its entry in the index, None
    if none of its runs is there. Raises ValueError for a run of it recorded before tasks had
    parts."""
    experiments = {arm: study.experiment(arm, dry_run) for arm in study.arms}
    runs = []
    for arm, experiment in experiments.items():
        for (name, _), found in sorted(analysed.items()):
            if name != experiment:
                continue
            if found.traits is None:
                raise ValueError(f"{found.run.directory.root} was recorded before tasks had parts")
            runs.append(Measured(arm, found.run, found.traits, found.measures, found.scores))
    if not runs:
        return None
    path = f"studies/{study.name}{'-dry-run' if dry_run else ''}.json"
    digest = site.put(f"data/{path}", document(table(study, dry_run, runs)))
    return {
        "study": study.name,
        "dry_run": dry_run,
        "url": ref(path, digest, False),
        "arms": [{"arm": arm, "experiment": name} for arm, name in experiments.items()],
    }


def _runs(runs_root: Path) -> list[Path]:
    """Every run directory under `runs_root`: `<experiment>/seed-<NNNN>` with a manifest."""
    return [
        manifest.parent
        for manifest in sorted(runs_root.glob("*/seed-*/manifest.json"))
        if _EXPERIMENT.fullmatch(manifest.parent.parent.name)
        and _SEED.fullmatch(manifest.parent.name)
    ]


def _fingerprint(run: RunDirectory) -> tuple[tuple[str, int, int], ...]:
    """Size and modification time of every file of `run` publishing reads, but the agent
    repositories: every commit to them is followed by a write to the event log, a checkpoint
    or the manifest."""
    paths = [
        run.manifest_path,
        run.config_path,
        run.events_path,
        run.llm_calls_path,
        *sorted(run.checkpoints_dir.glob("day-*.json")),
        *sorted(run.evaluation_dir.rglob("*.json*")),
    ]
    stats = []
    for path in paths:
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        stats.append((str(path), stat.st_size, stat.st_mtime_ns))
    return tuple(stats)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


@contextmanager
def _locked(directory: Path) -> Iterator[None]:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f"another publish into {directory} is running") from None
        yield
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m frontend.publish",
        description="Publish runs as a static site: the viewer and its data bundle.",
    )
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--out", type=Path, required=True, help="the site directory")
    parser.add_argument(
        "--study", type=Path, action="append", default=[], help="a study file to compare"
    )
    parser.add_argument(
        "--watch", type=float, metavar="SECONDS", help="publish again every SECONDS"
    )
    args = parser.parse_args(argv)
    publisher = Publisher(args.runs_root, args.out, args.study)
    try:
        while True:
            try:
                site = publisher.publish()
                written, removed = len(site.written), len(site.removed)
                print(f"{args.out}: {written} written, {removed} removed", flush=True)
            except Exception:
                if args.watch is None:
                    raise
                traceback.print_exc()
            if args.watch is None:
                return
            time.sleep(args.watch)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
