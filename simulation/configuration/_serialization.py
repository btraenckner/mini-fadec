"""Internal helpers for deterministic configuration serialization."""

from dataclasses import asdict
from enum import Enum
from typing import Any


def configuration_to_dict(configuration: object) -> dict[str, object]:
    """Return a JSON-compatible representation of one configuration tree."""

    value = _json_compatible(asdict(configuration))  # type: ignore[arg-type]
    if not isinstance(value, dict):
        raise TypeError("configuration must serialize to a dictionary")
    return value


def _json_compatible(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {
            str(key): _json_compatible(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        converted = [_json_compatible(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return sorted(converted, key=str)
        return converted
    return value
