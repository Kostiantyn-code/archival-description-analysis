from __future__ import annotations

import csv
import re
import statistics
import sys
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


BASE_DIR = Path(__file__).resolve().parent
SCRIPT_VERSION = "0.5-draft"
INPUT_FILE = BASE_DIR / "input.xlsx"
DICTIONARIES_DIR = BASE_DIR / "dictionaries"
REPORTS_DIR = BASE_DIR / "reports"
FIGURES_DIR = BASE_DIR / "figures"
WORK_DIR = BASE_DIR / "work"

SHEET_NAMES = ("Опис 1", "Опис 2", "Опис 3", "Опис 4")
MIN_ALLOWED_YEAR = 1790
MAX_ALLOWED_YEAR = 1911


def load_dependencies():
    missing: list[str] = []
    try:
        import openpyxl
    except ImportError:
        openpyxl = None
        missing.append("openpyxl")
    try:
        import yaml
    except ImportError:
        yaml = None
        missing.append("pyyaml")

    if missing:
        print("Не встановлено обов'язкові бібліотеки:")
        print("  " + ", ".join(missing))
        print("\nВстановіть їх у терміналі PyCharm:")
        print(f'  "{sys.executable}" -m pip install ' + " ".join(missing))
        raise SystemExit(1)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        plt = None
    return openpyxl, yaml, plt


@dataclass
class Issue:
    level: str
    row: int | None
    case_id: str
    field: str
    value: str
    message: str
    sheet_name: str = ""


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


WORD_RE = re.compile(
    r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґЁё]+(?:[-'][0-9A-Za-zА-Яа-яІіЇїЄєҐґЁё]+)*"
)
YEAR_HEADING_RE = re.compile(
    r"^\s*"
    r"((?:17|18|19|20)\d{2}"
    r"(?:\s*(?:,|;|/|-|і|та)\s*(?:17|18|19|20)\d{2})*)"
    r"\s*(?:рік|роки|років|рр?)\.?\s*$",
    re.I,
)
YEAR_RE = re.compile(r"(?<!\d)((?:17|18|19|20)\d{2})(?!\d)")
LONG_NUMBER_RE = re.compile(r"(?<!\d)\d{5,}(?!\d)")
WITHDRAWN_RE = re.compile(
    r"^в\s*и\s*б\s*у\s*л\s*[аио](?=$|[\s.,;:—-])",
    re.I,
)

STEM_ENDINGS = sorted(
    {
        "остями", "істями", "остях", "істях", "остям", "істям",
        "остей", "істей", "ості", "істю", "ість",
        "ими", "іми", "ами", "ями",
        "ього", "ьому", "ого", "ому",
        "ій", "ої", "ьої", "ою", "ею", "єю",
        "ів", "їв", "ев", "ов", "ам", "ям", "ах", "ях",
        "ий", "им", "их", "іх", "ом", "ем",
        "а", "я", "у", "ю", "и", "і", "ї", "е", "о",
    },
    key=len,
    reverse=True,
)


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_text(text: str) -> str:
    return (
        text.lower()
        .replace("’", "'")
        .replace(chr(96), "'")
        .replace("ʼ", "'")
        .replace("–", "-")
        .replace("—", "-")
        .replace("\u00a0", " ")
    )


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    # У джерелі складні слова інколи набрано з пробілами біля дефіса:
    # «військово- морський». Для зіставлення це те саме складне слово.
    normalized = re.sub(
        r"(?<=[A-Za-zА-Яа-яІіЇїЄєҐґЁё])\s*-\s*"
        r"(?=[A-Za-zА-Яа-яІіЇїЄєҐґЁё])",
        "-",
        normalized,
    )
    return WORD_RE.findall(normalized)


@lru_cache(maxsize=100_000)
def light_stem_word(word: str) -> str:
    word = normalize_text(word)
    if "-" in word:
        return "-".join(light_stem_word(part) for part in word.split("-") if part)
    if "'" in word:
        return "'".join(light_stem_word(part) for part in word.split("'") if part)
    if word.isdigit() or len(word) <= 3:
        return word
    for ending in STEM_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            word = word[:-len(ending)]
            break
    if word.endswith("ь") and len(word) > 3:
        word = word[:-1]
    irregular = {
        "купець": "купц",
        "купец": "купц",
        "купц": "купц",
        "купцеві": "купц",
        "купцев": "купц",
        "учень": "учн",
        "учен": "учн",
        "учн": "учн",
        "будинок": "будинк",
        "осіб": "особ",
        "особи": "особ",
        "ділянок": "ділянк",
        "набор": "набір",
        "рок": "рік",
        "шпитал": "шпиталь",
        "суден": "судн",
        "недоїмок": "недоїмк",
        "угідь": "угідд",
        "угід": "угідд",
        "платеж": "платіж",
        "крадіжок": "крадіжк",
        "грабеж": "грабіж",
        "міщанин": "міщан",
        "міщан": "міщан",
        "дворянин": "дворян",
        "дворян": "дворян",
        "селянин": "селян",
        "селян": "селян",
        "громадянин": "громадян",
        "громадян": "громадян",
        "протоієрей": "протоієр",
        "протоієре": "протоієр",
        "священник": "священик",
        "священик": "священик",
        "правлінн": "правлін",
        "правлін": "правлін",
        "присутствіє": "присутств",
        "присутстві": "присутств",
        "присутствієм": "присутств",
        "виданн": "видан",
        "видан": "видан",
        "вчинен": "вчиненн",
        "нанесен": "нанесенн",
        "церк": "церкв",
        "режим": "реж",
        "позов": "поз",
        "друкарен": "друкарн",
        "видавец": "видавц",
        "шкіл": "школ",
        "збор": "збір",
        "звод": "звід",
        "купален": "купальн",
        "молебн": "молебен",
        "гулян": "гулянн",
        "ярмарок": "ярмарк",
        "водосток": "водостік",
        "укріплен": "укріпленн",
    }
    return irregular.get(word, word)


def stem_tokens(text: str) -> list[str]:
    return [light_stem_word(word) for word in tokenize(text)]


@lru_cache(maxsize=None)
def item_tokens(item: str) -> list[str]:
    return stem_tokens(item)


def find_phrase_positions(tokens: list[str], phrase: list[str]) -> list[int]:
    if not phrase or len(phrase) > len(tokens):
        return []
    positions: list[int] = []
    width = len(phrase)
    for index in range(len(tokens) - width + 1):
        if tokens[index:index + width] == phrase:
            positions.append(index)
    return positions


def contains_item(tokens: list[str], item: str) -> bool:
    wanted = item_tokens(item)
    if not wanted:
        return False
    if len(wanted) == 1:
        return any(
            wanted[0] == token or wanted[0] in token.split("-")
            for token in tokens
        )
    return bool(find_phrase_positions(tokens, wanted))


def mask_item(tokens: list[str], item: str) -> list[str]:
    phrase = item_tokens(item)
    if not phrase:
        return tokens
    result = list(tokens)
    if len(phrase) == 1:
        for index, token in enumerate(result):
            if phrase[0] == token or phrase[0] in token.split("-"):
                result[index] = "__masked__"
        return result
    for start in find_phrase_positions(result, phrase):
        for index in range(start, start + len(phrase)):
            result[index] = "__masked__"
    return result


def normalize_case_id(value: str) -> str:
    result = normalize_text(value)
    result = re.sub(r'["“”«»]', "", result)
    result = re.sub(r"\s+", "", result)
    result = re.sub(r"-+", "-", result)
    return result


def safe_load_yaml(path: Path, yaml_module) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml_module.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"Корінь YAML-файла має бути словником: {path}")
    return data


