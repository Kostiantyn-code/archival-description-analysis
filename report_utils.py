"""Shared serialization for CSV exports and standalone HTML reports."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Sequence


def write_csv(
    path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, Any]], *,
    extrasaction: str = "ignore", create_parent: bool = True,
) -> int:
    """Write Excel-compatible CSV and return the number of data rows.

    Strict writers can retain their error-on-extra-fields and existing-directory
    behavior. Rows are consumed once, so generators remain supported.
    """
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter=";",
                                extrasaction=extrasaction)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            written += 1
    return written


def json_for_script(data: Any) -> str:
    """Protect embedded JSON from source titles containing HTML closing tags."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
