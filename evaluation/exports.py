"""What an export of a run's residents records beside them, which is where the evaluations take
the residents' model from and what their results name as the resident evaluated.

An export (`experiments.export`) is a directory with one agent directory per resident, as it
stood at a day's checkpoint, and `export.json` beside them: the run and the day, the commit of
each resident's tag of that day, and the run's frozen `llm` and `runtime` sections, the
residents' model and the runtime's settings as the run used them. An evaluation of an exported
resident answers through that model with those settings, never through a configuration of its
own, so that it measures the resident the run made, and records the resident's commit with its
results.
"""

from __future__ import annotations

from pathlib import Path

from agent.runtime import RuntimeConfig
from infrastructure.config import StrictModel
from infrastructure.llm import LLMConfig

MANIFEST = "export.json"


class Export(StrictModel):
    """The manifest of an export: the run directory, the day, each resident's commit by name,
    and the run's model and runtime."""

    run: str
    day: int
    commits: dict[str, str]
    llm: LLMConfig
    runtime: RuntimeConfig

    @classmethod
    def of(cls, resident: Path) -> Export:
        """The manifest of the export that holds the agent directory `resident`;
        FileNotFoundError when it is in none, ValueError when the manifest does not list it."""
        path = resident.resolve().parent / MANIFEST
        if not path.is_file():
            raise FileNotFoundError(f"{resident} is in no export: there is no {path}")
        export = cls.model_validate_json(path.read_text(encoding="utf-8"))
        if resident.resolve().name not in export.commits:
            raise ValueError(f"{path} lists no resident {resident.resolve().name}")
        return export

    def commit(self, resident: Path) -> str:
        """The commit the agent directory `resident` of this export was exported from."""
        return self.commits[resident.resolve().name]
