"""Feature request models for implementation planning."""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class FeatureRequest(BaseModel):
    """Describes a feature that should be planned without being implemented."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    feature_name: str = Field(
        min_length=1,
        validation_alias=AliasChoices("feature_name", "name", "title"),
        serialization_alias="feature_name",
    )
    description: str = Field(min_length=1)
    requirements: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()

