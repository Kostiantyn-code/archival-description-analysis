"""Exploratory lexical markers in archival case titles.

The labels count mentions in descriptions. They do not classify the beliefs of
people named in the records or the contents of documents within a case.
"""
from __future__ import annotations

import html
import re
from collections import Counter
from pathlib import Path
from typing import Callable

from report_utils import json_for_script, write_csv
from models import Record


RULES_VERSION = "0.1-draft"
TEMPLATE = Path(__file__).resolve().parent / "maps" / "terminology-template.html"
GROUPS = (
    ("status", "Соціальний і правовий статус"),
    ("control", "Облік, розшук і нагляд"),
    ("ideology", "Політично забарвлена лексика"),
)
_RULES = (
    ("burgher", "Міщанин / мещанин", "status", r"міщан\w*|мещан\w*"),
    ("merchant", "Купець / купец", "status", r"купець\w*|купц\w*"),
    ("peasant", "Селянин / крестьянин", "status", r"селян\w*|крестьян\w*"),
    ("subject", "Підданий / подданный", "status", r"піддан\w*|поддан\w*"),
    ("honorary", "Почесний громадянин", "status", r"почесн\w*\s+громадян\w*|почетн\w*\s+граждан\w*"),
    ("serf", "Кріпосний селянин", "status", r"кріпосн\w*\s+селян\w*|крепостн\w*\s+крестьян\w*"),
    ("worker", "Робітник / рабочий", "status", r"робітник\w*|рабоч\w*"),
    ("passport", "Паспорт", "control", r"паспорт\w*"),
    ("supervision", "Нагляд / надзор", "control", r"нагляд\w*|надзор\w*"),
    ("police_supervision", "Поліцейський нагляд", "control", r"поліцейськ\w*\s+нагляд\w*|полицейск\w*\s+надзор\w*|нагляд\w*\s+поліці\w*|надзор\w*\s+полици\w*"),
    ("search", "Розшук / розыск", "control", r"розшук\w*|розшу\w*|розыс\w*"),
    ("expulsion", "Висилка / высылка", "control", r"висил\w*|вислан\w*|высл\w*"),
    ("exile", "Заслання / ссылка", "control", r"заслан\w*|ссыл\w*"),
    ("political", "Політичний / политический", "ideology", r"політичн\w*|политическ\w*"),
    ("revolutionary", "Революційний / революционный", "ideology", r"революц\w*"),
    ("propaganda", "Пропаганда", "ideology", r"пропаганд\w*"),
    ("unreliable", "Неблагонадійний / неблагонадежный", "ideology", r"неблагонадійн\w*|неблагонадежн\w*"),
    ("unrest", "Заворушення / волнения", "ideology", r"заворуш\w*|волнени\w*|беспорядк\w*"),
    ("censorship", "Цензура", "ideology", r"цензур\w*"),
    ("dissenter", "Розкольник / раскольник", "ideology", r"розкольник\w*|раскольник\w*|раскол\w*"),
    ("strike", "Страйк / стачка", "ideology", r"страйк\w*|стачк\w*|забастовк\w*"),
)
TERMS = tuple((term_id, label, group, re.compile(r"(?<!\w)(?:" + expression + r")", re.I))
              for term_id, label, group, expression in _RULES)
INDEX_FIELDS = ("record_uid", "archive", "fond", "inventory", "sheet", "case_id",
                "decade", "term_id", "term", "group", "matched_form", "title")
SUMMARY_FIELDS = ("scope", "description", "decade", "term_id", "term", "group",
                  "titles_total", "titles_with_term", "per_1000_titles")


def match_terms(title: str) -> list[tuple[str, str]]:
    """Return one example per marker, even if a word repeats in the title."""
    return [(term_id, hit.group(0)) for term_id, _, _, pattern in TERMS
            if (hit := pattern.search(title))]


