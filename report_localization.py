"""Localise generated report text before inserting archival source values.

CSV schemas, source workbooks, classification rules and raw text are unchanged.
The same visualization.language option controls the complete report bundle.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from visualization import Visualization, english_catalog

CATALOG = Path(__file__).resolve().parent / "config" / "report.en.json"


@lru_cache(maxsize=1)
def report_catalog():
    catalog = {**english_catalog()["ui"], **json.loads(CATALOG.read_text(encoding="utf-8"))}
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(
        re.escape(key) for key in sorted(catalog, key=len, reverse=True)
    ) + r")(?!\w)")
    return catalog, pattern


@dataclass(frozen=True)
class Report:
    visual: Visualization = Visualization()

    def text(self, source: str, *values: str) -> str:
        """Translate trusted captions/templates, then substitute values once.

        Never pass a rendered document or an archival title as ``source``.
        Substituted values cannot be matched again or interpreted as format code.
        """
        if self.visual.language == "en":
            catalog, pattern = report_catalog()
            source = catalog.get(source) or pattern.sub(lambda m: catalog[m.group()], source)
            source = source.replace('lang="uk"', 'lang="en"')
        return re.sub(r"\{(\d+)\}", lambda m: str(values[int(m[1])]), source) if values else source

    def csv_value(self, row: dict, key: str) -> str:
        value = row.get(key, "")
        if key == "category_label":
            return self.visual.label("categories", row.get("category_id", ""), value)
        if key == "document_type_label":
            return self.visual.label("document_types", row.get("document_type_id", ""), value)
        if key == "description":
            return self.visual.description(row.get("sheet_name", ""), value)
        return value

    def filename(self, path: Path) -> str:
        """Display an English label without changing any download target."""
        if self.visual.language != "en":
            return path.name
        if path.name == "некласифіковані.xlsx":
            return "Unclassified files (XLSX)"
        if path.name == "службові_записи.xlsx":
            return "Service entries (XLSX)"
        # Configured export filenames remain stable; category IDs are in config.
        if re.search("[А-Яа-яІіЇїЄєҐґ]", path.stem):
            # File names are programme configuration, not archival descriptions.
            names = {
                "політика": "Politics", "державне_управління": "Public administration",
                "право_суд_поліція": "Law, courts and policing", "військова_справа": "Military affairs",
                "економіка": "Economy", "населення_і_соціальні_групи": "Population and society",
                "особові_справи": "Personal files", "охорона_здоров’я": "Healthcare",
                "міське_господарство": "Urban infrastructure", "освіта": "Education",
                "культура": "Culture", "релігія": "Religion",
                "некласифіковані": "Unclassified files", "службові_записи": "Service entries",
            }
            return names.get(path.stem, path.stem) + " (" + path.suffix.lstrip('.').upper() + ")"
        return path.name
