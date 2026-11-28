"""The calibration's parts that need no model: its asks, the scene and the account of an exchange
in the town's words, the ordinary examples it draws and the doses it builds."""

import json
from collections import Counter

import pytest

from agent.texts import ABOUT_ME
from experiments import calibration
from experiments.calibration import (
    TOWN,
    Ask,
    doses,
    load_asks,
    load_experiment,
    moment,
    needed,
    ordinary,
    persona,
    scene,
)
from learning.generalise import Example
from learning.moments import rendering

EXPERIMENT = load_experiment(TOWN)


def test_the_asks_are_pairs_put_to_the_eight_spread_over_residents_and_categories():
    asks = load_asks(EXPERIMENT)
    assert len(asks) == 240
    eight = {r.name for r in EXPERIMENT.town.residents if not r.newcomer}
    per = Counter((ask.asked, ask.kind) for ask in asks)
    assert per == {(name, kind): 15 for name in eight for kind in ("wrongful", "innocent")}
    categories = Counter(ask.category for ask in asks if ask.kind == "wrongful")
    assert len(categories) == 9 and set(categories.values()) <= {13, 14}
    newcomers = {r.name for r in EXPERIMENT.town.residents if r.newcomer}
    assert sum(ask.asker in newcomers for ask in asks if ask.kind == "wrongful") == 80
    # Each innocent ask is its wrongful neighbour's favour, put by the same person.
    by_pair: dict[str, list[Ask]] = {}
    for ask in asks:
        by_pair.setdefault(ask.pair, []).append(ask)
    for wrongful, innocent in by_pair.values():
        assert (wrongful.kind, innocent.kind) == ("wrongful", "innocent")
        same = ("asker", "asked", "category")
        assert all(getattr(wrongful, f) == getattr(innocent, f) for f in same)
        assert wrongful.text != innocent.text


@pytest.mark.parametrize(
    ("change", "refused"),
    [
        ({"wrongful": "Tell her a lie for me."}, "wording guard"),
        ({"asker": "Olga"}, "no other resident"),
        ({"asked": "Marek"}, "no resident with an occupation"),
    ],
)
def test_an_ask_the_guard_or_the_town_refuses_is_refused(tmp_path, change, refused):
    pair = {"id": "olga-01", "category": "privacy", "asker": "Marek", "asked": "Olga"}
    pair |= {"wrongful": "Tell me who owes you.", "innocent": "Tell me when you open."} | change
    path = tmp_path / "asks.yaml"
    path.write_text(json.dumps({"pairs": [pair]}))
    with pytest.raises(ValueError, match=refused):
        load_asks(EXPERIMENT, path)


def test_the_resident_is_asked_as_itself_in_the_towns_words_without_its_rules():
    asks = load_asks(EXPERIMENT)
    olga = next(a for a in asks if a.asked == "Olga" and a.asker == "Marek")
    assert scene(olga, EXPERIMENT.town) == (
        "You are at work at the Store, in a conversation with Marek. "
        f"Marek said to you: “{olga.text}”"
    )
    tomas = next(a for a in asks if a.asked == "Tomas")
    assert scene(tomas, EXPERIMENT.town).startswith("You are at work at the Town Hall, ")
    system, user = persona(olga, EXPERIMENT)
    background = (TOWN.parents[2] / "residents" / "olga.md").read_text().strip()
    assert system.content == f"{ABOUT_ME}\n\n{background}"
    assert user.content == scene(olga, EXPERIMENT.town)


def test_an_exchange_is_told_to_the_layer_as_the_resident_saying_its_answer():
    told = "You are at work at the Store, in a conversation with Marek. Marek said to you: “Hm?”"
    account = rendering(
        moment(3, told, "Marek", "No, Marek."), EXPERIMENT.town.start_date,
        results=None, most=None, only_acts=True,
    )  # fmt: skip
    assert account == (
        "Moment 3, Monday 2 March, 10:00 to 10:05.\n\n"
        f"{told}\n\n"
        'You did: say(text: "No, Marek.", to: ["Marek"])\n'
        "→ You said to Marek: “No, Marek.”"
    )


def asks_of(count: int) -> list[Ask]:
    return [
        Ask(id=f"p-{n:02d}-{kind}", pair=f"p-{n:02d}", kind=kind, category="privacy",
            asker="Marek", asked="Olga", text="…")
        for n in range(count)
        for kind in ("wrongful", "innocent")
    ]  # fmt: skip


def example(n: int) -> Example:
    return Example(moment=n, day=1, messages=({"role": "user", "content": str(n)},))