def _examples(index: list[dict], term_id: str, sheets: list[str]) -> list[dict]:
    """Sample distinct cases across descriptions and periods for verification."""
    candidates = [row for row in index if row["term_id"] == term_id]
    selected: list[dict] = []
    seen: set[str] = set()
    for sheet in sheets:
        years = sorted({r["decade"] for r in candidates
                        if r["sheet"] == sheet and isinstance(r["decade"], int)})
        for year in years[:3]:
            row = next((r for r in candidates if r["sheet"] == sheet
                        and r["decade"] == year and r["record_uid"] not in seen), None)
            if row:
                selected.append(row)
                seen.add(row["record_uid"])
            if len(selected) == 8:
                return selected
    for row in candidates:
        if row["record_uid"] not in seen:
            selected.append(row)
            seen.add(row["record_uid"])
        if len(selected) == 8:
            break
    return selected


def write_terminology_report(
    active: list[Record], sheets: list[str], labels: dict[str, str],
    colors: dict[str, str], decade_of: Callable[[Record], int | None],
    tables_dir: Path, figures_dir: Path, scope: str,
) -> dict[str, int]:
    """Write exact counts and an offline interactive report for one workbook scope."""
    denominators: Counter[tuple[str, int]] = Counter()
    hits: Counter[tuple[str, int, str]] = Counter()
    index: list[dict] = []
    for record in active:
        decade = decade_of(record)
        if decade is not None:
            denominators["all", decade] += 1
            denominators[record.sheet_name, decade] += 1
        for term_id, matched_form in match_terms(record.title_raw):
            term = next(item for item in TERMS if item[0] == term_id)
            index.append({
                "record_uid": record.record_uid,
                "archive": record.source_archive, "fond": record.source_fond,
                "inventory": record.source_inventory, "sheet": record.sheet_name,
                "case_id": record.case_id_normalized, "decade": decade if decade is not None else "unknown",
                "term_id": term_id, "term": term[1], "group": term[2],
                "matched_form": matched_form, "title": record.title_raw,
            })
            if decade is not None:
                hits["all", decade, term_id] += 1
                hits[record.sheet_name, decade, term_id] += 1

    periods = sorted(decade for sheet, decade in denominators if sheet == "all")
    summary = []
    for sheet in ["all", *sheets]:
        for decade in periods:
            n = denominators[sheet, decade]
            for term_id, term_label, group, _ in TERMS:
                count = hits[sheet, decade, term_id]
                summary.append({
                    "scope": sheet, "description": "Увесь корпус" if sheet == "all" else labels[sheet],
                    "decade": decade, "term_id": term_id, "term": term_label, "group": group,
                    "titles_total": n, "titles_with_term": count,
                    "per_1000_titles": f"{count / n * 1000:.2f}" if n else "",
                })
    write_csv(tables_dir / "term_mentions.csv", INDEX_FIELDS, index,
              extrasaction="raise", create_parent=False)
    write_csv(tables_dir / "terms_by_decade_and_description.csv", SUMMARY_FIELDS, summary,
              extrasaction="raise", create_parent=False)

    data = {
        "terms": [{"id": t[0], "label": t[1], "group": t[2]} for t in TERMS],
        "groups": GROUPS, "periods": periods, "descriptions": sheets,
        "labels": [labels[s] for s in sheets], "colors": [colors[s] for s in sheets],
        "bases": {sheet: {d: denominators[sheet, d] for d in periods}
                  for sheet in ["all", *sheets]},
        "values": {sheet: {d: {t[0]: hits[sheet, d, t[0]] for t in TERMS} for d in periods}
                   for sheet in ["all", *sheets]},
        "examples": {t[0]: _examples(index, t[0], sheets) for t in TERMS},
    }
    payload = json_for_script(data)
    period_label = (f"{min(periods)}–{max(periods)}-ті" if periods else "немає датованих справ")
    page = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__DATA__", payload)
            .replace("__TITLE_COUNT__", f"{len(active):,}".replace(",", " "))
            .replace("__SCOPE__", html.escape(scope))
            .replace("__DECADE_RANGE__", period_label)
            .replace("__TERM_COUNT__", str(len(TERMS))))
    (figures_dir / "terminology_evolution.html").write_text(page, encoding="utf-8")
    return {"titles": len(active), "matches": len(index),
            "dated_titles": sum(denominators["all", d] for d in periods)}
