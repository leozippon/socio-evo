"""The agent directory: one resident's files, and the system prompt assembled from them."""

from __future__ import annotations

from pathlib import Path

from agent import texts

BACKGROUND = "background.md"
MEMORY = "memory"
SKILLS = "skills"
JOURNAL = "memory/journal"
SESSION = "session.jsonl"
TRACE = "trace.jsonl"
AREAS = (MEMORY, SKILLS)
"""The folders a resident keeps files in; with `BACKGROUND`, all it can reach."""


class AgentDirectory:
    """The directory of one resident:

    background.md, who the resident is; memory/ (town.md, people.md, work.md and journal/),
    what it keeps; skills/, one file per method, whose first line describes it; session.jsonl
    and trace.jsonl, which the runtime writes. The resident reaches background.md, memory/ and
    skills/ only, and skills/ only for reading when `skills_writable` is False (group D).

    Folders that git does not keep when empty (memory/journal/, skills/) may be missing, as in
    an export of a tagged day; they are created when a file is written into them.
    """

    def __init__(self, root: Path, *, skills_writable: bool = True) -> None:
        if not (root / BACKGROUND).is_file():
            raise FileNotFoundError(f"{root} is no agent directory: it has no {BACKGROUND}")
        self.root = root
        self.skills_writable = skills_writable

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        background: str,
        town: str,
        people: str = "",
        work: str = "",
        skills_writable: bool = True,
    ) -> AgentDirectory:
        """Create the directory at `root`, which must not exist, from the resident's background
        and the first contents of its memory files (`town` is usually the town's rules)."""
        root.mkdir(parents=True)
        (root / MEMORY).mkdir()
        (root / JOURNAL).mkdir()
        (root / SKILLS).mkdir()
        for name, text in (
            (BACKGROUND, background),
            ("memory/town.md", town),
            ("memory/people.md", people),
            ("memory/work.md", work),
        ):
            (root / name).write_text(text, encoding="utf-8")
        return cls(root, skills_writable=skills_writable)

    @property
    def session_path(self) -> Path:
        return self.root / SESSION

    @property
    def trace_path(self) -> Path:
        return self.root / TRACE

    def files(self, folder: str = "") -> list[str]:
        """The resident's files under `folder` (all of them for ""), as sorted relative paths;
        names beginning with a dot are left out."""
        roots = [BACKGROUND, *AREAS] if folder == "" else [folder]
        found = []
        for name in roots:
            path = self.root / name
            if path.is_file():
                found.append(name)
            elif path.is_dir():
                found += [
                    file.relative_to(self.root).as_posix()
                    for file in path.rglob("*")
                    if file.is_file() and not file.name.startswith(".")
                ]
        return sorted(found)

    def index(self) -> str:
        """One line per file: its path, and what it is for where that is known; for a skill,
        the first line of the file."""
        lines = []
        for name in self.files():
            description = texts.KNOWN_FILES.get(name)
            if name.startswith(f"{SKILLS}/"):
                description = _first_line(self.root / name)
            lines.append(f"- {name}: {description}" if description else f"- {name}")
        return "\n".join(lines)

    def system_prompt(self, rules: str) -> str:
        """The resident's background, the standing `rules`, how tools work and the index of
        its files; the same text, byte for byte, while those are unchanged."""
        files = texts.FILES
        if not self.skills_writable:
            files += " " + texts.SKILLS_READ_ONLY
        background = (self.root / BACKGROUND).read_text(encoding="utf-8").strip()
        parts = (background, rules.strip(), texts.GUIDE, files, self.index())
        return "\n\n".join(part for part in parts if part) + "\n"


def _first_line(path: Path) -> str:
    """The first line of the file at `path`, without heading marks."""
    with path.open(encoding="utf-8", errors="replace") as file:
        return file.readline().strip().lstrip("#").strip()
