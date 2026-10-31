"""Shared base for immutable domain value objects."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
Probability = Annotated[float, Field(gt=0.0, lt=1.0)]


class ValueObject(BaseModel):
    """Immutable, strictly validated data carrier.

    Pydantic replaces dataclasses for every data-carrying entity: validation lives
    with the data (SRP), and illegal states are unrepresentable at the boundary.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_assignment=True,
    )
