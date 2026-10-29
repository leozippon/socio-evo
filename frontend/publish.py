"""Publish runs as a static site: the viewer, and a bundle of JSON documents under `data/`.

    python -m frontend.publish --runs-root runs --out SITE [--results-root results]
                               [--watch SECONDS]

The site is self-contained and every URL in it is relative, so any static web server can serve
it under any base path; nothing on the server computes anything. `frontend/README.md` is the
contract of the bundle.

Publishing is deterministic and incremental. A file is rewritten only when its bytes change,
the files of settled days are built once and then kept, and every write replaces a file
atomically. Every document is written before the documents that refer to it, and a reference
carries the hash of the content it refers to, so a reader never meets a torn file or a
reference to a file not yet written. Files no longer referred to are removed last. Publishing
reads run directories and the results root and never writes into either. A run whose frozen
configuration is missing or cannot be read by the current code, or whose publishing fails, is
skipped and named in the index with the reason in plain words and the error itself, so the
other runs are published all the same. `--watch` publishes again every SECONDS, skipping runs
whose files have not changed, until interrupted.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import quote

from analysis.measures import daily, measure, town_days
from frontend import bundle
from frontend.progress import progress
from frontend.timeline import timeline
from infrastructure.config import ConfigError, load_config
from infrastructure.git import Repository
from infrastructure.storage import RunDirectory, day_tag
from simulation.config import ExperimentConfig
from world.log import lived_days

FORMAT = 11
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
    "comparison": "compare/{set}.json",
    "run": "runs/{run}/run.json",
    "world": "runs/{run}/world.json",
    "timeline": "runs/{run}/timeline.json",
    "progress": "runs/{run}/progress.json",
    "measures": "runs/{run}/measures.json",
    "evaluation": "runs/{run}/evaluation.json",
    "events": "runs/{run}/events/day-{day}.json",
    "versions": "runs/{run}/agents/{agent}/versions.json",
    "agent_day": "runs/{run}/agents/{agent}/day-{day}.json",
    "trace_day": "runs/{run}/agents/{agent}/trace-day-{day}.json",
}
"""Every kind of file under `data/`, by the path pattern of its files."""
MANIFEST = {"format": FORMAT, "files": [{"kind": k, "path": p} for k, p in KINDS.items()]}
STATIC = Path(__file__).parent / "static"


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
        self.skipped: list[dict[str, str]] = []
        """The runs this publish left out, each with the reason in plain words and the error."""

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
class _Published:
    fingerprint: tuple[tuple[str, int, int], ...]
    entry: dict[str, Any]
    paths: frozenset[str]
    analysed: bundle.Analysed


class Publisher:
    """Publishes the runs under `runs_root`, with their evaluation results under
    `results_root`, into the site directory `out`, again and again. Between publishes it
    remembers each run's files, so a run whose files have not changed since is not read
    again, and each comparison's runs, so a comparison of unchanged runs is not computed
    again."""

    def __init__(self, runs_root: Path, out: Path, results_root: Path = Path("results")) -> None:
        self.runs_root = runs_root.resolve()
        self.out = out.resolve()
        self.results_root = results_root.resolve()
        if not self.runs_root.is_dir():
            raise FileNotFoundError(f"runs root {runs_root} is not a directory")
        if self.out.is_relative_to(self.runs_root):
            raise ValueError(f"{out} is inside the runs root; publishing never writes there")
        if self.out.is_relative_to(self.results_root):
            raise ValueError(f"{out} is inside the results root; publishing never writes there")
        self._published: dict[str, _Published] = {}
        self._compared: dict[str, tuple[tuple[Any, ...], str]] = {}

    def publish(self) -> Site:
        """Publish every run once; returns the site with what was written, removed and skipped.

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
                self._compared.clear()
            site = Site(self.out, reuse)
            published: dict[str, _Published] = {}
            for name, root in _runs(self.runs_root).items():
                found = self._run(site, name, root)
                if found is not None:
                    published[name] = found
            comparisons = self._comparisons(site, published)
            entries = [found.entry for found in published.values()]
            index = {
                "format": FORMAT,
                "runs": entries,
                "skipped": site.skipped,
                "comparisons": comparisons,
            }
            site.put("data/index.json", index)
            site.put("data/manifest.json", MANIFEST)
            for path in sorted(STATIC.rglob("*")):
                if path.is_file():
                    site.write(path.relative_to(STATIC).as_posix(), path.read_bytes())
            site.prune()
        return site

    def _run(self, site: Site, name: str, root: Path) -> _Published | None:
        """Publish one run, or skip it, saying why in `site.skipped`: its frozen configuration
        is missing or cannot be read by the current code, or publishing it failed, in which case
        the files written for it so far are left for `prune` and the error is printed."""
        try:
            config = load_config(root / "config.yaml", ExperimentConfig)
        except (ConfigError, OSError) as error:
            site.skipped.append(_skipped(name, root, UNREADABLE_CONFIG, error))
            return None
        fingerprint = _fingerprint(RunDirectory(root), self.results_root, name)
        last = self._published.get(name)
        if (
            last is not None
            and last.fingerprint == fingerprint
            and all((site.root / path).is_file() for path in last.paths)
        ):
            site.kept |= last.paths
            return last
        before = set(site.kept)
        try:
            entry, analysed = publish_run(site, name, root, config, self.results_root)
        except Exception as error:
            print(f"while publishing {root}:", file=sys.stderr)
            traceback.print_exc()
            site.kept = before
            self._published.pop(name, None)
            site.skipped.append(_skipped(name, root, PUBLISHING_FAILED, error))
            return None
        published = _Published(fingerprint, entry, frozenset(site.kept - before), analysed)
        self._published[name] = published
        return published

    def _comparisons(self, site: Site, published: dict[str, _Published]) -> list[dict[str, Any]]:
        """The comparison of the runs of each directory: the runs directly under the runs root,
        named after it, and those under each of its subdirectories, named after that."""
        families: dict[str, list[str]] = {}
        for name in published:
            parent, _, _ = name.rpartition("/")
            families.setdefault(parent or self.runs_root.name, []).append(name)
        entries = []
        for family, names in sorted(families.items()):
            if len(names) < 2:
                continue
            path = f"compare/{family}.json"
            key = tuple((name, published[name].fingerprint) for name in names)
            cached = self._compared.get(family)
            if cached is not None and cached[0] == key and (site.root / "data" / path).is_file():
                digest = site.keep(f"data/{path}")
            else:
                runs = [published[name].analysed for name in names]
                digest = site.put(f"data/{path}", bundle.compared(family, runs))
                self._compared[family] = (key, digest)
            entries.append({"name": family, "url": ref(path, digest, False), "runs": names})
        return entries


