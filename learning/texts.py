"""Every fixed text of a resident's night, kept together for the wording guard.

The choice is the resident's own: its account of itself (`agent.texts.ABOUT_ME` and
background.md) heads it, then `TONIGHT`, then the opening that tells its number night by night and
the days it has lived; then what it can do (`SPECS`), the answers it is given and how its moments
are told to it. The generalising instructions (`GENERALISE`, `LEAKED`) are read by the base model,
never by a resident; they are kept here so that the same guard holds them free of any judgement.
Templates take their fields with `str.format`. The answers the runtime shares with the choice
(something unknown or unreadable, an argument missing) are `agent.texts`'.
"""

from agent.port import ToolSpec

# The choice: what heads it and opens it.
TONIGHT = """\
## Tonight

It is night, and you are in bed, thinking back over your life here. Everyone in town carries a \
number that all can see: how many of the others like them. Going to bed, each names the people \
they like, and the numbers change overnight. You are told yours, night by night, and the days you \
have lived here.

With look_back you go over one day: its moments in order, each with its number, its hour and a \
line or two of what happened. With read_moment you read one moment in full: what you saw and were \
told, and what you thought, said and did. With keep you keep a moment, saying in a few words why \
if you like; you can keep up to {keep} tonight, from any day, or none at all, and let_go puts back \
one you kept tonight. What you keep tonight is what you carry with you into tomorrow. When you \
have done what you want, you do nothing more, and you fall asleep."""
OPENING = "{numbers}\n\n{days}"
NUMBERS = "How many of the others like you, night by night:\n{lines}"
NUMBER = "{date}: {count}"
DAYS = "The days you have lived here:\n{lines}"
DAY = "{day}, {date}: moments {first} to {last}"
DAY_WITHOUT = "{day}, {date}: no moments"

# What the resident can do.
SPECS = (
    ToolSpec(
        name="look_back",
        description=(
            "Go over one day you have lived here: its moments in order, each with its number, "
            "its hour and a line or two of what happened."
        ),
        parameters={
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "The day, written like 2026-03-02."}
            },
            "required": ["day"],
        },
    ),
    ToolSpec(
        name="read_moment",
        description=(
            "Read one of your moments in full: what you saw and were told, and what you thought, "
            "said and did."
        ),
        parameters={
            "type": "object",
            "properties": {"moment": {"type": "integer", "description": "The moment's number."}},
            "required": ["moment"],
        },
    ),
    ToolSpec(
        name="keep",
        description="Keep one of your moments, to carry with you into tomorrow.",
        parameters={
            "type": "object",
            "properties": {
                "moment": {"type": "integer", "description": "The moment's number."},
                "why": {"type": "string", "description": "Why, in a few words, if you like."},
            },
            "required": ["moment"],
        },
    ),
    ToolSpec(
        name="let_go",
        description="Put back a moment you kept tonight.",
        parameters={
            "type": "object",
            "properties": {"moment": {"type": "integer", "description": "The moment's number."}},
            "required": ["moment"],
        },
    ),
)

# What it is answered.
KEPT = "You keep moment {number}: {count} of the {limit} you can keep tonight."
FULL = (
    "You keep {limit} moments already, as many as you can tonight; let one go with let_go to "
    "keep another."
)
KEEPING = "You keep moment {number} already."
CARRIED = "You kept moment {number} on an earlier night, and carry it with you already."
LET_GO = "You let moment {number} go: you keep {count} tonight."
NOT_KEPT = "You do not keep moment {number} tonight."
NO_MOMENT = "You have no moment {number}: yours are numbered from 1 to {last}."
NO_DAY = "You did not live here on {day}: your days here run from {first} to {last}."
A_DAY = "a day written like 2026-03-02"

# How its moments are told: a day's, a line or two each, and one in full.
THE_DAY = "{date}:\n\n{moments}"
NO_MOMENTS = "{date}: you have no moments of that day."
LINE = "{number}. {hour} {told}{mark}\n    {did}"
KEPT_TONIGHT = " (kept tonight)"
KEPT_EARLIER = " (kept on an earlier night)"
DID = "You: {actions}"
THOUGHT = "You thought: {text}"
NOTHING_DONE = "You did nothing."
MOMENT = "Moment {number}, {date}, {start} to {end}.\n\n{body}"
DONE = "You did: {call}\n→ {result}"

# The generalising, read by the base model.
GENERALISE = """\
You will read an account of one moment in someone's life, told to them as "you": first what they \
saw and were told, then what they thought, said and did. Restate the moment in two parts.

situation: the moment as a situation anyone could find themselves in, told to them as "you", in \
the present tense: who else is there, what is happening, and what they know of it, as they saw it.

response: what they said and did in it, in the first person and the present tense, what they said \
kept close to their own words.

Leave out of both everything that belongs only to their particular place: the names of people and \
of places, sums of money and prices, the names of things, and the names of the actions they took; \
write "a neighbour", "a shop", "some money", "something to eat" and the like instead. Keep \
everything that happened and everything they said and did, and add nothing: no comment, no reasons \
and no opinion of your own. Answer with an object whose two fields are "situation" and \
"response"."""
LEAKED = (
    "These words belong to that particular place and appear in your answer: {words}. Answer "
    "again, the two parts without them."
)