def ensure_directories() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)


def load_dictionaries(yaml_module):
    index_path = DICTIONARIES_DIR / "categories.yaml"
    if not index_path.exists():
        raise FileNotFoundError(
            f"Не знайдено {index_path}. Папка dictionaries має лежати поруч зі скриптом."
        )

    index = safe_load_yaml(index_path, yaml_module)
    categories: list[Category] = []
    for item in index.get("categories", []):
        category_path = DICTIONARIES_DIR / item["file"]
        data = safe_load_yaml(category_path, yaml_module)
        categories.append(
            Category(
                id=data["id"],
                label=data["label"],
                macroblock=data["macroblock"],
                minimum_score=int(
                    data.get(
                        "minimum_score",
                        index.get("classification", {}).get("minimum_score", 3),
                    )
                ),
                strong_phrases=list(data.get("strong_phrases", [])),
                strong_terms=list(data.get("strong_terms", [])),
                context_only_phrases=list(
                    data.get("context_only_phrases", [])
                ),
                context_only_terms=list(data.get("context_only_terms", [])),
                contextual_terms=list(data.get("contextual_terms", [])),
                context_rules=list(data.get("context_rules", [])),
                exclude_phrases=list(data.get("exclude_phrases", [])),
                review_terms=list(data.get("review_terms", [])),
            )
        )
    if not categories:
        raise ValueError("У categories.yaml немає тематичних категорій.")

    ambiguity_path = DICTIONARIES_DIR / "auxiliary" / "ambiguities.yaml"
    ambiguities = (
        safe_load_yaml(ambiguity_path, yaml_module).get("rules", [])
        if ambiguity_path.exists()
        else []
    )

    stopwords_path = DICTIONARIES_DIR / "auxiliary" / "stopwords.yaml"
    stopword_data = (
        safe_load_yaml(stopwords_path, yaml_module)
        if stopwords_path.exists()
        else {}
    )
    stopwords: set[str] = set()
    for key in ("general", "document_genres", "corpus_specific"):
        for value in stopword_data.get(key, []):
            stopwords.update(stem_tokens(str(value)))

    macroblocks = {
        key: value.get("label", key)
        for key, value in index.get("macroblocks", {}).items()
    }
    dictionary_version = str(index.get("dictionary_version", "невідома"))
    return categories, ambiguities, stopwords, macroblocks, dictionary_version


def detect_status(
    case_id: str,
    title: str,
    dates: str = "",
    pages: str = "",
    notes: str = "",
) -> str:
    title_normalized = normalize_text(title).strip()
    if YEAR_HEADING_RE.match(title_normalized) and not case_id:
        return "year_heading"
    # У частині описів службову позначку надруковано з міжлітерними
    # пробілами: «В И Б У Л А», «В И Б У Л И», «В И Б У Л О».
    if WITHDRAWN_RE.match(title_normalized):
        return "withdrawn"
    if title_normalized.startswith("архівний опис"):
        return "inventory"
    if case_id and title:
        return "case"
    # Загальні заголовки груп справ можуть не мати номера.
    # Якщо інші облікові поля такого рядка порожні, це не помилка.
    if title and not case_id and not any((dates, pages, notes)):
        return "group_heading"
    if case_id or title:
        return "unknown"
    return "empty"


