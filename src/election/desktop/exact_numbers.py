"""Exact quantity text and safe QVariant copies for nested public API records."""

from copy import deepcopy
from typing import Any


def quantity_display(value: Any) -> Any:
    """Copy nested JSON and add exact text beside integer quantity fields."""
    if isinstance(value, dict):
        result = {key: quantity_display(item) for key, item in value.items()}
        for key, item in value.items():
            if type(item) is int and (
                key == "quantity" or key.endswith("_quantity")
                or key in ("difference", "reconciliation_difference")
            ):
                result[key + "_display"] = str(item)
        return result
    if isinstance(value, list):
        return [quantity_display(item) for item in value]
    return deepcopy(value)


def qt_state(state: dict[str, Any]) -> dict[str, Any]:
    """Copy a Qt view without overflowing QVariant's signed 64-bit integers."""
    def copied(value: Any) -> Any:
        if type(value) is int and not -(2**63) <= value < 2**63:
            return str(value)
        if isinstance(value, dict):
            return {key: copied(item) for key, item in value.items()}
        if isinstance(value, list):
            return [copied(item) for item in value]
        return deepcopy(value)

    return {key: copied(value) for key, value in state.items()}
