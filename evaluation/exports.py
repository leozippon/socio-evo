"""What an export of a run's residents records beside them, which is where the evaluations take
the residents' model from and what their results name as the resident evaluated.

An export (`experiments.export`) is a directory with one agent directory per resident, as it
stood at a day's checkpoint, and `export.json` beside them: the run and the day, the commit of
each resident's tag of that day, each resident's occupation, and the run's frozen `llm` and
`runtime` sections, the residents' model and the runtime's settings as the run used them, all
from the run's frozen configuration. An evaluation of an exported resident answers through that
model with those settings, never through a configuration of its own, so that it measures the
resident the run made, and records the resident's commit with its results.

    python -m evaluation.exports EXPORT_DIR

prints each resident of the export with its occupation, one a line (`Mei team-leader`), which is
how `ops/evaluate.sh` chooses whom to give the capability tasks.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from agent.runtime import RuntimeConfig
from infrastructure.config import StrictModel
from infrastructure.llm import LLMConfig

MANIFEST = "export.json"


class Export(StrictModel):
    """The manifest of an export: the run directory, the day, each resident's commit and
    occupation by name, and the run's model and runtime."""

    run: str
    day: int
    commits: dict[str, str]
    occupations: dict[str, str]
    llm: LLMConfig
    runtime: RuntimeConfig

    @classmethod
    def of(cls, resident: Path) -> Export:
        """The manifest of the export that holds the agent directory `resident`;
        FileNotFoundError when it is in none, ValueError when the manifest does not list it."""
        path = resident.resolve().parent / MANIFEST
        if not path.is_file():
            raise FileNotFoundError(f"{resident} is in no export: there is no {path}")
        export = cls.read(path)
        if resident.resolve().name not in export.commits:
            raise ValueError(f"{path} lists no resident {resident.resolve().name}")
        return export

    @classmethod
    def read(cls, path: Path) -> Export:
        """The manifest written at `path`."""
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def commit(self, resident: Path) -> str:
        """The commit the agent directory `resident` of this export was exported from."""
        return self.commits[resident.resolve().name]

    def occupation(self, resident: Path) -> str:
        """The occupation of the resident of the agent directory `resident` of this export."""
        return self.occupations[resident.resolve().name]


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.exports",
        description="Print each resident of an export with its occupation, one a line.",
    )
    parser.add_argument("export", type=Path, help="the export directory")
    args = parser.parse_args(argv)
    try:
        export = Export.read(args.export / MANIFEST)
    except (FileNotFoundError, ValueError) as error:
        parser.error(str(error))
    for name in export.commits:
        print(name, export.occupations[name])


if __name__ == "__main__":
    main()