def parse_years(
    dates_raw: str,
    row: int,
    case_id: str,
    issues: list[Issue],
    sheet_name: str,
) -> tuple[int | None, int | None]:
    if not dates_raw:
        issues.append(
            Issue(
                "WARNING", row, case_id, "Крайні дати", "",
                "Для справи не зазначено крайні дати.",
                sheet_name,
            )
        )
        return None, None

    long_numbers = LONG_NUMBER_RE.findall(dates_raw)
    if long_numbers:
        issues.append(
            Issue(
                "ERROR", row, case_id, "Крайні дати", dates_raw,
                "Виявлено число з п'ятьма або більше цифрами: "
                + ", ".join(long_numbers),
                sheet_name,
            )
        )

    years = [int(value) for value in YEAR_RE.findall(dates_raw)]
    if not years:
        issues.append(
            Issue(
                "WARNING", row, case_id, "Крайні дати", dates_raw,
                "Не вдалося розпізнати чотиризначний рік.",
                sheet_name,
            )
        )
        return None, None

    for year in sorted(set(years)):
        if year < MIN_ALLOWED_YEAR or year > MAX_ALLOWED_YEAR:
            issues.append(
                Issue(
                    "WARNING", row, case_id, "Крайні дати", dates_raw,
                    f"Рік {year} виходить за контрольні межі "
                    f"{MIN_ALLOWED_YEAR}–{MAX_ALLOWED_YEAR}.",
                    sheet_name,
                )
            )

    start_year = years[0]
    end_year = years[-1]
    if end_year < start_year:
        issues.append(
            Issue(
                "ERROR", row, case_id, "Крайні дати", dates_raw,
                f"Кінцевий рік {end_year} менший за початковий {start_year}.",
                sheet_name,
            )
        )
    return start_year, end_year


def parse_pages(
    pages_raw: str,
    row: int,
    case_id: str,
    issues: list[Issue],
    sheet_name: str,
) -> int | None:
    if not pages_raw:
        issues.append(
            Issue(
                "WARNING", row, case_id, "Кількість аркушів", "",
                "Не зазначено кількість аркушів.",
                sheet_name,
            )
        )
        return None

    compact = re.sub(r"\s+", "", pages_raw)
    if re.fullmatch(r"\d+", compact):
        pages = int(compact)
        if pages <= 0:
            issues.append(
                Issue(
                    "WARNING", row, case_id, "Кількість аркушів", pages_raw,
                    "Кількість аркушів має бути більшою за нуль.",
                    sheet_name,
                )
            )
            return None
        return pages

    numbers = re.findall(r"\d+", compact)
    if len(numbers) == 1:
        issues.append(
            Issue(
                "WARNING", row, case_id, "Кількість аркушів", pages_raw,
                "Нетипове оформлення; використано знайдене числове значення.",
                sheet_name,
            )
        )
        return int(numbers[0])

    issues.append(
        Issue(
            "WARNING", row, case_id, "Кількість аркушів", pages_raw,
            "Не вдалося однозначно визначити кількість аркушів.",
            sheet_name,
        )
    )
    return None


def read_records(
    openpyxl_module,
) -> tuple[list[Record], list[Issue], dict[str, list[str]]]:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Не знайдено {INPUT_FILE}. Покладіть input.xlsx поруч зі скриптом."
        )

    workbook = openpyxl_module.load_workbook(
        INPUT_FILE,
        read_only=True,
        data_only=True,
    )
    available_sheets = [name for name in SHEET_NAMES if name in workbook.sheetnames]
    if not available_sheets:
        available = ", ".join(workbook.sheetnames)
        raise KeyError(
            "У книзі немає жодного з очікуваних аркушів "
            f"{', '.join(SHEET_NAMES)}. Доступні аркуші: {available}"
        )

    issues: list[Issue] = []
    records: list[Record] = []
    expected_headers = [
        "№", "заголовок", "крайні дати", "кількість аркушів", "примітки"
    ]
    headers_by_sheet: dict[str, list[str]] = {}

    for missing_sheet in (name for name in SHEET_NAMES if name not in workbook.sheetnames):
        issues.append(
            Issue(
                "WARNING", None, "", "Аркуш", missing_sheet,
                "Очікуваний аркуш відсутній у книзі.",
                missing_sheet,
            )
        )

    for sheet_name in available_sheets:
        worksheet = workbook[sheet_name]
        current_section_year: int | None = None
        actual_headers = [
            normalize_text(clean_cell(cell.value))
            for cell in next(
                worksheet.iter_rows(min_row=1, max_row=1, max_col=5)
            )
        ]
        headers_by_sheet[sheet_name] = actual_headers

        for column, expected in enumerate(expected_headers, start=1):
            if expected not in actual_headers[column - 1]:
                issues.append(
                    Issue(
                        "WARNING", 1, "", f"Колонка {column}",
                        actual_headers[column - 1],
                        f"Заголовок колонки не містить очікуваний текст «{expected}».",
                        sheet_name,
                    )
                )

        for excel_row, values in enumerate(
            worksheet.iter_rows(min_row=2, max_col=5, values_only=True),
            start=2,
        ):
            case_id_raw, title_raw, dates_raw, pages_raw, notes_raw = [
                clean_cell(value) for value in values
            ]
            status = detect_status(
                case_id_raw, title_raw, dates_raw, pages_raw, notes_raw
            )
            if status == "empty":
                continue
            if status == "year_heading":
                heading_years = [
                    int(year) for year in YEAR_RE.findall(normalize_text(title_raw))
                ]
                current_section_year = (
                    heading_years[0] if len(heading_years) == 1 else None
                )

            record = Record(
                excel_row=excel_row,
                sheet_name=sheet_name,
                case_id_raw=case_id_raw,
                case_id_normalized=normalize_case_id(case_id_raw),
                title_raw=title_raw,
                dates_raw=dates_raw,
                pages_raw=pages_raw,
                notes_raw=notes_raw,
                status=status,
                section_year=current_section_year,
            )

            if status == "case":
                record.start_year, record.end_year = parse_years(
                    dates_raw, excel_row, case_id_raw, issues, sheet_name
                )
                record.pages = parse_pages(
                    pages_raw, excel_row, case_id_raw, issues, sheet_name
                )
            elif status == "unknown":
                joined = " | ".join(
                    value for value in (
                        case_id_raw, title_raw, dates_raw, pages_raw, notes_raw
                    ) if value
                )
                issues.append(
                    Issue(
                        "ERROR", excel_row, case_id_raw, "Структура рядка", joined,
                        "Рядок не вдалося віднести до відомого типу.",
                        sheet_name,
                    )
                )
            records.append(record)

    workbook.close()

    occurrences: dict[tuple[str, str], list[Record]] = defaultdict(list)
    for record in records:
        if record.case_id_normalized and record.status in {"case", "withdrawn"}:
            key = (record.sheet_name, record.case_id_normalized)
            occurrences[key].append(record)

    for (sheet_name, normalized_id), duplicated in occurrences.items():
        if len(duplicated) <= 1:
            continue
        rows = ", ".join(str(record.excel_row) for record in duplicated)
        titles = " || ".join(
            f"рядок {record.excel_row}: {record.title_raw}"
            for record in duplicated
        )
        issues.append(
            Issue(
                "WARNING", duplicated[0].excel_row, duplicated[0].case_id_raw,
                "Номер справи", normalized_id,
                f"Номер повторюється у рядках {rows}. {titles}",
                sheet_name,
            )
        )

    return records, issues, headers_by_sheet


