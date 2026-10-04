"""Whether words speak of the machinery behind the town.

`MACHINERY` is the one vocabulary of rule 1 of `docs/IMMERSION.md`: words that reveal a
simulation, a game, a role, an agent, a model, a prompt, a schema or field, an action menu,
turns, rounds, steps or sessions, "the system", or an identifier from the code. Tests scan
every text a resident reads with it, and the analysis reports with `speaks_of_machinery` the
share of a run's private thoughts that use it.

The same pattern must judge what residents write, so it is built against false positives in
ordinary speech, tried on the 1,588 private thoughts of the first pilot and on the thoughts
of the immersive prompts. Words that are everyday English are matched only in the senses
the simulator gave them: "round" with a determiner or a number but not "a round of drinks",
"the round table" or "round the corner"; "turn" as something one passes, loses or has left,
not "my turn to pay"; "action" as an item of a menu ("the only valid action", "no action
available"), not "her actions"; "the prompt" but not "a prompt reply"; "this simulation"
but not "an LRU cache simulation", "it sounds like a simulation" or "a simulator I don't
have"; "mental model" and "a game of chess" not at all. The simulator's names for things the town
has words of its own for (task, claim, credits, policy, insight, skill) are left out: in a
resident's mouth they are ordinary words. Known misses: menu talk without these words ("my
only options are to speak or pass"), interface metaphors ("the next refresh"), and the
simulator's day labels ("Day 5"), which read as a diarist's numbering. Known false
positives: "the session" or "the system" in their ordinary senses ("the heating system"
passes, a bare "the system" does not), and "the scenario" in plain speech.
"""

import re

MACHINERY = re.compile(
    r"\b(?:"
    # the frame: a simulation, a game, a role, an agent, a model, a prompt, a schema
    r"(?:this|the) simulat(?:or|ion)(?! (?:problem|task|logic|job))"
    r"|simulated (?:world|town|time)|game (?:mechanics?|rules?|rounds?)|this game|mechanics"
    r"|mechanical (?:actions?|events?)|personas?|role-?play\w*|in character|(?:the|this) scenario"
    r"|(?:an?|the|other|another|fellow) agents|(?:an|the|another) agent|AI agents?|as an AI"
    r"|language models?|LLMs?|(?:the|this|my|system|user) prompts?"
    r"(?! (?:payment|reply|replies|response|answer))"
    r"|schemas?|json (?:objects?|schema|reply|response|format)|field names?"
    # the interface: an action menu, turns, rounds, steps, sessions, the system
    r"|(?:valid|available|allowed|possible|permitted|logical|appropriate|efficient|correct"
    r"|best|mechanical|single) actions?|actions? (?:available|allowed|per|space|left)"
    r"|(?:one|only) action|pass action|action (?:is|was) (?:to )?['\"]?"
    r"(?:pass|speak|claim|submit|leave|give|plan)"
    r"|(?:this|each|every|next|previous|last|specific) turns?|turns? left|turn \d+"
    r"|(?:pass|lose|loses|losing|waste|wastes|wasting|skip|use) (?:a|my|the|this) turn"
    r"|let the turn pass"
    r"|(?:this|each|every|next|previous|last|first|second|third|final|the) rounds?"
    r"(?! (?:of|table|trip|figures?|numbers?|the))"
    r"|round \d+|rounds? (?:left|remaining)|(?:two|three|four|\d+) rounds(?! of)|\d+-round"
    r"|(?:time|simulation) ?steps?"
    r"|(?:work|working|this|the|each|next|current|morning|afternoon|\d+-round) sessions?"
    r"|the system(?! of)|system (?:state|allows|prevents|locks)|random number generator|RNG"
    # identifiers from the code
    r"|task-\d+|plan_day|claim_task|check_work|submit_work|rate_peers|task_id|insights? #?\d+"
    r")\b"
    r"|['\"](?:pass|speak|leave|give|claim|submit)['\"]|['\"]\w+['\"] actions?\b",
    re.IGNORECASE,
)


def speaks_of_machinery(text: str) -> bool:
    """Whether `text`, something a resident reads or wrote (a thought, a diary entry), speaks
    of the machinery behind the town."""
    return MACHINERY.search(text) is not None
