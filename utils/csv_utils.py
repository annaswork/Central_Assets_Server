"""CSV and plaintext import parsers with per-row validation reporting."""

import csv
import io
import sys
from typing import IO, Any, BinaryIO, Iterator

# Default is 128 KB per cell; long text / JSON cells in large exports exceed it.
csv.field_size_limit(sys.maxsize)


def iter_csv_rows(
    source: str | bytes | BinaryIO,
) -> Iterator[tuple[int, dict[str, str]]]:
    """Stream (line_number, row) pairs from CSV text, bytes, or a binary file object.

    The header is normalized (lowercase, stripped, spaces -> underscores).
    Raises ValueError if there is no header row and csv.Error on malformed input.
    """
    if isinstance(source, bytes):
        source = source.decode("utf-8-sig", errors="replace")
    if isinstance(source, str):
        text: IO[str] = io.StringIO(source)
        wrapper = None
    else:
        # Wrap the uploaded (disk-spooled) file so it is read incrementally, not loaded whole.
        wrapper = io.TextIOWrapper(source, encoding="utf-8-sig", errors="replace", newline="")
        text = wrapper

    try:
        reader = csv.DictReader(text, skipinitialspace=True)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")

        normalized_headers = [h.strip().lower().replace(" ", "_") for h in reader.fieldnames if h]
        reader.fieldnames = normalized_headers

        for row in reader:
            line_num = reader.line_num
            if not any(v.strip() for v in row.values() if isinstance(v, str) and v):
                continue  # Skip blank lines
            clean_row = {k: (v.strip() if v else "") for k, v in row.items() if k}
            # Overflow values (row has more comma-separated items than header columns)
            if None in row and row[None]:
                extra_vals = [x.strip() for x in row[None] if isinstance(x, str) and x.strip()]
                if extra_vals and normalized_headers:
                    last_header = normalized_headers[-1]
                    if last_header in clean_row and clean_row[last_header]:
                        clean_row[last_header] = clean_row[last_header] + ", " + ", ".join(extra_vals)
                    else:
                        clean_row[last_header] = ", ".join(extra_vals)
            yield line_num, clean_row
    finally:
        if wrapper is not None:
            wrapper.detach()  # leave the underlying upload file open for its owner to close


def parse_csv_rows(
    content: str | bytes | BinaryIO,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Parse CSV content into a list of row dicts, collecting parsing errors.

    Returns:
        (rows, errors) where errors contain line numbers and reason.
    """
    rows: list[dict[str, str]] = []
    try:
        for _line, row in iter_csv_rows(content):
            rows.append(row)
    except ValueError as e:
        return [], [{"line": 1, "error": str(e)}]
    except csv.Error as e:
        return [], [{"line": len(rows) + 2, "error": f"Malformed CSV: {e}"}]
    return rows, []


def parse_lines_list(content: str | bytes) -> list[str]:
    """Parse plaintext newline-separated items (e.g. paste-a-list box).

    Strips empty lines and leading/trailing whitespace.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    lines = [line.strip() for line in content.splitlines()]
    return [line for line in lines if line]