def global_masks_for_category(
    tokens: list[str],
    category_id: str,
    ambiguities: list[dict[str, Any]],
) -> list[str]:
    result = list(tokens)
    for rule in ambiguities:
        term = str(rule.get("term", ""))
        if category_id in rule.get("do_not_assign", []):
            result = mask_item(result, term)
        key = f"exclude_for_{category_id}"
        for phrase in rule.get(key, []):
            result = mask_item(result, str(phrase))
    return result


def check_context_rule(tokens: list[str], rule: dict[str, Any]) -> bool:
    all_items = [str(value) for value in rule.get("all", [])]
    any_items = [str(value) for value in rule.get("any", [])]
    if all_items and not all(contains_item(tokens, item) for item in all_items):
        return False
    if any_items and not any(contains_item(tokens, item) for item in any_items):
        return False
    return bool(all_items or any_items)


def classify_title(
    title: str,
    categories: list[Category],
    ambiguities: list[dict[str, Any]],
    macroblock_order: list[str],
):
    original_tokens = stem_tokens(title)
    matched_ids: list[str] = []
    matched_labels: list[str] = []
    scores: dict[str, int] = {}
    evidence: dict[str, list[str]] = {}
    context_ids: list[str] = []
    context_labels: list[str] = []
    context_evidence: dict[str, list[str]] = {}
    review_flags: set[str] = set()

    for category in categories:
        tokens = global_masks_for_category(original_tokens, category.id, ambiguities)
        for phrase in category.exclude_phrases:
            tokens = mask_item(tokens, phrase)

        category_context_evidence: list[str] = []
        for phrase in category.context_only_phrases:
            if contains_item(tokens, phrase):
                category_context_evidence.append(f"фраза: {phrase}")
        for term in category.context_only_terms:
            if contains_item(tokens, term):
                category_context_evidence.append(f"термін: {term}")
        for term in category.contextual_terms:
            if contains_item(tokens, term):
                category_context_evidence.append(f"слабкий контекст: {term}")
        if category_context_evidence:
            context_ids.append(category.id)
            context_labels.append(category.label)
            context_evidence[category.id] = category_context_evidence

        score = 0
        category_evidence: list[str] = []
        for phrase in category.strong_phrases:
            if contains_item(tokens, phrase):
                score += 4
                category_evidence.append(f"фраза: {phrase}")
        for term in category.strong_terms:
            if contains_item(tokens, term):
                score += 3
                category_evidence.append(f"термін: {term}")
        for term in category.contextual_terms:
            if contains_item(tokens, term):
                score += 1
                category_evidence.append(f"контекст: {term}")
        for rule in category.context_rules:
            if check_context_rule(tokens, rule):
                score += int(rule.get("score", 3))
                readable = " + ".join(
                    [str(value) for value in rule.get("all", [])]
                    + [str(value) for value in rule.get("any", [])]
                )
                category_evidence.append(f"правило: {readable}")

        for ambiguity in ambiguities:
            term = str(ambiguity.get("term", ""))
            category_context = ambiguity.get("conditional", {}).get(category.id, [])
            if (
                term
                and category_context
                and contains_item(tokens, term)
                and any(
                    contains_item(tokens, str(context))
                    for context in category_context
                )
            ):
                score += 3
                category_evidence.append(
                    f"контекст неоднозначного терміна: {term}"
                )

        if score >= category.minimum_score:
            matched_ids.append(category.id)
            matched_labels.append(category.label)
            scores[category.id] = score
            evidence[category.id] = category_evidence
        elif score >= max(1, category.minimum_score - 1):
            for review_term in category.review_terms:
                if contains_item(tokens, review_term):
                    review_flags.add(f"{category.id}: {review_term}")

    ordered = sorted(
        zip(matched_ids, matched_labels),
        key=lambda pair: (-scores[pair[0]], pair[1]),
    )
    matched_ids = [pair[0] for pair in ordered]
    matched_labels = [pair[1] for pair in ordered]
    category_by_id = {category.id: category for category in categories}
    found_macroblocks = {
        category_by_id[category_id].macroblock for category_id in matched_ids
    }
    macroblocks = [
        macroblock for macroblock in macroblock_order
        if macroblock in found_macroblocks
    ]
    return (
        matched_ids, matched_labels, macroblocks,
        scores, evidence, context_ids, context_labels,
        context_evidence, sorted(review_flags)
    )


