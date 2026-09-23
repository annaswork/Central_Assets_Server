"""Validates, parses, and normalizes more_fields typed blocks."""

from typing import Any

from pydantic import TypeAdapter

from database.models.more_fields import TypedBlock
from utils.errors import ValidationError

_typed_block_adapter: TypeAdapter[TypedBlock] = TypeAdapter(TypedBlock)


def validate_and_parse_block(block_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a single typed block against the discriminated union schema."""
    if not isinstance(payload, dict):
        raise ValidationError(f"Block '{block_key}' must be a dictionary object")

    block_type = payload.get("type")
    if not block_type:
        raise ValidationError(f"Block '{block_key}' is missing mandatory 'type' field")

    try:
        validated = _typed_block_adapter.validate_python(payload)
        return validated.model_dump(mode="json")
    except Exception as exc:
        raise ValidationError(
            f"Validation failed for more_fields block '{block_key}' of type '{block_type}': {exc}"
        ) from exc


def validate_more_fields_dict(more_fields: dict[str, Any]) -> dict[str, Any]:
    """Validate all typed blocks inside more_fields."""
    result = {}
    for key, block in more_fields.items():
        result[key] = validate_and_parse_block(key, block)
    return result
