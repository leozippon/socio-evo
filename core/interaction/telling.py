"""How a text names people for whoever reads it.

An event is told once for everyone and again for each witness it names, from the same parts:
a `Telling` is the text as a function of the `Witness` it is told to, which names that witness
`you` and everyone else by name. Told to `Witness()`, nobody in particular, it names everyone:
that is the event's text, what a bystander reads.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

YOU = "you"
YOUR = "your"


def listed(names: Sequence[str]) -> str:
    """`Ana`, `Ana and Ben`, `Ana, Ben and Cai`."""
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)


def capital(text: str) -> str:
    """`text` with its first letter upper-case, for a sentence that starts with it."""
    return text[:1].upper() + text[1:]


@dataclass(frozen=True)
class Witness:
    """The one a text is told to, `name`, or nobody in particular (None)."""

    name: str | None = None

    def __call__(self, person: str) -> str:
        """`person` by name, or `you` if it is the witness."""
        return YOU if person == self.name else person

    def whose(self, person: str) -> str:
        """`person's`, or `your` if it is the witness."""
        return YOUR if person == self.name else f"{person}'s"

    def listed(self, people: Sequence[str]) -> str:
        """`people` listed, the witness as `you` in its own place."""
        return listed([self(person) for person in people])


Telling = Callable[[Witness], str]
"""A text as told to a witness."""


def tell(telling: str | Telling, witnesses: Iterable[str]) -> tuple[str, dict[str, str]]:
    """The text of `telling` for nobody in particular, and by witness the wording of each of
    `witnesses` it is told differently; a plain string is the same for everyone."""
    if isinstance(telling, str):
        return telling, {}
    text = telling(Witness())
    personal = {witness: telling(Witness(witness)) for witness in witnesses}
    return text, {witness: told for witness, told in personal.items() if told != text}
