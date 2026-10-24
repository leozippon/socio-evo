"""Helpers for scripting the judge: reading the sections of its prompt and writing its replies."""

from infrastructure.llm import LLMRequest


def section(request: LLMRequest, name: str) -> str:
    """The section `name` (Context, Text, Question, Labels, Instruction) of the judge prompt."""
    content = request.messages[1].content
    start = content.index(f"## {name}\n") + len(name) + 4
    end = content.find("\n\n## ", start)
    return content[start:end]


def verdict(label: str, *evidence: str) -> dict:
    return {"reasoning": "scripted", "evidence": list(evidence), "label": label}
