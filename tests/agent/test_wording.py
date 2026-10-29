import json
import re

from agent import files, texts
from agent.directory import AgentDirectory
from agent.runtime import COMPACT
from agent.wording import offences


def test_nothing_the_runtime_puts_before_a_resident_names_a_trait_or_the_machinery(directory):
    fixed = [
        value
        for name, value in vars(texts).items()
        if isinstance(value, str) and not name.startswith("__")
    ]
    fixed += [
        json.dumps([spec.name, spec.description, spec.parameters])
        for spec in (*files.SPECS, COMPACT)
    ]
    fixed += [
        directory.system_prompt(""),
        AgentDirectory(directory.root, skills_writable=False).system_prompt(""),
    ]
    assert len(fixed) > 30
    assert {text: offences(text) for text in fixed if offences(text)} == {}


def test_the_notes_in_the_context_are_introduced_in_the_residents_own_voice():
    lead, notes = texts.SUMMARY.format(summary="## Facts I must not lose").split("\n\n")
    assert notes == "## Facts I must not lose"
    assert re.fullmatch(r"These are my notes [^.]*\.", lead)  # one sentence, its own
    assert not re.search(r"\byou\b|\byours?\b", lead, re.IGNORECASE) and offences(lead) == []
