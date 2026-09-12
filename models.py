"""Записи опису, категорії та повідомлення перевірки."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Issue:
    level: str
    row: int | None
    case_id: str
    field: str
    value: str
    message: str
    sheet_name: str = ""


CATEGORY_RULE_FIELDS = ('strong_phrases', 'strong_terms', 'context_only_phrases', 'context_only_terms', 'contextual_terms', 'context_rules', 'exclude_phrases', 'review_terms')


@dataclass
class Category:
    id: str
    label: str
    macroblock: str
    minimum_score: int
    strong_phrases: list[str]
    strong_terms: list[str]
    context_only_phrases: list[str]
    context_only_terms: list[str]
    contextual_terms: list[str]
    context_rules: list[dict[str, Any]]
    exclude_phrases: list[str]
    review_terms: list[str]
    export_filename: str = ""


@dataclass
class Record:
    excel_row: int
    sheet_name: str
    case_id_raw: str
    case_id_normalized: str
    title_raw: str
    dates_raw: str
    pages_raw: str
    notes_raw: str
    status: str
    section_year: int | None
    source_archive: str = ""
    source_fond: str = ""
    source_inventory: str = ""
    source_id: str = ""
    language: str = "uk"
    detected_language: str = "undetermined"
    language_source: str = "sheet_setting"
    section_label: str = ""
    start_year: int | None = None
    end_year: int | None = None
    pages: int | None = None
    categories: list[str] = field(default_factory=list)
    category_labels: list[str] = field(default_factory=list)
    macroblocks: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    context_categories: list[str] = field(default_factory=list)
    context_category_labels: list[str] = field(default_factory=list)
    context_evidence: dict[str, list[str]] = field(default_factory=dict)
    review_flags: list[str] = field(default_factory=list)


