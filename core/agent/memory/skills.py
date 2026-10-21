"""Skills: procedural notes the agent writes for itself, one markdown file each, named by its
title."""

import hashlib
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml
from pydantic import Field, model_validator

from infrastructure.config import StrictModel

SKILL_NAME = r"^[a-z0-9]+(-[a-z0-9]+)*$"
"""A skill name is its file stem: lowercase words joined by hyphens."""
_WORD = re.compile(r"[a-z0-9]+")


def title_of(name: str) -> str:
    """The title of the note `name` written before titles were kept: its words, the first
    capitalised."""
    return name.replace("-", " ").capitalize()


def name_of(title: str) -> str | None:
    """The name of the note titled `title`: its words in lower case joined by hyphens; None
    if it has no letters or digits, or would be longer than a name may be."""
    name = "-".join(_WORD.findall(title.lower()))
    return name if 0 < len(name) <= 64 else None


_FILE = re.compile(r"---\n(.*?)\n---\n(.*)", re.DOTALL)


class Skill(StrictModel):
    """A procedure note: its `title` as its author wrote it, its `name`, the file stem, which
    the title gives (`name_of`), `description`, the one line shown in the skill index, and
    its `body`."""

    name: str = Field(pattern=SKILL_NAME, max_length=64)
    title: str
    description: str
    body: str

    @property
    def version(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]

    @model_validator(mode="after")
    def _named_by_its_title(self) -> "Skill":
        if name_of(self.title) != self.name:
            raise ValueError(f"the note titled {self.title!r} cannot be named {self.name!r}")
        return self


class SkillLibrary:
    """`memory/skills/<name>.md`: YAML front matter holding the title and the description,
    then the body; a note written before titles were kept has no title in it, and is titled
    by its name. The directory may be absent until the first note."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def read(self) -> list[Skill]:
        """Every skill, ordered by name."""
        return [_parse(self._path(path.stem)) for path in sorted(self.directory.glob("*.md"))]

    def write(self, skill: Skill) -> None:
        """Create the note, or replace the note of the same name."""
        front = yaml.safe_dump(
            {"title": skill.title, "description": skill.description},
            allow_unicode=True,
            sort_keys=False,
        )
        path = self._path(skill.name)
        self.directory.mkdir(exist_ok=True)
        # Never expose a half-written page to the next decision or nightly review.
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, delete=False) as f:
            temporary = Path(f.name)
            try:
                f.write(f"---\n{front}---\n\n{skill.body.strip()}\n")
                f.close()
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

    def remove(self, name: str) -> None:
        """Delete the note `name`; raises FileNotFoundError if there is none."""
        self._path(name).unlink()

    def _path(self, name: str) -> Path:
        if not isinstance(name, str) or not re.fullmatch(SKILL_NAME, name) or len(name) > 64:
            raise ValueError("Invalid skill name")
        path = self.directory / f"{name}.md"
        if self.directory.parent.is_symlink() or self.directory.is_symlink() or path.is_symlink():
            raise ValueError("Symlinked skill pages are not accessible")
        return path


def _parse(path: Path) -> Skill:
    match = _FILE.fullmatch(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"{path}: expected YAML front matter between '---' lines")
    front = {"title": title_of(path.stem), **yaml.safe_load(match[1])}
    return Skill.model_validate({"name": path.stem, **front, "body": match[2].strip()})
