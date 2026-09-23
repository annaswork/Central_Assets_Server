"""Shared Pydantic validators and structure checks."""

import re
from typing import Any

from config.constants import MAX_JSON_DEPTH


def validate_json_depth(obj: Any, current_depth: int = 1) -> bool:
    """Recursively ensure a nested dictionary does not exceed MAX_JSON_DEPTH."""
    if current_depth > MAX_JSON_DEPTH:
        return False
    if isinstance(obj, dict):
        return all(validate_json_depth(v, current_depth + 1) for v in obj.values())
    if isinstance(obj, list):
        return all(validate_json_depth(v, current_depth + 1) for v in obj)
    return True


def is_valid_package_name(package_name: str) -> bool:
    """Validate Android/Java-style package name (e.g. com.example.app)."""
    pattern = r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$"
    return bool(re.match(pattern, package_name))
