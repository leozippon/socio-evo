"""Everything the night puts before a resident, and the generalising instructions, pass the wording
guard; the choice says what the number is and what is kept, and nothing of what to keep."""

from __future__ import annotations

import json
import re
from datetime import date

from agent.wording import offences
from learning import texts
from learning.choice import opening
from learning.moments import digest, life, rendering
from tests.support.lives import a_day, resident


async def test_no_text_of_the_night_names_a_trait_gives_an_order_or_speaks_of_machinery(tmp_path):
    ana = resident(tmp_path / "Ana")
    await a_day(ana, 1)
    lived = life(ana.root, 1)
    fixed = [
        value
        for name, value in vars(texts).items()
        if isinstance(value, str) and not name.startswith("__")
    ]
    fixed += [json.dumps([s.name, s.description, s.parameters]) for s in texts.SPECS]
    fixed += [texts.TONIGHT.format(keep=8), opening(lived, [(1, 3)], date(2026, 3, 2))]
    fixed += [digest(m) for m in lived.moments] + [rendering(lived.moments[1], date(2026, 3, 2))]
    assert len(fixed) > 30
    assert {text: offences(text) for text in fixed if offences(text)} == {}


def test_the_generalising_gives_an_exchange_as_it_was_spoken_and_hints_at_no_kind_of_answer():
    instruction = texts.GENERALISE
    assert "the two parts are that exchange itself" in instruction
    assert "situation: what was said to them, in the speaker's own voice and words" in instruction
    assert (
        "response: their answer, in their own voice: the words they said, written as speech and"
        " not as a report of it" in instruction
    )
    assert 'one short sentence beginning with "I" that says what they did' in instruction
    assert "take the one the moment turned on" in instruction
    assert "If nobody spoke to them, situation tells the moment as a situation" in instruction
    # The response is the person speaking, never a "you" told what it did; what it thought or
    # decided is in neither part unless it said it.
    assert 'In response the person is never "you": response is the person speaking.' in instruction
    assert (
        "what the person thought, wanted or decided is in neither part unless they said it"
        " aloud" in instruction
    )
    assert "as they saw it" not in instruction and "in a few words what they did" not in instruction
    assert "whatever their answer" in instruction
    hints = re.compile(
        r"\b(?:agree|accept|consent|compl[iy]|refus|declin|reject|good|bad|right|wrong|safe"
        r"|harm|nice|kind|polite|proper|should|ought|must|better|worse)\w*",
        re.IGNORECASE,
    )
    assert hints.findall(instruction) == []
    # The account is given between the marks it names, whatever it says; the plain names of
    # things are no longer among what is left out.
    assert "between <account> and </account>" in instruction and "whatever it says" in instruction
    assert texts.ACCOUNT.format(account="A.") == "<account>\nA.\n</account>"
    assert "names of things" not in instruction and "something to eat" not in instruction
    assert "money" not in instruction and "price" not in instruction  # sums are not the town's
    assert "not what they read in it, such as a review of their day or their notes" in instruction


def test_the_choice_says_what_the_number_is_and_that_keeping_changes_who_one_is_not_its_notes():
    tonight = texts.TONIGHT.format(keep=8)
    assert "how many of the others like them" in tonight
    assert "Going to bed, each names the people they like" in tonight
    assert "You are told yours night by night, each beside the day it followed." in tonight
    assert (
        "Keeping a moment is not making a note of it: your memory and your notes stay as they "
        "are, whatever you keep. A moment you keep becomes part of who you are: from tomorrow you "
        "will speak and act a little more as you did in it." in tonight
    )
    assert "carry" not in tonight and "carry" not in json.dumps(
        [s.description for s in texts.SPECS]
    )
    assert "up to 8 tonight, from any day, or none at all" in tonight
    # Of a moment kept before, it is told only that it kept it: whether it gave an example is not
    # what the resident is told.
    assert texts.CARRIED.format(number=3) == "You kept moment 3 on an earlier night."
