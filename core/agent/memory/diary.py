"""The diary: one markdown entry per day, written by the agent at night."""

from pathlib import Path


class Diary:
    """`memory/diary/day-NNNN.md`. The directory may be absent until the first entry."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def write(self, day: int, text: str) -> None:
        self.directory.mkdir(exist_ok=True)
        self._path(day).write_text(text.strip() + "\n", encoding="utf-8")

    def entries(self, after: int = 0) -> list[tuple[int, str]]:
        """`(day, text)` of every entry for a day later than `after`, oldest first."""
        days = sorted(
            int(path.stem.removeprefix("day-")) for path in self.directory.glob("day-*.md")
        )
        return [
            (day, self._path(day).read_text(encoding="utf-8").strip())
            for day in days
            if day > after
        ]

    def _path(self, day: int) -> Path:
        return self.directory / f"day-{day:04d}.md"
