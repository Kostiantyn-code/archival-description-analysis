"""Exploratory labels for document forms mentioned in archival case titles.

These are lexical mentions, not a verified inventory of documents within a file.
Several labels can apply to one title. Generic headings such as ``Справа про``
and ``Дело о`` intentionally have no label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from language_packs import alias_hits
import html
from collections import Counter
from pathlib import Path
from typing import Callable
from report_utils import json_for_script, write_csv
from models import Record
from localization import Visualization, english_catalog

DOCUMENT_TYPE_RULES_VERSION = "0.1-draft"


@dataclass(frozen=True)
class DocumentType:
    id: str
    label: str
    pattern: re.Pattern[str]


_DOCUMENT_RULES = (
    (
        "correspondence",
        "Листування та листи",
        r"\b(?:листуван[а-яіїєґ]*|лист(?:и|а|ів|ами|ах|ом|у|і)?|переписк[а-яё]*|письм(?:о|а|у|ом|е|ами|ах)|писем)\b",
    ),
    (
        "reports",
        "Рапорти та донесення",
        r"\b(?:рапорт[а-яіїєґё]*|донесенн[а-яіїєґ]*|донесени[а-яё]*)\b",
    ),
    (
        "instructions",
        "Приписи та розпорядження",
        r"\b(?:припис(?:и|ів|а|у|ом|ами|ах)?|розпоряджен[а-яіїєґ]*|предписани[а-яё]*|распоряжени[а-яё]*)\b",
    ),
    (
        "circulars",
        "Обіжники та циркуляри",
        r"\b(?:обіжник[а-яіїєґ]*|циркуляр[а-яіїєґё]*)\b",
    ),
    (
        "petitions",
        "Клопотання та прохання",
        r"\b(?:клопотанн[а-яіїєґ]*|проханн[а-яіїєґ]*|прошенн[а-яіїєґ]*|ходатайств[а-яё]*|прошени[а-яё]*)\b",
    ),
    (
        "statements",
        "Відомості та звіти",
        r"\b(?:відомост[а-яіїєґ]*|звіт[а-яіїєґ]*|ведомост[а-яё]*|отч[её]т[а-яё]*)\b",
    ),
    (
        "decrees",
        "Укази та накази",
        r"\b(?:указ[а-яіїєґё]*|наказ[а-яіїєґ]*|приказ[а-яё]*)\b",
    ),
    (
        "memoranda",
        "Доповіді та записки",
        r"\b(?:доповід[а-яіїєґ]*|записк[а-яіїєґё]*|доклад[а-яё]*)\b",
    ),
    (
        "lists",
        "Списки та реєстри",
        r"\b(?:списк[а-яіїєґё]*|список|реєстр[а-яіїєґ]*|реестр[а-яё]*)\b",
    ),
    (
        "minutes",
        "Протоколи та журнали",
        r"\b(?:протокол[а-яіїєґё]*|журнал[а-яіїєґё]*)\b",
    ),
    (
        "certificates",
        "Паспорти та свідоцтва",
        r"\b(?:паспорт[а-яіїєґё]*|свідоцтв[а-яіїєґ]*|свидетельств[а-яё]*)\b",
    ),
    (
        "plans",
        "Плани, проєкти та кошториси",
        r"\b(?:план(?:и|ів|у|ом|ах|ами|ов|а|е)?|проєкт[а-яіїєґ]*|проект[а-яё]*|кошторис[а-яіїєґ]*|смет[а-яё]*)\b",
    ),
    (
        "complaints",
        "Скарги та заяви",
        r"\b(?:скарг[а-яіїєґ]*|заяв(?:а|и|ою|і|ами|ах)|жалоб[а-яё]*|заявлени[а-яё]*)\b",
    ),
    (
        "acts",
        "Акти та постанови",
        r"\b(?:акт(?:и|ів|а|ом|у|ами|ах|ов|ы)?|постанов[а-яіїєґ]*|постановлени[а-яё]*)\b",
    ),
    (
        "notifications",
        "Повідомлення та телеграми",
        r"\b(?:повідомленн[а-яіїєґ]*|телеграм[а-яіїєґё]*|уведомлени[а-яё]*|сообщени[а-яё]*)\b",
    ),
)

DOCUMENT_TYPES = tuple(
    DocumentType(
        id, english_catalog()["document_types"][id], re.compile(pattern, re.IGNORECASE)
    )
    for id, label, pattern in _DOCUMENT_RULES
)


def match_document_types(
    title: str, language: str = "uk"
) -> list[tuple[DocumentType, str]]:
    """Return each mentioned type once, with an example matched expression."""
    matches = []
    if language not in {"uk", "ru"}:
        hits = alias_hits(title, language, "document_types")
        return [
            (document_type, hits[document_type.id])
            for document_type in DOCUMENT_TYPES
            if document_type.id in hits
        ]
    for document_type in DOCUMENT_TYPES:
        match = document_type.pattern.search(title)
        if match:
            matches.append((document_type, match.group(0)))
    return matches


RULES_VERSION = "0.1-draft"
TEMPLATE = Path(__file__).resolve().parent / "maps" / "terminology-template.html"
GROUPS = (
    ("status", "Соціальний і правовий статус"),
    ("control", "Облік, розшук і нагляд"),
    ("ideology", "Політично забарвлена лексика"),
)
_TERM_RULES = (
    ("burgher", "Міщанин / мещанин", "status", r"міщан\w*|мещан\w*"),
    ("merchant", "Купець / купец", "status", r"купець\w*|купц\w*"),
    ("peasant", "Селянин / крестьянин", "status", r"селян\w*|крестьян\w*"),
    ("subject", "Підданий / подданный", "status", r"піддан\w*|поддан\w*"),
    (
        "honorary",
        "Почесний громадянин",
        "status",
        r"почесн\w*\s+громадян\w*|почетн\w*\s+граждан\w*",
    ),
    (
        "serf",
        "Кріпосний селянин",
        "status",
        r"кріпосн\w*\s+селян\w*|крепостн\w*\s+крестьян\w*",
    ),
    ("worker", "Робітник / рабочий", "status", r"робітник\w*|рабоч\w*"),
    ("passport", "Паспорт", "control", r"паспорт\w*"),
    ("supervision", "Нагляд / надзор", "control", r"нагляд\w*|надзор\w*"),
    (
        "police_supervision",
        "Поліцейський нагляд",
        "control",
        r"поліцейськ\w*\s+нагляд\w*|полицейск\w*\s+надзор\w*|нагляд\w*\s+поліці\w*|надзор\w*\s+полици\w*",
    ),
    ("search", "Розшук / розыск", "control", r"розшук\w*|розшу\w*|розыс\w*"),
    ("expulsion", "Висилка / высылка", "control", r"висил\w*|вислан\w*|высл\w*"),
    ("exile", "Заслання / ссылка", "control", r"заслан\w*|ссыл\w*"),
    (
        "political",
        "Політичний / политический",
        "ideology",
        r"політичн\w*|политическ\w*",
    ),
    ("revolutionary", "Революційний / революционный", "ideology", r"революц\w*"),
    ("propaganda", "Пропаганда", "ideology", r"пропаганд\w*"),
    (
        "unreliable",
        "Неблагонадійний / неблагонадежный",
        "ideology",
        r"неблагонадійн\w*|неблагонадежн\w*",
    ),
    (
        "unrest",
        "Заворушення / волнения",
        "ideology",
        r"заворуш\w*|волнени\w*|беспорядк\w*",
    ),
    ("censorship", "Цензура", "ideology", r"цензур\w*"),
    (
        "dissenter",
        "Розкольник / раскольник",
        "ideology",
        r"розкольник\w*|раскольник\w*|раскол\w*",
    ),
    ("strike", "Страйк / стачка", "ideology", r"страйк\w*|стачк\w*|забастовк\w*"),
)
GROUPS = tuple((key, english_catalog()["term_groups"][key]) for key, _ in GROUPS)
TERMS = tuple(
    (
        term_id,
        english_catalog()["terms"][term_id],
        group,
        re.compile(r"(?<!\w)(?:" + expression + r")", re.I),
    )
    for term_id, label, group, expression in _TERM_RULES
)
INDEX_FIELDS = (
    "record_uid",
    "archive",
    "fond",
    "inventory",
    "sheet",
    "case_id",
    "decade",
    "term_id",
    "term",
    "group",
    "matched_form",
    "title",
)
SUMMARY_FIELDS = (
    "scope",
    "description",
    "decade",
    "term_id",
    "term",
    "group",
    "titles_total",
    "titles_with_term",
    "per_1000_titles",
)


def match_terms(title: str, language: str = "uk") -> list[tuple[str, str]]:
    """Return one example per marker, even if a word repeats in the title."""
    if language not in {"uk", "ru"}:
        return list(alias_hits(title, language, "terminology").items())
    return [
        (term_id, hit.group(0))
        for term_id, _, _, pattern in TERMS
        if (hit := pattern.search(title))
    ]


def _examples(index: list[dict], term_id: str, sheets: list[str]) -> list[dict]:
    """Sample distinct cases across descriptions and periods for verification."""
    candidates = [row for row in index if row["term_id"] == term_id]
    selected: list[dict] = []
    seen: set[str] = set()
    for sheet in sheets:
        years = sorted(
            {
                r["decade"]
                for r in candidates
                if r["sheet"] == sheet and isinstance(r["decade"], int)
            }
        )
        for year in years[:3]:
            row = next(
                (
                    r
                    for r in candidates
                    if r["sheet"] == sheet
                    and r["decade"] == year
                    and r["record_uid"] not in seen
                ),
                None,
            )
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
    active: list[Record],
    sheets: list[str],
    labels: dict[str, str],
    colors: dict[str, str],
    decade_of: Callable[[Record], int | None],
    tables_dir: Path,
    figures_dir: Path,
    scope: str,
    visual: Visualization | None = None,
) -> dict[str, int]:
    """Write exact counts and an offline interactive report for one workbook scope."""
    visual = visual or Visualization()
    denominators: Counter[tuple[str, int]] = Counter()
    hits: Counter[tuple[str, int, str]] = Counter()
    index: list[dict] = []
    for record in active:
        decade = decade_of(record)
        if decade is not None:
            denominators["all", decade] += 1
            denominators[record.sheet_name, decade] += 1
        for term_id, matched_form in match_terms(record.title_raw, record.language):
            term = next(item for item in TERMS if item[0] == term_id)
            index.append(
                {
                    "record_uid": record.record_uid,
                    "archive": record.source_archive,
                    "fond": record.source_fond,
                    "inventory": record.source_inventory,
                    "sheet": record.sheet_name,
                    "case_id": record.case_id_normalized,
                    "decade": decade if decade is not None else "unknown",
                    "term_id": term_id,
                    "term": term[1],
                    "group": term[2],
                    "matched_form": matched_form,
                    "title": record.title_raw,
                }
            )
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
                summary.append(
                    {
                        "scope": sheet,
                        "description": (
                            "Увесь корпус" if sheet == "all" else labels[sheet]
                        ),
                        "decade": decade,
                        "term_id": term_id,
                        "term": term_label,
                        "group": group,
                        "titles_total": n,
                        "titles_with_term": count,
                        "per_1000_titles": f"{count / n * 1000:.2f}" if n else "",
                    }
                )
    write_csv(
        tables_dir / "term_mentions.csv",
        INDEX_FIELDS,
        index,
        extrasaction="raise",
        create_parent=False,
    )
    write_csv(
        tables_dir / "terms_by_decade_and_description.csv",
        SUMMARY_FIELDS,
        summary,
        extrasaction="raise",
        create_parent=False,
    )

    data = {
        "terms": [
            {"id": t[0], "label": visual.label("terms", t[0], t[1]), "group": t[2]}
            for t in TERMS
        ],
        "groups": [
            (key, visual.label("term_groups", key, label)) for key, label in GROUPS
        ],
        "periods": periods,
        "descriptions": sheets,
        "labels": [visual.description(s, labels[s]) for s in sheets],
        "colors": [colors[s] for s in sheets],
        "bases": {
            sheet: {d: denominators[sheet, d] for d in periods}
            for sheet in ["all", *sheets]
        },
        "values": {
            sheet: {d: {t[0]: hits[sheet, d, t[0]] for t in TERMS} for d in periods}
            for sheet in ["all", *sheets]
        },
        "examples": {t[0]: _examples(index, t[0], sheets) for t in TERMS},
    }
    payload = json_for_script(data)
    period_label = (
        f"{min(periods)}–{max(periods)}{visual.text('s')}"
        if periods
        else visual.text("no dated case files")
    )
    page = (
        visual.template(TEMPLATE.read_text(encoding="utf-8"))
        .replace("__DATA__", payload)
        .replace("__TITLE_COUNT__", f"{len(active):,}".replace(",", " "))
        .replace("__SCOPE__", html.escape(visual.text(scope)))
        .replace("__DECADE_RANGE__", period_label)
        .replace("__TERM_COUNT__", str(len(TERMS)))
    )
    (figures_dir / "terminology_evolution.html").write_text(page, encoding="utf-8")
    return {
        "titles": len(active),
        "matches": len(index),
        "dated_titles": sum(denominators["all", d] for d in periods),
    }
