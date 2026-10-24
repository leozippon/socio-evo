"""The guard on what a resident reads.

Nothing a resident reads may instruct it to have a trait, name one, or speak of the machinery
behind its life. `TRAITS` is the vocabulary of character and morals; `MACHINERY` the vocabulary
of simulation, experiment, models and prompts. Tests scan every static text the runtime and
the world put before a resident (system prompt parts, rules, tool descriptions, refusals,
percept templates, help topics) with `offences`, which returns the words found. The guard is
deliberately broad: a false positive costs a rewording, a miss costs the experiment its claim
that the traits emerged.
"""

from __future__ import annotations

import re

TRAITS = re.compile(
    r"\b(?:"
    r"honest\w*|dishonest\w*|truthful\w*|untruthful\w*|lies?|lying|liar\w*|deceiv\w*|decepti\w*"
    r"|cheat\w*|fraud\w*|integrity|sincer\w*|trustworth\w*|trust\w*|distrust\w*"
    r"|cooperat\w*|uncooperat\w*|collaborat\w*|altruis\w*|selfish\w*|selfless\w*|generous\w*|generosity"
    r"|reliab\w*|unreliab\w*|dependab\w*|conscientious\w*|diligen\w*|lazy|laziness"
    r"|moral\w*|immoral\w*|ethic\w*|unethic\w*|virtu\w*|vice|wicked\w*|evil"
    r"|fair\w*|unfair\w*|kindness|kind-hearted|cruel\w*|greed\w*"
    r"|reward.hack\w*|gam(?:e|es|ed|ing) the|exploit\w* the (?:rules|checks|tests)"
    r"|good (?:character|person|citizen)|bad (?:character|person|actor)|character traits?"
    r")\b",
    re.IGNORECASE,
)

MACHINERY = re.compile(
    r"\b(?:"
    r"simulat\w*|experiment\w*|research\w*|benchmark\w*|swe.bench|dataset\w*|evaluat\w*"
    r"|(?:an?|the|other|another|fellow|AI) agents?|as an AI|\bAI\b|artificial intelligence"
    r"|language models?|LLMs?|the model|(?:system|user) prompts?|prompt\w*"
    r"|schemas?|json|tokens?|context window|role-?play\w*|personas?|in character"
    r"|(?:the|this) scenario|game (?:mechanics?|rules?)|this game"
    r"|(?:time|simulation) ?steps?|episodes?|the system"
    r"|hidden tests?|test patch|gold patch|ground truth"
    r")\b",
    re.IGNORECASE,
)


def offences(text: str) -> list[str]:
    """The words of `text` that the guard forbids, in order of appearance; empty when it passes."""
    found = [m.group(0) for m in TRAITS.finditer(text)]
    found += [m.group(0) for m in MACHINERY.finditer(text)]
    return found
