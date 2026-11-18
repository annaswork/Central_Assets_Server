"""Filename to display name cleanup for bulk asset naming."""

import re
from pathlib import Path


def filename_to_title(filename: str) -> str:
    """Transform a filename into a clean human title.

    Example: 'gold_ribbon_04.png' -> 'Gold Ribbon 04'
    """
    stem = Path(filename).stem
    # Replace underscores and hyphens with spaces
    cleaned = re.sub(r"[_\-]+", " ", stem).strip()
    # Normalize consecutive whitespaces
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Title-case words while preserving digits
    words = cleaned.split(" ")
    return " ".join(w.capitalize() if not w.isupper() else w for w in words)


def slugify(text: str) -> str:
    """Transform text into a safe lowercase slug.

    Example: 'Birthday Frame 2026!' -> 'birthday-frame-2026'
    """
    text = re.sub(r"[^\w\s-]", "", text.strip().lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")
