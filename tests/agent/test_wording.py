import json

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
    fixed += texts.KNOWN_FILES.values()
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