def classify_records(
    records: list[Record],
    categories: list[Category],
    ambiguities: list[dict[str, Any]],
    macroblock_order: list[str],
) -> None:
    active_records = [record for record in records if record.status == "case"]
    total = len(active_records)
    if total == 0:
        print("   Немає справ для тематичної класифікації.")
        return

    started_at = time.perf_counter()
    update_every = max(1, total // 100)
    print_classification_progress(0, total, started_at)

    for processed, record in enumerate(active_records, start=1):
        (
            record.categories,
            record.category_labels,
            record.macroblocks,
            record.scores,
            record.evidence,
            record.context_categories,
            record.context_category_labels,
            record.context_evidence,
            record.review_flags,
        ) = classify_title(
            record.title_raw, categories, ambiguities, macroblock_order
        )
        if processed % update_every == 0 or processed == total:
            print_classification_progress(
                processed, total, started_at, finished=processed == total
            )


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_count(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def print_classification_progress(
    processed: int,
    total: int,
    started_at: float,
    finished: bool = False,
) -> None:
    elapsed = time.perf_counter() - started_at
    fraction = processed / total if total else 1.0
    bar_width = 28
    filled = min(bar_width, int(bar_width * fraction))
    bar = "█" * filled + "·" * (bar_width - filled)

    details = (
        f"   [{bar}] {fraction * 100:6.2f}% | "
        f"{format_count(processed)}/{format_count(total)} | "
        f"час {format_duration(elapsed)}"
    )
    if processed:
        remaining = elapsed / processed * (total - processed)
        if finished:
            details += " | завершено"
        else:
            details += f" | залишилося ~{format_duration(remaining)}"

    print("\r" + details.ljust(115), end="\n" if finished else "", flush=True)


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=fieldnames, delimiter=";", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def record_to_row(record: Record) -> dict[str, Any]:
    evidence_text = " | ".join(
        f"{category_id}: {', '.join(values)}"
        for category_id, values in record.evidence.items()
    )
    scores_text = " | ".join(
        f"{category_id}={score}" for category_id, score in record.scores.items()
    )
    context_evidence_text = " | ".join(
        f"{category_id}: {', '.join(values)}"
        for category_id, values in record.context_evidence.items()
    )
    return {
        "sheet_name": record.sheet_name,
        "excel_row": record.excel_row,
        "case_id_raw": record.case_id_raw,
        "case_id_normalized": record.case_id_normalized,
        "status": record.status,
        "section_year": record.section_year or "",
        "start_year": record.start_year or "",
        "end_year": record.end_year or "",
        "pages": record.pages or "",
        "title_raw": record.title_raw,
        "dates_raw": record.dates_raw,
        "pages_raw": record.pages_raw,
        "notes_raw": record.notes_raw,
        "category_ids": " | ".join(record.categories),
        "category_labels": " | ".join(record.category_labels),
        "macroblocks": " | ".join(record.macroblocks),
        "scores": scores_text,
        "evidence": evidence_text,
        "context_category_ids": " | ".join(record.context_categories),
        "context_category_labels": " | ".join(
            record.context_category_labels
        ),
        "context_evidence": context_evidence_text,
        "review_flags": " | ".join(record.review_flags),
    }


def get_decade(record: Record) -> int | None:
    year = record.start_year or record.section_year
    return year // 10 * 10 if year is not None else None


def create_service_tables(records: list[Record], categories: list[Category]):
    record_fields = [
        "sheet_name", "excel_row", "case_id_raw", "case_id_normalized", "status",
        "section_year", "start_year", "end_year", "pages",
        "title_raw", "dates_raw", "pages_raw", "notes_raw",
        "category_ids", "category_labels", "macroblocks",
        "scores", "evidence", "context_category_ids",
        "context_category_labels", "context_evidence", "review_flags",
    ]
    write_csv(
        WORK_DIR / "records.csv", record_fields,
        (record_to_row(record) for record in records)
    )

    active = [record for record in records if record.status == "case"]
    topic_unclassified = [record for record in active if not record.categories]
    context_only = [
        record for record in topic_unclassified if record.context_categories
    ]
    unclassified = [
        record for record in topic_unclassified
        if not record.context_categories
    ]
    needs_review = [record for record in active if record.review_flags]
    context_mentions = [record for record in active if record.context_categories]
    write_csv(
        WORK_DIR / "unclassified_cases.csv", record_fields,
        (record_to_row(record) for record in unclassified)
    )
    write_csv(
        WORK_DIR / "context_only_cases.csv", record_fields,
        (record_to_row(record) for record in context_only)
    )
    write_csv(
        WORK_DIR / "needs_review.csv", record_fields,
        (record_to_row(record) for record in needs_review)
    )
    write_csv(
        WORK_DIR / "context_mentions.csv", record_fields,
        (record_to_row(record) for record in context_mentions)
    )

    category_counts = Counter(
        category_id for record in active for category_id in record.categories
    )
    category_by_id = {category.id: category for category in categories}
    write_csv(
        WORK_DIR / "category_counts.csv",
        [
            "category_id", "category_label", "macroblock", "cases",
            "percent_of_analyzed_titles",
        ],
        (
            {
                "category_id": category.id,
                "category_label": category.label,
                "macroblock": category.macroblock,
                "cases": category_counts[category.id],
                "percent_of_analyzed_titles": (
                    f"{category_counts[category.id] / len(active) * 100:.2f}"
                    if active else "0.00"
                ),
            }
            for category in categories
        ),
    )

    context_counts = Counter(
        category_id
        for record in active
        for category_id in record.context_categories
    )
    write_csv(
        WORK_DIR / "context_category_counts.csv",
        [
            "category_id", "category_label", "cases",
            "percent_of_analyzed_titles",
        ],
        (
            {
                "category_id": category.id,
                "category_label": category.label,
                "cases": context_counts[category.id],
                "percent_of_analyzed_titles": (
                    f"{context_counts[category.id] / len(active) * 100:.2f}"
                    if active else "0.00"
                ),
            }
            for category in categories
        ),
    )

    decade_counts = Counter(
        decade for record in active
        if (decade := get_decade(record)) is not None
    )
    write_csv(
        WORK_DIR / "cases_by_decade.csv",
        ["decade", "cases"],
        (
            {"decade": f"{decade}–{decade + 9}", "cases": count}
            for decade, count in sorted(decade_counts.items())
        ),
    )

    theme_decades: dict[str, Counter[int]] = defaultdict(Counter)
    for record in active:
        decade = get_decade(record)
        if decade is None:
            continue
        for category_id in record.categories:
            theme_decades[category_id][decade] += 1

    theme_rows: list[dict[str, Any]] = []
    for category_id, counts in theme_decades.items():
        for decade, count in sorted(counts.items()):
            theme_rows.append(
                {
                    "category_id": category_id,
                    "category_label": category_by_id[category_id].label,
                    "decade": f"{decade}–{decade + 9}",
                    "cases": count,
                }
            )
    write_csv(
        WORK_DIR / "themes_by_decade.csv",
        ["category_id", "category_label", "decade", "cases"],
        theme_rows,
    )
    return {
        "active": active,
        "topic_unclassified": topic_unclassified,
        "context_only": context_only,
        "unclassified": unclassified,
        "needs_review": needs_review,
        "context_mentions": context_mentions,
        "category_counts": category_counts,
        "context_counts": context_counts,
        "decade_counts": decade_counts,
        "theme_decades": theme_decades,
    }


def one_line(value: str, limit: int = 500) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[:limit - 1] + "…"


def write_error_log(issues: list[Issue], records: list[Record]) -> None:
    errors = [issue for issue in issues if issue.level == "ERROR"]
    warnings = [issue for issue in issues if issue.level == "WARNING"]
    statuses = Counter(record.status for record in records)
    lines = [
        "ПЕРЕВІРКА АРХІВНОГО ОПИСУ",
        f"Файл: {INPUT_FILE}",
        "Опрацьовані аркуші: "
        + ", ".join(sorted({record.sheet_name for record in records})),
        f"Дата запуску: {datetime.now():%d.%m.%Y %H:%M:%S}",
        "",
        "РЕЗЮМЕ",
        f"Справи, включені до аналізу: {statuses['case']}",
        f"Вибулі записи: {statuses['withdrawn']}",
        f"Структурні заголовки років: {statuses['year_heading']}",
        f"Загальні заголовки груп справ: {statuses['group_heading']}",
        f"Записи архівного опису: {statuses['inventory']}",
        f"Нерозпізнані рядки: {statuses['unknown']}",
        f"Помилки: {len(errors)}",
        f"Попередження: {len(warnings)}",
        "",
    ]

    number = 1
    for heading, group in (("ПОМИЛКИ", errors), ("ПОПЕРЕДЖЕННЯ", warnings)):
        lines.extend([heading, ""])
        if not group:
            lines.extend(["Не виявлено.", ""])
            continue
        for issue in group:
            location = []
            if issue.sheet_name:
                location.append(f"аркуш «{issue.sheet_name}»")
            if issue.row is not None:
                location.append(f"рядок {issue.row}")
            if issue.case_id:
                location.append(f"справа № {issue.case_id}")
            suffix = f" ({', '.join(location)})" if location else ""
            lines.append(f"{number}. {issue.message}{suffix}")
            if issue.field:
                lines.append(f"   Поле: {issue.field}")
            if issue.value:
                lines.append(f"   Значення: {one_line(issue.value)}")
            lines.append("")
            number += 1

    (REPORTS_DIR / "error.log").write_text(
        "\n".join(lines), encoding="utf-8-sig"
    )


def write_analysis_report(
    records: list[Record],
    issues: list[Issue],
    categories: list[Category],
    macroblock_labels: dict[str, str],
    table_data: dict[str, Any],
    figures_created: bool,
    dictionary_version: str,
) -> None:
    active = table_data["active"]
    unclassified = table_data["unclassified"]
    context_only = table_data["context_only"]
    needs_review = table_data["needs_review"]
    context_mentions = table_data["context_mentions"]
    category_counts = table_data["category_counts"]
    status_counts = Counter(record.status for record in records)
    classified = [record for record in active if record.categories]
    multilabel = [record for record in active if len(record.categories) > 1]
    years = [
        year for record in active
        for year in (record.start_year, record.end_year)
        if year is not None
    ]
    pages = [record.pages for record in active if record.pages is not None]
    error_count = sum(issue.level == "ERROR" for issue in issues)
    warning_count = sum(issue.level == "WARNING" for issue in issues)
    macroblock_counts = Counter(
        macroblock for record in active for macroblock in record.macroblocks
    )
    category_by_id = {category.id: category for category in categories}

    def percent(value: int, total: int) -> str:
        return f"{value / total * 100:.2f}%" if total else "0.00%"

    def format_int(value: int) -> str:
        return f"{value:,}".replace(",", " ")

    lines = [
        "# Результати тестового аналізу фонду 230",
        "",
        f"Дата запуску: {datetime.now():%d.%m.%Y %H:%M:%S}.",
        f"Версія скрипта: `{SCRIPT_VERSION}`. Версія словників: "
        f"`{dictionary_version}`.",
        "Опрацьовані аркуші: "
        + ", ".join(sorted({record.sheet_name for record in records})) + ".",
        "",
        "## Склад масиву",
        "",
        "| Показник | Значення |",
        "|---|---:|",
        f"| Заголовки справ, включені до аналізу | {format_int(len(active))} |",
        f"| Вибулі записи | {format_int(status_counts['withdrawn'])} |",
        f"| Заголовки років | {format_int(status_counts['year_heading'])} |",
        f"| Загальні заголовки груп справ | "
        f"{format_int(status_counts['group_heading'])} |",
        f"| Записи про архівний опис | {format_int(status_counts['inventory'])} |",
        f"| Нерозпізнані рядки | {format_int(status_counts['unknown'])} |",
        f"| Помилки | {format_int(error_count)} |",
        f"| Попередження | {format_int(warning_count)} |",
        "",
        "## Хронологічні й кількісні показники",
        "",
        f"- Розпізнаний діапазон років: "
        f"{min(years) if years else '—'}–{max(years) if years else '—'}.",
        f"- Справ із розпізнаною кількістю аркушів: {format_int(len(pages))}.",
        f"- Загальна кількість аркушів: {format_int(sum(pages))}.",
        (
            f"- Середня кількість аркушів: {statistics.mean(pages):.2f}."
            if pages else "- Середня кількість аркушів: —."
        ),
        (
            f"- Медіанна кількість аркушів: {statistics.median(pages):.2f}."
            if pages else "- Медіанна кількість аркушів: —."
        ),
        "",
        "## Покриття тематичною класифікацією",
        "",
        f"- Предметну тематику визначено: {format_int(len(classified))} "
        f"({percent(len(classified), len(active))}).",
        f"- Визначено лише контекст осіб або установ: "
        f"{format_int(len(context_only))} "
        f"({percent(len(context_only), len(active))}).",
        f"- Не визначено ні тему, ні контекст: {format_int(len(unclassified))} "
        f"({percent(len(unclassified), len(active))}).",
        f"- Належить до кількох категорій: {format_int(len(multilabel))} "
        f"({percent(len(multilabel), len(active))}).",
        f"- Позначено для контекстної перевірки: {format_int(len(needs_review))}.",
        f"- Виявлено окремі контекстні згадки осіб або установ: "
        f"{format_int(len(context_mentions))} "
        f"({percent(len(context_mentions), len(active))}).",
        "",
        "## Тематичні категорії",
        "",
        "| Категорія | Справ | Частка справ, включених до аналізу |",
        "|---|---:|---:|",
    ]
    for category_id, count in category_counts.most_common():
        lines.append(
            f"| {category_by_id[category_id].label} | "
            f"{format_int(count)} | {percent(count, len(active))} |"
        )

    lines.extend(
        [
            "",
            "Сума часток перевищує 100%, оскільки одна справа може належати "
            "до кількох категорій.",
            "",
            "## Макроблоки дисертації",
            "",
            "| Макроблок | Справ | Частка справ, включених до аналізу |",
            "|---|---:|---:|",
        ]
    )
    for macroblock, count in macroblock_counts.most_common():
        lines.append(
            f"| {macroblock_labels.get(macroblock, macroblock)} | "
            f"{format_int(count)} | {percent(count, len(active))} |"
        )

    lines.extend(
        [
            "",
            "## Створені матеріали",
            "",
            "- reports/error.log — перелік помилок і попереджень;",
            "- work/records.csv — усі розпізнані рядки;",
            "- work/unclassified_cases.csv — справи без тематичної категорії;",
            "- work/context_only_cases.csv — справи, для яких визначено лише "
            "контекст осіб або установ;",
            "- work/needs_review.csv — справи з неоднозначними термінами;",
            "- work/context_mentions.csv — згадки осіб та установ, які самі "
            "по собі не визначають тему;",
            "- work/category_counts.csv — кількість справ за категоріями;",
            "- work/context_category_counts.csv — кількість контекстних "
            "згадок за категоріями;",
            "- work/cases_by_decade.csv — хронологічний розподіл;",
            "- work/themes_by_decade.csv — динаміка тем за десятиліттями;",
        ]
    )
    if figures_created:
        lines.append("- figures/ — графіки у форматах PNG і SVG.")
    else:
        lines.extend(
            [
                "",
                "> Графіки не створено, оскільки бібліотеку matplotlib "
                "не встановлено. Решта аналізу виконана.",
            ]
        )
    lines.extend(
        [
            "",
            "## Методичне застереження",
            "",
            f"Це тестова класифікація за словниками версії {dictionary_version}. "
            "Тематичні категорії описують предмет справи; назви установ, "
            "посади та станові означення, які лише називають учасника або "
            "автора документа, винесено в окремі контекстні мітки. "
            "Перед використанням числових результатів у дисертації потрібно "
            "перевірити needs_review.csv та unclassified_cases.csv, "
            "після чого скоригувати словники.",
        ]
    )
    (REPORTS_DIR / "analysis_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def save_figure(plt, name: str) -> None:
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / f"{name}.png", dpi=220, bbox_inches="tight")
    plt.savefig(FIGURES_DIR / f"{name}.svg", bbox_inches="tight")
    plt.close()


def create_figures(plt, records, categories, table_data) -> bool:
    if plt is None:
        print(
            "Увага: matplotlib не встановлено, тому графіки пропущено.\n"
            f'Для графіків виконайте: "{sys.executable}" -m pip install matplotlib'
        )
        return False

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titlesize": 13,
            "axes.labelsize": 10,
            "figure.dpi": 120,
        }
    )
    active = table_data["active"]
    category_counts = table_data["category_counts"]
    decade_counts = table_data["decade_counts"]
    theme_decades = table_data["theme_decades"]
    category_by_id = {category.id: category for category in categories}

    decades = sorted(decade_counts)
    values = [decade_counts[decade] for decade in decades]
    plt.figure(figsize=(10, 5.6))
    bars = plt.bar(
        [f"{decade}–{decade + 9}" for decade in decades],
        values, color="#315f8c",
    )
    plt.title("Розподіл справ за десятиліттями")
    plt.xlabel("Десятиліття")
    plt.ylabel("Кількість справ")
    plt.xticks(rotation=45, ha="right")
    plt.bar_label(bars, padding=2, fontsize=8)
    plt.grid(axis="y", alpha=0.25)
    save_figure(plt, "cases_by_decade")

    ordered = category_counts.most_common()
    labels = [category_by_id[item[0]].label for item in ordered][::-1]
    counts = [item[1] for item in ordered][::-1]
    plt.figure(figsize=(10, 6.5))
    bars = plt.barh(labels, counts, color="#6a8f3d")
    plt.title("Тематична структура заголовків справ")
    plt.xlabel("Кількість справ")
    plt.bar_label(bars, padding=3, fontsize=8)
    plt.grid(axis="x", alpha=0.25)
    save_figure(plt, "thematic_categories")

    classified_count = sum(bool(record.categories) for record in active)
    context_only_count = sum(
        not record.categories and bool(record.context_categories)
        for record in active
    )
    unclassified_count = len(active) - classified_count - context_only_count
    plt.figure(figsize=(7, 4.8))
    bars = plt.bar(
        ["Предметну тему\nвизначено", "Лише контекст", "Не визначено"],
        [classified_count, context_only_count, unclassified_count],
        color=["#4472c4", "#70ad47", "#c55a11"],
    )
    plt.title("Покриття класифікаційними словниками")
    plt.ylabel("Кількість справ")
    plt.bar_label(bars, padding=3)
    plt.grid(axis="y", alpha=0.25)
    save_figure(plt, "classification_coverage")

    status_counts = Counter(record.status for record in records)
    plt.figure(figsize=(7, 4.8))
    bars = plt.bar(
        ["Включено до аналізу", "Вибулі"],
        [status_counts["case"], status_counts["withdrawn"]],
        color=["#2f6b55", "#9b4a4a"],
    )
    plt.title("Справи, включені до аналізу, та вибулі записи")
    plt.ylabel("Кількість записів")
    plt.bar_label(bars, padding=3)
    plt.grid(axis="y", alpha=0.25)
    save_figure(plt, "included_and_withdrawn")

    if decades and ordered:
        category_ids = [category_id for category_id, _ in ordered]
        matrix = [
            [theme_decades[category_id][decade] for decade in decades]
            for category_id in category_ids
        ]
        plt.figure(figsize=(11, 7))
        image = plt.imshow(matrix, aspect="auto", cmap="Blues")
        plt.colorbar(image, label="Кількість справ")
        plt.xticks(
            range(len(decades)),
            [f"{decade}–{str(decade + 9)[-2:]}" for decade in decades],
            rotation=45, ha="right",
        )
        plt.yticks(
            range(len(category_ids)),
            [category_by_id[category_id].label for category_id in category_ids],
        )
        plt.title("Динаміка тематичних категорій за десятиліттями")
        plt.xlabel("Десятиліття")
        save_figure(plt, "themes_by_decade")
    return True