def publish_run(
    site: Site, name: str, root: Path, config: ExperimentConfig, results_root: Path
) -> tuple[dict[str, Any], bundle.Analysed]:
    """Write every file of the run `name` at `root` into `site`; returns its entry in the index
    and the run as the comparison of runs reads it."""
    run = RunDirectory(root)
    manifest = run.read_manifest().model_dump(mode="json", exclude={"pid"})  # pid: local only
    base = f"data/runs/{name}"
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

    data = timeline(root)
    states = bundle.saved(run, data)
    things, holders = bundle.holdings(states, config.town, data)
    lanes = [{**lane, "things": things[lane["name"]]} for lane in data["residents"]]
    data = {**data, "residents": lanes, "holders": holders}
    days = lived_days(run.world_log_path)
    lived = days.lived()
    closed = set(days.closed)
    settled_day = max(closed, default=0)
    last_day = lived[-1].number if lived else 0

    event_days = []
    for found in lived:
        day = found.number
        path = f"events/day-{day_tag(day)[4:]}.json"
        published = [bundle.published_entry(entry) for entry in found.entries]
        digest = put(path, partial(dict, day=day, entries=published), day)
        event_days.append(
            {
                "day": day,
                "url": ref(path, digest, day in closed),
                "entries": len(found.entries),
                "first_seq": found.entries[0]["seq"],
                "last_seq": found.entries[-1]["seq"],
                "settled": day in closed,
            }
        )

    residents = []
    spans = [*days.closed.values(), days.open]
    for resident in config.town.residents:
        agent_dir = resident.agent_dir or run.agent_dir(resident.name)
        repository = Repository(agent_dir)
        versions = bundle.agent_versions(repository, config.town.start_date)
        by_day: dict[int, list[bundle.Version]] = {}
        for found in versions:
            by_day.setdefault(found.day, []).append(found)
        urls = {}
        for day, found in by_day.items():
            path = f"day-{day_tag(day)[4:]}.json"
            build = partial(bundle.agent_day, repository, resident.name, day, found)
            digest = put(f"agents/{resident.name}/{path}", build, day)
            urls[day] = ref(path, digest, day <= settled_day)
        build = partial(bundle.versions_index, resident.name, versions, urls)
        digest = put(f"agents/{resident.name}/versions.json", build)
        traces = []
        for day, doc in sorted(bundle.trace_days(agent_dir, resident.name, spans).items()):
            path = f"trace-day-{day_tag(day)[4:]}.json"
            digest_of_day = put(f"agents/{resident.name}/{path}", lambda doc=doc: doc, day)
            traces.append(
                {
                    "day": day,
                    "url": ref(f"agents/{resident.name}/{path}", digest_of_day, day in closed),
                    "records": len(doc["records"]),
                }
            )
        residents.append(
            {
                "name": resident.name,
                "url": ref(f"agents/{resident.name}/versions.json", digest, False),
                "versions": len(versions),
                "trace_days": traces,
            }
        )

    world = bundle.world(config)
    headline = progress(data)
    rows = measure(root) if settled_day else []
    # The world logs a day's checkpoint before the run writes its file; while the latest is
    # being saved, the town's days, which read the treasury from the files, wait for it.
    saving = settled_day and not run.checkpoint_path(settled_day).is_file()
    town = town_days(root) if settled_day and not saving else []
    measures = {
        "rows": rows,
        "daily": daily(rows),
        "town": town,
        "graph": bundle.graph(data, lived),
    }
    evaluation = bundle.evaluation(results_root, name)
    digests = {
        "world": put("world.json", lambda: world, 0),
        "timeline": put("timeline.json", lambda: data),
        "progress": put("progress.json", lambda: headline),
        "measures": put("measures.json", lambda: measures),
        "evaluation": put("evaluation.json", lambda: evaluation),
    }
    document = {
        "name": name,
        **manifest,
        "days": config.days,
        "settled_day": settled_day,
        "last_day": last_day,
        "last_time": lived[-1].entries[-1]["sim_time"] if lived else None,
        "entries": sum(len(found.entries) for found in lived),
        **{kind: ref(f"{kind}.json", digest, kind == "world") for kind, digest in digests.items()},
        "event_days": event_days,
        "residents": residents,
    }
    digest = put("run.json", lambda: document)
    entry = {
        "name": name,
        "url": ref(f"runs/{name}/run.json", digest, False),
        "status": manifest["status"],
        "started_at": manifest["started_at"],
        "ended_at": manifest["ended_at"],
        "days": config.days,
        "settled_day": settled_day,
        "last_day": last_day,
        "residents": [resident.name for resident in config.town.residents],
        "model": world["model"]["name"],
        "dry_run": world["model"]["backend"] == "scripted",
        "headline": bundle.headline(headline, town),
    }
    return entry, bundle.Analysed(name, rows, evaluation)


