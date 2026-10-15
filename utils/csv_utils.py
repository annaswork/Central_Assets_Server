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

    reader = csv.DictReader(io.StringIO(content), skipinitialspace=True)
    if not reader.fieldnames:
        return [], [{"line": 1, "error": "CSV has no header row"}]

    # Normalize header names (lowercase, stripped, replace spaces with underscores)
    normalized_headers = [h.strip().lower().replace(" ", "_") for h in reader.fieldnames if h]
    reader.fieldnames = normalized_headers

    rows: list[dict[str, str]] = []
    errors: list[dict[str, Any]] = []

    for line_num, row in enumerate(reader, start=2):
        if not any(v.strip() for v in row.values() if isinstance(v, str) and v):
            continue  # Skip blank lines
        clean_row = {k: (v.strip() if v else "") for k, v in row.items() if k}
        # If there are overflow values (row has more comma-separated items than header columns)
        if None in row and row[None]:
            extra_vals = [x.strip() for x in row[None] if isinstance(x, str) and x.strip()]
            if extra_vals and normalized_headers:
                last_header = normalized_headers[-1]
                if last_header in clean_row and clean_row[last_header]:
                    clean_row[last_header] = clean_row[last_header] + ", " + ", ".join(extra_vals)
                else:
                    clean_row[last_header] = ", ".join(extra_vals)
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
