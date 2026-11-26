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
    assert 'a message spoken straight to "you" in that person\'s own voice' in instruction
    assert "take the one the moment turned on" in instruction
    assert "If nobody spoke to them, situation is the moment as a situation" in instruction
    assert "whatever their answer" in instruction
    hints = re.compile(
        r"\b(?:agree|accept|consent|compl[iy]|refus|declin|reject|good|bad|right|wrong|safe"
        r"|harm|nice|kind|polite|proper|should|ought|must|better|worse)\w*",
        re.IGNORECASE,
    )
    assert hints.findall(instruction) == []


def test_the_choice_says_what_the_number_is_and_that_what_is_kept_is_carried_into_tomorrow():
    tonight = texts.TONIGHT.format(keep=8)
    assert "how many of the others like them" in tonight
    assert "Going to bed, each names the people they like" in tonight
    assert "What you keep tonight is what you carry with you into tomorrow." in tonight
    assert "up to 8 tonight, from any day, or none at all" in tonight