UNREADABLE_CONFIG = (
    "Its frozen configuration cannot be read by the version of the code that publishes, so the "
    "run is left out until the two agree; nothing of it is lost."
)
PUBLISHING_FAILED = "Publishing its files failed, so the run is left out until that is repaired."


def _skipped(name: str, root: Path, reason: str, error: BaseException) -> dict[str, str]:
    """A skipped run's entry in the index: the reason in plain words, and the error as the code
    reported it, with the run's directory named by the run so the bundle stays the same bytes
    wherever it is published."""
    detail = f"{type(error).__name__}: {error}".replace(str(root), name)
    return {"name": name, "reason": reason, "detail": detail}


def _runs(runs_root: Path) -> dict[str, Path]:
    """Every run under `runs_root`, by its path relative to the root: a directory holding a
    manifest, directly under the root or one level further down."""
    manifests = [*runs_root.glob("*/manifest.json"), *runs_root.glob("*/*/manifest.json")]
    return {
        manifest.parent.relative_to(runs_root).as_posix(): manifest.parent
        for manifest in sorted(manifests)
    }


def _fingerprint(
    run: RunDirectory, results_root: Path, name: str
) -> tuple[tuple[str, int, int], ...]:
    """Size and modification time of every file publishing reads of a run, but the agent
    repositories: every commit to them is followed by a checkpoint. The results read are the
    JSON documents under the run's results and the shared day 0 beside them."""
    results = results_root / name
    paths = [
        run.manifest_path,
        run.config_path,
        run.world_log_path,
        *sorted(run.checkpoints_dir.glob("day-*.json")),
        *sorted(results.rglob("*.json")),
        *sorted((results.parent / "day-00").rglob("*.json")),
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


def report(out: Path, site: Site) -> str:
    """One line on what a publish did, and one per run it skipped, with the error."""
    lines = [f"{out}: {len(site.written)} written, {len(site.removed)} removed"]
    lines += [f"skipped {found['name']}: {found['detail']}" for found in site.skipped]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m frontend.publish",
        description="Publish runs as a static site: the viewer and its data bundle.",
    )
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--results-root", type=Path, default=Path("results"))
    parser.add_argument("--out", type=Path, required=True, help="the site directory")
    parser.add_argument(
        "--watch", type=float, metavar="SECONDS", help="publish again every SECONDS"
    )
    args = parser.parse_args(argv)
    publisher = Publisher(args.runs_root, args.out, args.results_root)
    try:
        while True:
            try:
                print(report(args.out, publisher.publish()), flush=True)
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
