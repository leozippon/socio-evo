"""Strict immutable pydantic base and a validating YAML config loader."""

from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

M = TypeVar("M", bound=BaseModel)


class StrictModel(BaseModel):
    """Immutable model that rejects unknown fields; the base for configs and records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ConfigError(ValueError):
    """A config file is unreadable YAML or does not match its model."""


def load_config(path: Path, model: type[M]) -> M:
    """Load `path` as YAML and validate it as `model`; errors name the offending key paths."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {describe_validation_error(exc)}") from exc


def describe_validation_error(error: ValidationError) -> str:
    """One line per problem, `dotted.key.path: message`, joined by semicolons."""
    return "; ".join(
        f"{'.'.join(map(str, problem['loc'])) or '<root>'}: {problem['msg']}"
        for problem in error.errors()
    )