def print_summary(records, issues, table_data, figures_created) -> None:
    statuses = Counter(record.status for record in records)
    errors = sum(issue.level == "ERROR" for issue in issues)
    warnings = sum(issue.level == "WARNING" for issue in issues)
    active = table_data["active"]
    classified = sum(bool(record.categories) for record in active)
    print("\nАНАЛІЗ ЗАВЕРШЕНО")
    print(f"Справи в аналізі:        {statuses['case']}")
    print(f"Вибулі записи:           {statuses['withdrawn']}")
    print(f"Предметну тему визначено:{classified:>7}")
    print(f"Лише контекст:           {len(table_data['context_only']):>7}")
    print(f"Не визначено:            {len(table_data['unclassified']):>7}")
    print(f"Потребують перегляду:    {len(table_data['needs_review'])}")
    print(f"Контекстні згадки:       {len(table_data['context_mentions'])}")
    print(f"Помилки:                 {errors}")
    print(f"Попередження:            {warnings}")
    print(f"Графіки створено:        {'так' if figures_created else 'ні'}")
    print("\nОсновні результати:")
    print(f"  {REPORTS_DIR / 'error.log'}")
    print(f"  {REPORTS_DIR / 'analysis_report.md'}")
    print(f"  {WORK_DIR / 'records.csv'}")
    if figures_created:
        print(f"  {FIGURES_DIR}")


