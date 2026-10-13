"""Skills: procedural notes the agent writes for itself, one markdown file each, named by its
title."""

import re
from pathlib import Path

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
        return [_parse(path) for path in sorted(self.directory.glob("*.md"))]

    def write(self, skill: Skill) -> None:
        """Create the note, or replace the note of the same name."""
        front = yaml.safe_dump(
            {"title": skill.title, "description": skill.description},
            allow_unicode=True,
            sort_keys=False,
        )
        self.directory.mkdir(exist_ok=True)
        self._path(skill.name).write_text(
            f"---\n{front}---\n\n{skill.body.strip()}\n", encoding="utf-8"
        )

    def remove(self, name: str) -> None:
        """Delete the note `name`; raises FileNotFoundError if there is none."""
        self._path(name).unlink()

    def _path(self, name: str) -> Path:
        return self.directory / f"{name}.md"


def _parse(path: Path) -> Skill:
    match = _FILE.fullmatch(path.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"{path}: expected YAML front matter between '---' lines")
    front = {"title": title_of(path.stem), **yaml.safe_load(match[1])}
    return Skill.model_validate({"name": path.stem, **front, "body": match[2].strip()})
