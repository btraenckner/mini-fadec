"""Standards-compliant JSON serialization for verification artifacts."""

import json
from pathlib import Path

from simulation.scenarios.serialization import definition_to_dict


REQUIREMENTS_REPORT_SCHEMA_VERSION = "1.1"


def write_json_exclusive(path: Path, payload: object) -> None:
    """Write deterministic UTF-8 JSON without replacing an existing artifact."""

    serialized = definition_to_dict(payload)
    with path.open("x", encoding="utf-8") as output_file:
        json.dump(
            serialized,
            output_file,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        output_file.write("\n")

def update_json_object(path: Path, updates: dict[str, object]) -> None:
    """Extend an existing JSON object using JSON-safe values."""

    with path.open(encoding="utf-8") as input_file:
        payload = json.load(input_file)
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    payload.update(definition_to_dict(updates))
    with path.open("w", encoding="utf-8") as output_file:
        json.dump(
            payload,
            output_file,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        output_file.write("\n")
