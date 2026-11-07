"""Explicit source-clock contracts. Receipt is not proof of a new measurement."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceContract:
    semantics: str = "received"
    timestamp_attribute: str | None = None
    timestamp_entity: str | None = None

    def __post_init__(self):
        if self.semantics not in ("received", "origin", "provider"):
            raise ValueError("Unknown source contract")
        if self.timestamp_attribute and self.timestamp_entity:
            raise ValueError("Choose one origin timestamp route")
        if self.semantics == "origin" and not (
            self.timestamp_attribute or self.timestamp_entity
        ):
            raise ValueError("Origin semantics requires an explicit timestamp source")
        if self.semantics != "origin" and (
            self.timestamp_attribute or self.timestamp_entity
        ):
            raise ValueError("Timestamp sources require origin semantics")
        for value in (self.timestamp_attribute, self.timestamp_entity):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError("Invalid timestamp route")
