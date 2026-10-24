"""Reading an experiment's configuration from YAML, where one file may overlay another.

A file that names `base:` (a path relative to the file) is read as an overlay on that base:
mappings are merged key by key, recursively, and every other value (a list, a scalar, null)
replaces the base's. Bases may chain. The four groups overlay one shared town
(`configs/town.yaml`), which is not a complete configuration by itself; the smoke town overlays
group C.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from infrastructure.config import ConfigError, describe_validation_error
from simulation.config import PROJECT_ROOT, ExperimentConfig, Resident

__all__ = ["PROJECT_ROOT", "ExperimentConfig", "Resident", "load_experiment", "overlay"]


def load_experiment(path: Path) -> ExperimentConfig:
    """The configuration in `path`, over its bases; errors name the file and the key paths."""
    data = _read(path.resolve(), ())
    try:
        return ExperimentConfig.model_validate(data)
    except ValidationError as error:
        raise ConfigError(f"{path}: {describe_validation_error(error)}") from error


def overlay(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    """`top` over `base`: mappings merged recursively, anything else replaced."""
    merged = dict(base)
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = overlay(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read(path: Path, chain: tuple[Path, ...]) -> dict[str, Any]:
    if path in chain:
        raise ConfigError(f"{path}: its bases lead back to it")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ConfigError(f"{path}: invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: not a mapping")
    base = data.pop("base", None)
    if base is None:
        return data
    return overlay(_read((path.parent / base).resolve(), (*chain, path)), data)
