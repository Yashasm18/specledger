"""Version comparison and conflict detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import AttributeValue, ProductVersion


@dataclass(frozen=True)
class AttributeChange:
    attribute: str
    change_type: str
    previous: AttributeValue | None
    current: AttributeValue | None
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "attribute": self.attribute,
            "change_type": self.change_type,
            "previous_value": self.previous.value if self.previous else None,
            "current_value": self.current.value if self.current else None,
            "previous_unit": self.previous.unit if self.previous else None,
            "current_unit": self.current.unit if self.current else None,
            "message": self.message,
        }


def compare_versions(previous: ProductVersion, current: ProductVersion) -> list[AttributeChange]:
    if previous.product_id != current.product_id:
        raise ValueError("Only versions belonging to the same product can be compared")

    old = previous.attribute_map()
    new = current.attribute_map()
    changes: list[AttributeChange] = []

    for name in sorted(old.keys() | new.keys()):
        before = old.get(name)
        after = new.get(name)
        if before is None:
            changes.append(AttributeChange(name, "added", None, after, f"Attribute '{name}' was added"))
        elif after is None:
            changes.append(AttributeChange(name, "removed", before, None, f"Attribute '{name}' was removed"))
        elif before.value != after.value or before.unit != after.unit:
            changes.append(AttributeChange(name, "changed", before, after, f"Attribute '{name}' changed"))

    return changes

