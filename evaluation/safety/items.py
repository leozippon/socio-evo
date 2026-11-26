"""The items of the three safety instruments, from public datasets at pinned revisions.

- Harmful compliance: the 100 harmful behaviours of JailbreakBench (JBB-Behaviors, Chao et al.
  2024, MIT licence), each asked plainly, as its `Goal`.
- Jailbreak success: the same behaviours, each wrapped in every one of a fixed set of published
  jailbreak templates (`jailbreaks.json`, beside this module, which names their source, commit
  and licence): five templates of distinct families, 500 items.
- Harmless compliance: the 100 benign behaviours of JBB-Behaviors, written to mirror the harmful
  ones topic by topic, and the 250 safe prompts of XSTest (Röttger et al. 2024, CC BY 4.0), which
  look dangerous and are not; 350 items.

The files are fetched once through the Hugging Face endpoint the environment names
(`HF_ENDPOINT`) into CACHE, outside the repository. An item's `behaviour` is the request in plain
words, which is what the judge is told the user asked; its `prompt` is what the subject is asked,
the behaviour itself or, for a jailbreak, the behaviour inside the template. The id names the
dataset row, so that the same behaviour can be followed across instruments, and `items_hash`
identifies the exact set of prompts asked, so that two results can be shown to be of the same
items.
"""

import csv
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from huggingface_hub import hf_hub_download

from infrastructure.config import StrictModel

Instrument = Literal["harmful", "jailbreak", "harmless"]
INSTRUMENTS: tuple[Instrument, ...] = ("harmful", "jailbreak", "harmless")

CACHE = Path("~/.cache/socio-evo/safety").expanduser()
"""Where the dataset files are kept, one directory per repository and revision."""


class Source(StrictModel):
    """One file of a Hugging Face dataset repository at a pinned revision."""

    repo: str
    revision: str
    filename: str

    def path(self, cache: Path = CACHE) -> Path:
        """The file in `cache`, downloaded first if it is not there."""
        directory = cache / self.repo.replace("/", "--") / self.revision
        path = directory / self.filename
        if not path.exists():
            hf_hub_download(
                self.repo,
                self.filename,
                repo_type="dataset",
                revision=self.revision,
                local_dir=directory,
            )
        return path


JBB = "JailbreakBench/JBB-Behaviors"
JBB_REVISION = "886acc352a31533ffbcf4ef22c744658688086fc"
JBB_HARMFUL = Source(repo=JBB, revision=JBB_REVISION, filename="data/harmful-behaviors.csv")
JBB_BENIGN = Source(repo=JBB, revision=JBB_REVISION, filename="data/benign-behaviors.csv")
XSTEST = Source(
    repo="Paul/XSTest",
    revision="f600c994b256f12867dfa5b3eb3d545a3e62f8b5",
    filename="xstest_prompts.csv",
)
"""XSTest as its authors published it: 250 prompts labelled `safe` and 200 `unsafe` contrasts,
of which only the safe ones are asked."""
SOURCES = (JBB_HARMFUL, JBB_BENIGN, XSTEST)

JAILBREAKS = Path(__file__).with_name("jailbreaks.json")
PLACEHOLDER = "{forbidden_prompt}"
"""Where a template takes the behaviour, as StrongREJECT writes it."""


class Item(StrictModel):
    """One prompt of an instrument. `template` names the jailbreak it is wrapped in, None
    outside the jailbreak instrument; `category` is the dataset's (JBB's category, XSTest's
    type)."""

    instrument: Instrument
    id: str
    template: str | None = None
    category: str
    behaviour: str
    prompt: str

    @property
    def key(self) -> str:
        """What tells this item from every other of its set."""
        return f"{self.instrument}/{self.id}" + (f"/{self.template}" if self.template else "")

    @property
    def prompt_hash(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()


def items_hash(items: Sequence[Item]) -> str:
    """The hash of the set of `items`: of every key with its prompt's hash, in key order."""
    lines = sorted(f"{item.key} {item.prompt_hash}" for item in items)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def templates(path: Path = JAILBREAKS) -> dict[str, str]:
    """Each jailbreak template's text by name; ValueError for a file of another placeholder or a
    template that does not hold it exactly once."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document["placeholder"] != PLACEHOLDER:
        raise ValueError(f"{path}: the placeholder is not {PLACEHOLDER}")
    found = {name: entry["text"] for name, entry in document["templates"].items()}
    if wrong := [name for name, text in found.items() if text.count(PLACEHOLDER) != 1]:
        raise ValueError(f"{path}: the templates {wrong} do not hold {PLACEHOLDER} exactly once")
    return found


def wrap(template: str, behaviour: str) -> str:
    """`behaviour` put in the place of the placeholder of `template`, as StrongREJECT does."""
    return template.replace(PLACEHOLDER, behaviour)


def _rows(source: Source, cache: Path) -> list[dict[str, str]]:
    with source.path(cache).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def load_items(cache: Path = CACHE, jailbreaks: Path = JAILBREAKS) -> list[Item]:
    """Every item of the three instruments, in instrument order: the harmful behaviours plainly,
    then each wrapped in each template, then the benign behaviours and XSTest's safe prompts."""
    harmful = [
        Item(
            instrument="harmful",
            id=f"jbb-harmful-{row['Index']}",
            category=row["Category"],
            behaviour=row["Goal"],
            prompt=row["Goal"],
        )
        for row in _rows(JBB_HARMFUL, cache)
    ]
    wrapped = [
        item.model_copy(
            update={"instrument": "jailbreak", "template": name, "prompt": wrap(text, item.prompt)}
        )
        for name, text in templates(jailbreaks).items()
        for item in harmful
    ]
    benign = [
        Item(
            instrument="harmless",
            id=f"jbb-benign-{row['Index']}",
            category=row["Category"],
            behaviour=row["Goal"],
            prompt=row["Goal"],
        )
        for row in _rows(JBB_BENIGN, cache)
    ]
    safe = [
        Item(
            instrument="harmless",
            id=f"xstest-{row['id']}",
            category=row["type"],
            behaviour=row["prompt"],
            prompt=row["prompt"],
        )
        for row in _rows(XSTEST, cache)
        if row["label"] == "safe"
    ]
    items = [*harmful, *wrapped, *benign, *safe]
    if len({item.key for item in items}) != len(items):
        raise ValueError("two items share a key")
    return items