def main() -> None:
    print(
        f"=== АНАЛІЗ АРХІВНОГО ОПИСУ ФОНДУ 230 "
        f"— {SCRIPT_VERSION} ==="
    )
    print(f"Папка скрипта: {BASE_DIR}")
    print(f"Вхідний файл:  {INPUT_FILE}")
    print(f"Аркуші:        {', '.join(SHEET_NAMES)}")

    openpyxl_module, yaml_module, plt = load_dependencies()
    ensure_directories()

    print("\n1. Завантаження класифікаційних словників...")
    (
        categories, ambiguities, stopwords, macroblock_labels,
        dictionary_version,
    ) = load_dictionaries(yaml_module)
    print(f"   Завантажено категорій: {len(categories)}")
    print(f"   Завантажено стоп-слів: {len(stopwords)}")

    print("2. Читання та перевірка input.xlsx...")
    records, issues, _headers = read_records(openpyxl_module)
    print(f"   Розпізнано рядків: {len(records)}")

    print("3. Тематична класифікація...")
    macroblock_order = list(macroblock_labels)
    classify_records(records, categories, ambiguities, macroblock_order)

    print("4. Створення службових таблиць...")
    table_data = create_service_tables(records, categories)

    print("5. Створення error.log...")
    write_error_log(issues, records)

    print("6. Створення графіків...")
    figures_created = create_figures(plt, records, categories, table_data)

    print("7. Створення аналітичного звіту...")
    write_analysis_report(
        records, issues, categories, macroblock_labels,
        table_data, figures_created, dictionary_version
    )
    print_summary(records, issues, table_data, figures_created)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print("\nКРИТИЧНА ПОМИЛКА")
        print(str(error))
        print("\nТехнічні подробиці:")
        traceback.print_exc()
        raise SystemExit(1)
