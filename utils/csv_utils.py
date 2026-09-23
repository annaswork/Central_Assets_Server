"""CSV and plaintext import parsers with per-row validation reporting."""

import csv
import io
from typing import Any


def parse_csv_rows(content: str | bytes) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Parse CSV content into a list of row dicts, collecting parsing errors.

    Returns:
        (rows, errors) where errors contain line numbers and reason.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="replace")

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return [], [{"line": 1, "error": "CSV has no header row"}]

    # Normalize header names (lowercase, stripped, replace spaces with underscores)
    normalized_headers = [h.strip().lower().replace(" ", "_") for h in reader.fieldnames if h]
    reader.fieldnames = normalized_headers

    rows: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = []

    for line_num, row in enumerate(reader, start=2):
        if not any(v.strip() for v in row.values() if v):
            continue  # Skip blank lines
        clean_row = {k: (v.strip() if v else "") for k, v in row.items() if k}
        rows.append(clean_row)

    return rows, errors


def parse_lines_list(content: str | bytes) -> list[str]:
    """Parse plaintext newline-separated items (e.g. paste-a-list box).

    Strips empty lines and leading/trailing whitespace.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    lines = [line.strip() for line in content.splitlines()]
    return [line for line in lines if line]