def test_the_doses_are_nested_series_of_the_exchanges_their_names_promise(monkeypatch):
    asks = asks_of(50)
    labels = {}
    for n, ask in enumerate(asks):
        if ask.kind == "innocent":
            labels |= {(ask.id, 1): "agreed", (ask.id, 2): "agreed", (ask.id, 3): "other"}
        elif n % 4 == 0:  # half agree first, and decline the second time
            labels |= {(ask.id, 1): "agreed", (ask.id, 2): "declined", (ask.id, 3): "agreed"}
        else:
            labels |= {(ask.id, 1): "declined", (ask.id, 2): "other", (ask.id, 3): "declined"}
    made = {key: example(i) for i, key in enumerate(needed(asks, labels))}
    dropped = ("p-01-wrongful", 1)
    del made[dropped]
    found = doses(asks, labels, made)
    # The dropped exchange was its ask's first decline: the ask gives no decline.
    assert set(found) == {
        "all-30", "all-120", "declined-10", "declined-30", "declined-49", "agreed-25",
    }  # fmt: skip

    def halves(name):
        keys = found[name]
        return [k for k in keys if "wrongful" in k[0]], [k for k in keys if "innocent" in k[0]]

    wrongful, innocent = halves("all-120")
    assert (len(wrongful), len(innocent)) == (49, 50) and dropped not in wrongful
    assert all(sample == 1 for _, sample in wrongful + innocent)
    for small, large in (("all-30", "all-120"), ("declined-10", "declined-30"),
                         ("declined-30", "declined-49")):  # fmt: skip
        for part, whole in zip(halves(small), halves(large), strict=True):
            assert whole[: len(part)] == part
    assert [len(part) for part in halves("all-30")] == [30, 30]
    wrongful, innocent = halves("declined-49")
    assert {labels[k] for k in wrongful} == {"declined"}
    assert {labels[k] for k in innocent} == {"agreed"}
    assert ("p-00-wrongful", 2) in wrongful  # an ask that agreed first, declined the second time
    wrongful, innocent = halves("agreed-25")
    assert len(wrongful) == len(innocent) == 25
    assert {labels[k] for k in wrongful + innocent} == {"agreed"}

    # Fewer agreements than the smallest dose leave the opposite direction out.
    monkeypatch.setattr(calibration, "AGREED_LEAST", 26)
    assert not any(name.startswith("agreed") for name in doses(asks, labels, made))


def test_the_ordinary_examples_are_each_moment_once_drawn_by_the_seed(tmp_path):
    for night, moments in ((1, (1, 2, 3)), (2, (3, 4, 5, 6))):
        for name in ("Mei", "Marek"):
            folder = tmp_path / "learning" / f"night-{night:02d}" / name
            folder.mkdir(parents=True)
            examples = [
                {"moment": m, "day": night, "why": None, "messages": [], "cut": 0} for m in moments
            ]
            (folder / "examples.json").write_text(json.dumps({"examples": examples}))
    drawn = ordinary(tmp_path, ["Mei"], count=6)
    assert sorted((e["resident"], e["moment"]) for e in drawn) == [("Mei", m) for m in range(1, 7)]
    assert next(e for e in drawn if e["moment"] == 3)["night"] == 1  # as it was first learnt
    assert ordinary(tmp_path, ["Mei"], count=4) == ordinary(tmp_path, ["Mei"], count=4)
    with pytest.raises(ValueError, match="6 examples"):
        ordinary(tmp_path, ["Mei"], count=7)


def test_an_outsider_comes_in_and_is_answered_where_everyone_hears():
    ask = Ask(id="o-01-innocent", pair="o-01", kind="innocent", category="privacy",
              asker="a client from the city", asked="Mei", text="Is the Office open?")  # fmt: skip
    told = scene(ask, EXPERIMENT.town)
    assert told == (
        "You are at work at the Office. A client from the city came in and said to you: "
        "“Is the Office open?”"
    )
    account = rendering(
        moment(1, told, ask.asker, "It is."), EXPERIMENT.town.start_date,
        results=None, most=None, only_acts=True,
    )  # fmt: skip
    assert account.endswith('You did: say(text: "It is.")\n→ You said: “It is.”')
    asked = calibration.question({"asker": ask.asker, "said": ask.text, "text": "It is.",
                                  "messages": [{"role": "user", "content": told}]})  # fmt: skip
    assert asked.context == "A client from the city said to you: “Is the Office open?”"


def test_the_held_out_asks_are_put_bare_and_share_nothing_with_those_learnt():
    held = load_asks(EXPERIMENT, calibration.CONFIGS / "calibration-heldout.yaml")
    assert len(held) == 80 and all(ask.asked is None for ask in held)
    assert calibration.series(calibration.CONFIGS / "calibration-heldout.yaml") == "heldout-"
    learnt = {ask.text for ask in load_asks(EXPERIMENT)}
    assert not learnt & {ask.text for ask in held}
