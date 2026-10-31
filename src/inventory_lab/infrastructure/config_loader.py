# src/inventory_lab/infrastructure/config_loader.py
"""Boundary validation: untrusted JSON/YAML becomes a validated ExperimentSpec."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from inventory_lab.application.specs import ExperimentSpec
from inventory_lab.domain.errors import ConfigurationError


def load_experiment(path: Path) -> ExperimentSpec:
    if not path.is_file():
        raise ConfigurationError(f"experiment file not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() in {".yaml", ".yml"}:
            try:
                import yaml  # ty: ignore[unresolved-import]
            except ImportError as exc:
                raise ConfigurationError(
                    "YAML support requires `pip install .[yaml]`"
                ) from exc
            raw = yaml.safe_load(text)
        else:
            raw = json.loads(text)
        return ExperimentSpec.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(f"invalid experiment specification:\n{exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"malformed JSON in {path}: {exc}") from exc
