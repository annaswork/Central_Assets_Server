"""Sequence ordering math for instance-level list items."""

from collections.abc import Sequence

from config.constants import SEQUENCE_STEP


def compute_next_sequence(current_max: int | None) -> int:
    """Calculate sequence number for appending a new item to the end of a list."""
    if current_max is None or current_max < 1:
        return 1
    return current_max + 1


def generate_sequence_reordering(ordered_ids: Sequence[str]) -> list[tuple[str, int]]:
    """Produce (id, sequence) pairs spaced by 1 (1, 2, 3...) for bulk reordering."""
    return [(item_id, index + 1) for index, item_id in enumerate(ordered_ids)]
