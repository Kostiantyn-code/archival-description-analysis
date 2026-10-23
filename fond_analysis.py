from __future__ import annotations

import hashlib
import json
import platform
from copy import copy
import re
import statistics
import sys
import time
import traceback
from io import BytesIO
from collections import Counter, defaultdict
from functools import lru_cache
from datetime import datetime
from pathlib import Path
from textwrap import fill
from typing import Any, Iterable


from models import Issue, Category, Record, CATEGORY_RULE_FIELDS
from mentions import (
    DOCUMENT_TYPES, DOCUMENT_TYPE_RULES_VERSION, match_document_types,
    RULES_VERSION as TERMINOLOGY_RULES_VERSION, write_terminology_report,
)
from geography import (
    GAZETTEER, find_places, load_places, unknown_candidates,
    write_maps as write_geography_maps,
)
from theme_links import write_theme_links
from html_report import write_html_report
from report_utils import write_csv
from localization import Visualization, Report, CATALOG as PRESENTATION_CATALOG
from language_packs import LanguageRegistry, REGISTRY as LANGUAGE_REGISTRY, evaluate_concepts, pack_content, lexical_patterns, structural_patterns, personal_section_matches
from text_matching import (
    MATCH_LANGUAGE,
    YEAR_HEADING_RE,
    YEAR_RE,
    LONG_NUMBER_RE,
    WITHDRAWN_RE,
    clean_cell,
    normalize_text,
    tokenize,
    stem_tokens,
    item_matcher,
    mask_item,
    normalize_case_id,
    detect_title_language,
    configure_matching_profiles,
)

BASE_DIR = Path(__file__).resolve().parent
SCRIPT_VERSION = "0.16-dev"
CONFIG_DIR = BASE_DIR / "config"
INPUT_DIR = BASE_DIR / "input"
INPUT_FILE = INPUT_DIR / "input.xlsx"
DICTIONARIES_DIR = BASE_DIR / "dictionaries"
OUTPUTS_DIR = BASE_DIR / "outputs"
RUN_DIR = OUTPUTS_DIR
REPORTS_DIR = RUN_DIR / "reports"
FIGURES_DIR = RUN_DIR / "figures"
WORK_DIR = RUN_DIR / "tables"
THEMATIC_DIR = RUN_DIR / "thematic_exports"

SHEET_NAMES: tuple[str, ...] = ()
SOURCE_CONFIG: dict[str, dict[str, Any]] = {}
HEADER_ROWS_BY_SHEET: dict[str, int] = {}
ANALYSIS_CONFIG: dict[str, Any] = {}
LANGUAGE_CATEGORIES: dict[str, list] = {}
LANGUAGE_AMBIGUITIES: dict[str, list] = {}
MIN_ALLOWED_YEAR = 1500
MAX_ALLOWED_YEAR = 2099
PERSONAL_SECTION_RE = re.compile(
    r"^(?:особов[іи]\s+справ[и]|особист[іи]\s+справ[и]|личн(?:ые|ое)\s+дел[ао]"
    r"|(?:список|списки)\s+(?:учнів|учениць|студентів|службовців|працівників|особового\s+складу)"
    r"|(?:список|списки)\s+(?:учеников|учениц|студентов|служащих|работников|личного\s+состава))\b",
    re.I,
)
LETTER_HEADING_RE = re.compile(r'^[«"“]?\s*[А-ЯЁІЇЄҐA-Z]\s*[»"”]?$', re.I)


def tr(source: str, *values: Any) -> str:
    return Report(Visualization.from_config(ANALYSIS_CONFIG)).text(source, *values)


@lru_cache(maxsize=1)
def analysis_languages() -> LanguageRegistry:
    registry = LanguageRegistry.load(LANGUAGE_REGISTRY)
    configure_matching_profiles({code: pack["matching"] for code, pack in registry.languages.items()},
                                {code: pack.get("detection_terms", []) for code, pack in registry.languages.items()})
    return registry


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
        print(tr('Missing required packages:'))
        print("  " + ", ".join(missing))
        print(tr('\nInstall them in your terminal:'))
        print(f'  "{sys.executable}" -m pip install ' + " ".join(missing))
        raise SystemExit(1)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        plt = None
    return openpyxl, yaml, plt


def configure_analysis(yaml_module) -> None:
    global ANALYSIS_CONFIG, INPUT_DIR, INPUT_FILE, OUTPUTS_DIR
    global MIN_ALLOWED_YEAR, MAX_ALLOWED_YEAR
    path = CONFIG_DIR / "analysis.yaml"
    config = safe_load_yaml(path, yaml_module)
    Visualization.from_config(config)  # Validate presentation settings before analysis.
    options = config.get("analysis", {})
    if not isinstance(options, dict):
        raise ValueError("analysis: expected a mapping")
    unknown_options = set(options) - {"language", "sheet_languages"}
    if unknown_options:
        raise ValueError("Unsupported analysis settings: " + ", ".join(sorted(unknown_options)))
    ANALYSIS_CONFIG = config
    analysis_languages.cache_clear()
    registry = analysis_languages()
    LANGUAGE_CATEGORIES.clear()
    LANGUAGE_AMBIGUITIES.clear()
    pack_content.cache_clear()
    lexical_patterns.cache_clear()
    structural_patterns.cache_clear()
    configured_language = options.get("language", "auto")
    if configured_language not in {"auto", *registry.languages}:
        raise ValueError(f"analysis.language: unknown language {configured_language}")
    overrides = options.get("sheet_languages", {})
    if not isinstance(overrides, dict) or any(not isinstance(key, str) or code not in registry.languages for key, code in overrides.items()):
        raise ValueError("analysis.sheet_languages: expected worksheet names mapped to registered language codes")

    input_name = str(config.get("input_dir", "input"))
    output_name = str(config.get("output_root", "outputs"))
    input_path = Path(input_name)
    output_path = Path(output_name)
    INPUT_DIR = input_path if input_path.is_absolute() else BASE_DIR / input_path
    INPUT_FILE = INPUT_DIR / "input.xlsx"
    OUTPUTS_DIR = output_path if output_path.is_absolute() else BASE_DIR / output_path

    chronology = config.get("chronology", {})
    MIN_ALLOWED_YEAR = int(chronology.get("minimum_year", 1500))
    MAX_ALLOWED_YEAR = int(chronology.get("maximum_year", 2099))
    if MIN_ALLOWED_YEAR > MAX_ALLOWED_YEAR:
        raise ValueError(tr('config/analysis.yaml: minimum_year exceeds maximum_year'))


def input_workbooks() -> list[Path]:
    """List real XLSX workbooks in stable order; ignore Excel lock files."""
    if not INPUT_DIR.is_dir():
        raise FileNotFoundError(tr('Folder not found: {0}. Create input/ and add XLSX workbooks.', INPUT_DIR))
    paths = sorted(
        (p for p in INPUT_DIR.iterdir()
         if p.is_file() and p.suffix.casefold() == ".xlsx"
         and not p.name.startswith("~$")),
        key=lambda p: (p.name.casefold(), p.name),
    )
    if not paths:
        raise FileNotFoundError(tr('In folder {0} no XLSX workbooks were found.', INPUT_DIR))
    return paths


def workbook_folder(path: Path, occupied: set[str]) -> str:
    """Readable, collision-safe folder name for a workbook's own reports."""
    stem = re.sub(r"[^\w-]+", "_", path.stem, flags=re.UNICODE).strip("_-")[:75]
    stem = stem or "book"
    candidate = stem
    suffix = 2
    while candidate.casefold() in occupied:
        candidate = f"{stem}_{suffix}"
        suffix += 1
    occupied.add(candidate.casefold())
    return candidate


def configure_workbook_sources(openpyxl_module) -> None:
    """Read the authoritative Archive/Fond/Inventory rows on every sheet."""
    global SOURCE_CONFIG, SHEET_NAMES, HEADER_ROWS_BY_SHEET
    analysis_languages()
    workbook = openpyxl_module.load_workbook(INPUT_FILE, read_only=True, data_only=True)
    try:
        sources = {}
        metadata_rows = {}
        source_keys = {}
        inventory_keys = set()
        for sheet in workbook:
            rows = list(sheet.iter_rows(min_row=1, max_row=4, max_col=5, values_only=True))
            if len(rows) < 4:
                raise ValueError(tr('{0}, {1}: three metadata rows and a header in row 4 are required', INPUT_FILE.name, sheet.title))
            fields = []
            for row_number, (label, aliases) in enumerate((("Archive", {"архів", "archive"}), ("Fonds", {"фонд", "fond", "fonds"}), ("Inventory", {"опис", "inventory"})), start=1):
                if normalize_text(clean_cell(rows[row_number - 1][0])) not in aliases:
                    raise ValueError(tr('{0}, {1}, A{2}: expected «{3}»', INPUT_FILE.name, sheet.title, row_number, label))
                value = clean_cell(rows[row_number - 1][1])
                if not value:
                    raise ValueError(tr('{0}, {1}, B{2}: enter a value for «{3}»', INPUT_FILE.name, sheet.title, row_number, label))
                fields.append(value)
            archive, fond, inventory = fields
            inventory_key = (archive.casefold(), fond.casefold(), inventory.casefold())
            if inventory_key in inventory_keys:
                raise ValueError(tr('{0}, {1}: this archive, fonds and inventory already occur on another worksheet', INPUT_FILE.name, sheet.title))
            inventory_keys.add(inventory_key)
            identifier_header = clean_cell(rows[3][0])
            if "№" not in identifier_header and identifier_header.casefold().rstrip('.') not in {"no", "number", "id", "#"}:
                raise ValueError(tr('{0}, {1}, A4: expected a number/ID header', INPUT_FILE.name, sheet.title))
            key = (archive.casefold(), fond.casefold())
            if key not in source_keys:
                safe_fond = re.sub(r"[^a-z0-9_-]+", "_", fond.casefold()).strip("_")
                safe_fond = safe_fond[:30] or "unnumbered"
                source_keys[key] = f"fond_{safe_fond}_{hashlib.sha1(archive.casefold().encode('utf-8')).hexdigest()[:6]}"
            language_counts = Counter()
            for row in sheet.iter_rows(min_row=5, max_row=104, min_col=2, max_col=2, values_only=True):
                title_language = detect_title_language(clean_cell(row[0]))
                if title_language not in {"undetermined", "mixed"}:
                    language_counts[title_language] += 2
                elif title_language == "undetermined":
                    tokens = tokenize(clean_cell(row[0]))
                    if any(token in {"дело", "переписка", "сведения", "об"} for token in tokens):
                        language_counts["ru"] += 1
                    elif any(token in {"справа", "відомості", "щодо"} for token in tokens):
                        language_counts["uk"] += 1
            language = "ru" if language_counts["ru"] > language_counts["uk"] else "uk"
            if not sum(language_counts.values()):
                sample = ' '.join(clean_cell(row[0]) for row in sheet.iter_rows(min_row=5, max_row=104, min_col=2, max_col=2, values_only=True))
                if re.search(r'[A-Za-zÀ-ž]', sample) and not re.search(r'[А-Яа-яІіЇїЄєҐґЁё]', sample):
                    language = "undetermined"
            latin = [(count, code) for code, count in language_counts.items() if code not in {"uk", "ru"}]
            if latin:
                best_count, best_language = max(latin)
                if best_count > max(language_counts["uk"], language_counts["ru"]):
                    language = best_language
            options = ANALYSIS_CONFIG.get("analysis", {})
            configured = options.get("sheet_languages", {}).get(sheet.title, options.get("language", "auto"))
            language_source = "sheet_inferred"
            if configured != "auto":
                language = configured
                language_source = "config_sheet" if sheet.title in options.get("sheet_languages", {}) else "config_default"
            declared = clean_cell(rows[0][4]).casefold() if clean_cell(rows[0][3]).casefold() == "language" else ""
            if declared:
                if not re.fullmatch(r"[a-z]{2,3}", declared):
                    raise ValueError(f"{INPUT_FILE.name}, {sheet.title}, E1: invalid language code")
                language = declared
                language_source = "sheet_declared"
            header = [normalize_text(clean_cell(value)) for value in rows[3]]
            sources[sheet.title] = {
                "source_id": source_keys[key], "archive": archive, "fond": fond,
                "inventory": inventory, "language": language,
                "language_source": language_source,
                "pages_expected": bool(header[3]),
                "skip_header_checks": [index for index, value in enumerate(header, 1)
                                       if (index in {4, 5} and not value) or
                                       (index == 2 and re.search(r"\bф\.\s*\d", value))],
            }
            metadata_rows[sheet.title] = 4
        if not sources:
            raise ValueError(tr('{0}: the workbook has no worksheets', INPUT_FILE.name))
        SOURCE_CONFIG = sources
        SHEET_NAMES = tuple(sources)
        HEADER_ROWS_BY_SHEET = metadata_rows
    finally:
        workbook.close()


def safe_load_yaml(path: Path, yaml_module) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = yaml_module.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError(tr('The YAML root must be a mapping: {0}', path))
    return data


def ensure_directories() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    THEMATIC_DIR.mkdir(parents=True, exist_ok=True)


def load_dictionaries(yaml_module, language="uk"):
    """Load one language against the common, editable category index."""
    index = safe_load_yaml(CONFIG_DIR / "categories.yaml", yaml_module)
    registry = analysis_languages()
    compiled, pack = registry.compile(language, index)
    blocks = {key: value['label'] for key, value in index['macroblocks'].items()}
    categories, ids, exports = [], set(), set()
    for item in index['categories']:
        cid = item['id']
        if not re.fullmatch(r'[a-z0-9_]+', cid) or cid in ids:
            raise ValueError(f'Invalid or duplicate category ID: {cid}')
        ids.add(cid)
        if not isinstance(item.get('enabled', True), bool):
            raise ValueError(f'{cid}: enabled must be true or false')
        if not item.get('enabled', True):
            continue
        if item['macroblock'] not in blocks:
            raise ValueError(f'{cid}: unknown macroblock')
        filename = item.get('export', f'{cid}.xlsx')
        if not re.fullmatch(r'[^<>:"/\\|?*]+\.xlsx', filename, re.I) or filename.casefold() in exports:
            raise ValueError(f'{cid}: invalid or duplicate export filename')
        exports.add(filename.casefold())
        rules = compiled[cid]
        categories.append(Category(
            id=cid, label=item['label'], macroblock=item['macroblock'],
            minimum_score=int(rules.get('minimum_score', index.get('classification', {}).get('minimum_score', 3))),
            **{key: list(rules.get(key, [])) for key in CATEGORY_RULE_FIELDS},
            export_filename=filename, concepts=rules.get('concepts', []),
            concept_rules=rules.get('concept_rules', []),
        ))
    if not categories:
        raise ValueError('Enable at least one category in config/categories.yaml')
    return categories, pack.get('ambiguities', []), blocks, pack['version']


def detect_status(
    case_id: str,
    title: str,
    dates: str = "",
    pages: str = "",
    notes: str = "",
    language: str = "uk",
) -> str:
    title_normalized = normalize_text(title).strip()
    if language not in {"uk", "ru"}:
        year_pattern, withdrawn_pattern = structural_patterns(language)
        if not case_id and year_pattern and year_pattern.fullmatch(title_normalized):
            return "year_heading"
        if withdrawn_pattern and withdrawn_pattern.match(title_normalized):
            return "withdrawn"
    if YEAR_HEADING_RE.match(title_normalized) and not case_id:
        return "year_heading"
    # Some finding aids space out the letters of the withdrawn-entry marker.
    if WITHDRAWN_RE.match(title_normalized):
        return "withdrawn"
    if re.match(
        r"^(?:(?:архівний опис|архивная опись|недействующая опись|недіючий опис)(?:\s|$|[.,])"
        r"|(?:опис|опись)\s*[№#]\s*\d+\s+(?:фонду|фонда)\b)",
        title_normalized,
    ):
        return "inventory"
    if case_id and title:
        return "case"
    # Unnumbered group headings are valid when their other data fields are empty.
    if title and not case_id and not any((dates, pages, notes)):
        return "group_heading"
    if case_id or title or dates or pages or notes:
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
                "WARNING", row, case_id, tr('Date range'), "",
                tr('No date range is provided for the file.'),
                sheet_name,
            )
        )
        return None, None

    long_numbers = LONG_NUMBER_RE.findall(dates_raw)
    if long_numbers:
        issues.append(
            Issue(
                "ERROR", row, case_id, tr('Date range'), dates_raw,
                tr('A number with five or more digits was found: ')
                + ", ".join(long_numbers),
                sheet_name,
            )
        )

    years = [int(value) for value in YEAR_RE.findall(dates_raw)]
    if not years:
        issues.append(
            Issue(
                "WARNING", row, case_id, tr('Date range'), dates_raw,
                tr('No four-digit year could be recognised.'),
                sheet_name,
            )
        )
        return None, None

    for year in sorted(set(years)):
        if year < MIN_ALLOWED_YEAR or year > MAX_ALLOWED_YEAR:
            issues.append(
                Issue(
                    "WARNING", row, case_id, tr('Date range'), dates_raw,
                    tr('Year {0} is outside the configured bounds {1}–{2}.', year, MIN_ALLOWED_YEAR, MAX_ALLOWED_YEAR),
                    sheet_name,
                )
            )

    start_year = years[0]
    end_year = years[-1]
    if end_year < start_year:
        issues.append(
            Issue(
                "ERROR", row, case_id, tr('Date range'), dates_raw,
                tr('End year {0} precedes start year {1}.', end_year, start_year),
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
                "WARNING", row, case_id, tr('Folio count'), "",
                tr('No folio count is provided.'),
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
                    "WARNING", row, case_id, tr('Folio count'), pages_raw,
                    tr('The folio count must be greater than zero.'),
                    sheet_name,
                )
            )
            return None
        return pages

    numbers = re.findall(r"\d+", compact)
    if len(numbers) == 1:
        issues.append(
            Issue(
                "WARNING", row, case_id, tr('Folio count'), pages_raw,
                tr('Unusual formatting; the detected numeric value was used.'),
                sheet_name,
            )
        )
        return int(numbers[0])

    issues.append(
        Issue(
            "WARNING", row, case_id, tr('Folio count'), pages_raw,
            tr('The folio count could not be determined unambiguously.'),
            sheet_name,
        )
    )
    return None


def read_records(
    openpyxl_module,
) -> tuple[list[Record], list[Issue], dict[str, list[str]]]:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            tr('File not found: {0}. Place an XLSX workbook in input/.', INPUT_FILE)
        )

    workbook = openpyxl_module.load_workbook(
        INPUT_FILE,
        read_only=True,
        data_only=True,
    )
    available_sheets = list(SHEET_NAMES)
    if set(available_sheets) != set(workbook.sheetnames):
        workbook.close()
        raise ValueError(tr('The worksheets changed after reading metadata; restart the analysis.'))

    issues: list[Issue] = []
    records: list[Record] = []
    expected_headers = [
        "№", "заголовок", "крайні дати", "кількість аркушів", "примітки"
    ]
    headers_by_sheet: dict[str, list[str]] = {}
    for sheet_name in available_sheets:
        worksheet = workbook[sheet_name]
        header_row = HEADER_ROWS_BY_SHEET[sheet_name]
        current_section_year: int | None = None
        actual_headers = [
            normalize_text(clean_cell(cell.value))
            for cell in next(
                worksheet.iter_rows(min_row=header_row, max_row=header_row, max_col=5)
            )
        ]
        headers_by_sheet[sheet_name] = actual_headers

        config = SOURCE_CONFIG.get(sheet_name, {})
        current_section_label = ""
        current_thematic_section = ""
        for column, expected in enumerate(expected_headers, start=1):
            if column in config.get("skip_header_checks", []):
                continue
            english_headers = {1: {"no", "no.", "number", "id", "#"}, 2: {"title", "file title", "description"}, 3: {"dates", "date range", "date"}, 4: {"pages", "folios", "folio count", "page count"}, 5: {"notes", "note"}}
            if expected not in actual_headers[column - 1] and actual_headers[column - 1] not in english_headers[column]:
                issues.append(
                    Issue(
                        "WARNING", header_row, "", tr('Column {0}', column),
                        actual_headers[column - 1],
                        tr('The column header does not contain the expected text “{0}”.', expected),
                        sheet_name,
                    )
                )

        for excel_row, values in enumerate(
            worksheet.iter_rows(min_row=header_row + 1, max_col=5, values_only=True),
            start=header_row + 1,
        ):
            case_id_raw, title_raw, dates_raw, pages_raw, notes_raw = [
                clean_cell(value) for value in values
            ]
            status = detect_status(
                case_id_raw, title_raw, dates_raw, pages_raw, notes_raw,
                config.get("language", "uk"),
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
                current_section_label = title_raw
            elif status == "group_heading":
                current_section_label = title_raw
                current_section_year = None
                if PERSONAL_SECTION_RE.match(title_raw) or personal_section_matches(title_raw, config.get("language", "uk")):
                    current_thematic_section = title_raw
                elif not LETTER_HEADING_RE.fullmatch(title_raw):
                    current_thematic_section = ""

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
                section_label=current_section_label,
                thematic_section=current_thematic_section,
                source_archive=config.get("archive", ""),
                source_fond=str(config.get("fond", "")),
                source_inventory=str(config.get("inventory", "")),
                source_id=config.get("source_id", sheet_name),
                language=config.get("language", "uk"),
                detected_language=detect_title_language(title_raw),
                language_source=config.get("language_source", "sheet_inferred"),
            )

            if status == "case":
                record.start_year, record.end_year = parse_years(
                    dates_raw, excel_row, case_id_raw, issues, sheet_name
                )
                record.pages = parse_pages(
                    pages_raw, excel_row, case_id_raw, issues, sheet_name
                ) if pages_raw or config.get("pages_expected", True) else None
            elif status == "unknown":
                joined = " | ".join(
                    value for value in (
                        case_id_raw, title_raw, dates_raw, pages_raw, notes_raw
                    ) if value
                )
                issues.append(
                    Issue(
                        "ERROR", excel_row, case_id_raw, tr('Row structure'), joined,
                        tr('The row could not be assigned to a recognised type.'),
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
            tr('row {0}: {1}', record.excel_row, record.title_raw)
            for record in duplicated
        )
        issues.append(
            Issue(
                "WARNING", duplicated[0].excel_row, duplicated[0].case_id_raw,
                tr('File number'), normalized_id,
                tr('The number occurs in rows {0}. {1}', rows, titles),
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


def check_context_rule(tokens: list[str], rule: dict[str, Any], matches=None) -> bool:
    matches = matches if matches is not None else item_matcher(tokens)
    all_items = [str(value) for value in rule.get("all", [])]
    any_items = [str(value) for value in rule.get("any", [])]
    if all_items and not all(matches(item) for item in all_items):
        return False
    if any_items and not any(matches(item) for item in any_items):
        return False
    return bool(all_items or any_items)


def classify_title(
    title: str,
    categories: list[Category],
    ambiguities: list[dict[str, Any]],
    macroblock_order: list[str],
    language: str = "uk",
):
    if language not in {"uk", "ru"} and language not in LANGUAGE_CATEGORIES:
        import yaml
        loaded, rules, _, _ = load_dictionaries(yaml, language)
        LANGUAGE_CATEGORIES[language] = loaded
        LANGUAGE_AMBIGUITIES[language] = rules
    token = MATCH_LANGUAGE.set(language)
    try:
        return _classify_title(
            title, categories if language == "uk" else LANGUAGE_CATEGORIES.get(language, categories),
            ambiguities if language == "uk" else LANGUAGE_AMBIGUITIES.get(language, ambiguities), macroblock_order
        )
    finally:
        MATCH_LANGUAGE.reset(token)


def _classify_title(title, categories, ambiguities, macroblock_order):
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

        matches = item_matcher(tokens)
        concept_score, concept_evidence, concept_context = evaluate_concepts(
            matches, category.concepts, category.concept_rules, category.id)
        category_context_evidence: list[str] = list(concept_context)
        for items, label in (
            (category.context_only_phrases, "phrase"),
            (category.context_only_terms, "term"),
            (category.contextual_terms, "weak_context"),
        ):
            category_context_evidence.extend(
                f"{label}: {item}" for item in items if matches(item)
            )
        if category_context_evidence:
            context_ids.append(category.id)
            context_labels.append(category.label)
            context_evidence[category.id] = category_context_evidence

        score = concept_score
        category_evidence: list[str] = list(concept_evidence)
        for items, weight, label in (
            (category.strong_phrases, 4, "phrase"),
            (category.strong_terms, 3, "term"),
            (category.contextual_terms, 1, "weak_context"),
        ):
            for item in items:
                if matches(item):
                    score += weight
                    category_evidence.append(f"{label}: {item}")
        for rule in category.context_rules:
            if check_context_rule(tokens, rule, matches):
                score += int(rule.get("score", 3))
                matched_rule_items = [
                    str(value) for value in rule.get("all", [])
                    if matches(str(value))
                ] + [
                    str(value) for value in rule.get("any", [])
                    if matches(str(value))
                ]
                readable = " + ".join(matched_rule_items)
                category_evidence.append(f"rule: {readable}")

        for ambiguity in ambiguities:
            term = str(ambiguity.get("term", ""))
            category_context = ambiguity.get("conditional", {}).get(category.id, [])
            if (
                term
                and category_context
                and matches(term)
                and any(
                    matches(str(context))
                    for context in category_context
                )
            ):
                score += 3
                category_evidence.append(
                    f"ambiguity_context: {term}"
                )

        has_subject_evidence = any(not e.startswith("weak_context:") for e in category_evidence)
        if score >= category.minimum_score and has_subject_evidence:
            matched_ids.append(category.id)
            matched_labels.append(category.label)
            scores[category.id] = score
            evidence[category.id] = category_evidence
        elif score >= max(1, category.minimum_score - 1):
            for review_term in category.review_terms:
                if matches(review_term):
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
        print(tr('   No case entries to classify.'))
        return

    started_at = time.perf_counter()
    update_every = max(1, total // 100)
    section_results: dict[tuple[str, str], tuple] = {}
    print_classification_progress(0, total, started_at)

    supported_languages = set(analysis_languages().languages)
    for processed, record in enumerate(active_records, start=1):
        if record.language not in supported_languages:
            # Do not silently apply a different language's dictionaries.
            record.review_flags.append("unsupported_language: " + record.language)
            if processed % update_every == 0 or processed == total:
                print_classification_progress(processed, total, started_at, finished=processed == total)
            continue
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
            record.title_raw, categories, ambiguities, macroblock_order,
            language=record.language
        )
        if record.thematic_section:
            section_key = (record.language, record.thematic_section)
            if section_key not in section_results:
                section_results[section_key] = classify_title(
                    record.thematic_section, categories, ambiguities,
                    macroblock_order, language=record.language,
                )
            section_ids, section_labels, _, section_scores, _, _, _, _, _ = section_results[section_key]
            for category_id, label in zip(section_ids, section_labels):
                if category_id not in record.categories:
                    record.categories.append(category_id)
                    record.category_labels.append(label)
                    record.scores[category_id] = section_scores[category_id]
                    record.evidence[category_id] = [f"inventory_section: {record.thematic_section}"]
            ordered = sorted(
                zip(record.categories, record.category_labels),
                key=lambda pair: (-record.scores[pair[0]], pair[1]),
            )
            record.categories = [pair[0] for pair in ordered]
            record.category_labels = [pair[1] for pair in ordered]
            category_by_id = {
                category.id: category
                for category in (categories if record.language == "uk" else LANGUAGE_CATEGORIES.get(record.language, categories))
            }
            found_blocks = {
                category_by_id[category_id].macroblock
                for category_id in record.categories
            }
            record.macroblocks = [block for block in macroblock_order if block in found_blocks]
        if record.detected_language not in {"undetermined", record.language}:
            record.review_flags.append("language_check: " + record.detected_language)
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
        f"{tr('elapsed')} {format_duration(elapsed)}"
    )
    if processed:
        remaining = elapsed / processed * (total - processed)
        if finished:
            details += " | " + tr('complete')
        else:
            details += f" | {tr('remaining')} ~{format_duration(remaining)}"

    print("\r" + details.ljust(115), end="\n" if finished else "", flush=True)


def classification_type(record: Record) -> str:
    if len(record.categories) > 1:
        return "subject_multilabel"
    if record.categories:
        return "subject_single"
    if record.context_categories:
        return "context_only"
    return "unclassified"


def classification_confidence(record: Record) -> str:
    """Descriptive rule strength, not a statistical probability."""
    if record.categories:
        return "strong" if max(record.scores.values(), default=0) >= 4 else "threshold"
    if record.context_categories:
        return "context_only"
    return "none"


CLASSIFICATION_INDEX_FIELDS = [
    "record_uid", "source", "archive", "fond", "inventory", "sheet",
    "row_number", "case_id", "status", "title_original", "dates_original",
    "pages_original", "notes_original", "language", "detected_language",
    "categories", "category_labels", "classification_type",
    "classification_confidence", "scores", "evidence", "context_categories",
    "context_labels", "context_evidence", "section_label", "thematic_section", "start_year",
    "end_year", "chronology_basis",
]


def classification_index_row(record: Record) -> dict[str, Any]:
    base = record_to_row(record)
    return {
        "record_uid": base["record_uid"],
        "source": record.source_id,
        "archive": record.source_archive,
        "fond": record.source_fond,
        "inventory": record.source_inventory,
        "sheet": record.sheet_name,
        "row_number": record.excel_row,
        "case_id": record.case_id_raw,
        "status": record.status,
        "title_original": record.title_raw,
        "dates_original": record.dates_raw,
        "pages_original": record.pages_raw,
        "notes_original": record.notes_raw,
        "language": record.language,
        "detected_language": record.detected_language,
        "categories": " | ".join(record.categories),
        "category_labels": " | ".join(record.category_labels),
        "classification_type": classification_type(record),
        "classification_confidence": classification_confidence(record),
        "scores": base["scores"],
        "evidence": base["evidence"],
        "context_categories": " | ".join(record.context_categories),
        "context_labels": " | ".join(record.context_category_labels),
        "context_evidence": base["context_evidence"],
        "section_label": record.section_label,
        "thematic_section": record.thematic_section,
        "start_year": record.start_year or "",
        "end_year": record.end_year or "",
        "chronology_basis": chronology_basis(record),
    }


def write_combined_indexes(
    records: list[Record], categories: list[Category], tables_dir: Path
) -> None:
    cases = [record for record in records if record.status == "case"]
    unclassified = [record for record in cases if not record.categories]
    service_records = [record for record in records if record.status != "case"]

    for filename, selected in (
        ("classification_index.csv", cases),
        ("unclassified_cases.csv", unclassified),
    ):
        written = write_csv(
            tables_dir / filename, CLASSIFICATION_INDEX_FIELDS,
            (classification_index_row(record) for record in selected),
        )
        if written != len(selected):
            raise RuntimeError(
                tr('{0}: wrote {1} rows instead of {2}', filename, written, len(selected))
            )

    service_fields = [
        "record_uid", "source", "archive", "fond", "inventory", "sheet",
        "row_number", "case_id", "title_original", "dates_original",
        "pages_original", "notes_original", "status", "section_label", "thematic_section",
    ]
    write_csv(
        tables_dir / "service_records.csv",
        service_fields,
        (
            {
                "record_uid": r.record_uid,
                "source": r.source_id,
                "archive": r.source_archive,
                "fond": r.source_fond,
                "inventory": r.source_inventory,
                "sheet": r.sheet_name,
                "row_number": r.excel_row,
                "case_id": r.case_id_raw,
                "title_original": r.title_raw,
                "dates_original": r.dates_raw,
                "pages_original": r.pages_raw,
                "notes_original": r.notes_raw,
                "status": r.status,
                "section_label": r.section_label,
                "thematic_section": r.thematic_section,
            }
            for r in service_records
        ),
    )

    counts = Counter(
        category_id for record in cases for category_id in record.categories
    )
    write_csv(
        tables_dir / "thematic_summary.csv",
        [
            "category_id", "category_label", "macroblock", "export_file",
            "cases", "percent_of_analyzed_titles",
        ],
        (
            {
                "category_id": category.id,
                "category_label": category.label,
                "macroblock": category.macroblock,
                "export_file": category.export_filename,
                "cases": counts[category.id],
                "percent_of_analyzed_titles": (
                    f"{counts[category.id] / len(cases) * 100:.2f}"
                    if cases else "0.00"
                ),
            }
            for category in categories
        ),
    )


def copy_cell(source_cell, target_cell) -> None:
    target_cell.value = source_cell.value
    # Style indices belong to the source workbook; copy individual properties.
    target_cell.font = copy(source_cell.font)
    target_cell.fill = copy(source_cell.fill)
    target_cell.border = copy(source_cell.border)
    target_cell.alignment = copy(source_cell.alignment)
    target_cell.number_format = source_cell.number_format
    target_cell.protection = copy(source_cell.protection)
    target_cell.quotePrefix = source_cell.quotePrefix
    if source_cell.hyperlink:
        target_cell._hyperlink = copy(source_cell.hyperlink)
    if source_cell.comment:
        target_cell.comment = copy(source_cell.comment)


def copy_source_row(source_sheet, target_sheet, source_row: int,
                    target_row: int, max_columns: int) -> None:
    for column in range(1, max_columns + 1):
        copy_cell(
            source_sheet.cell(source_row, column),
            target_sheet.cell(target_row, column),
        )
    source_dimension = source_sheet.row_dimensions[source_row]
    target_dimension = target_sheet.row_dimensions[target_row]
    if source_dimension.height is not None:
        target_dimension.height = source_dimension.height
    target_dimension.hidden = source_dimension.hidden
    target_dimension.outlineLevel = source_dimension.outlineLevel
    target_dimension.collapsed = source_dimension.collapsed
    target_dimension.thickTop = source_dimension.thickTop
    target_dimension.thickBot = source_dimension.thickBot


def create_filtered_workbook(
    openpyxl_module,
    source_workbook,
    records: list[Record],
    output_path: Path,
    max_columns: int,
) -> None:
    workbook = openpyxl_module.Workbook()
    workbook.remove(workbook.active)
    by_sheet: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        by_sheet[record.sheet_name].append(record)

    for sheet_name in SHEET_NAMES:
        header_row = HEADER_ROWS_BY_SHEET[sheet_name]
        target_sheet = workbook.create_sheet(sheet_name)
        source_sheet = (
            source_workbook[sheet_name]
            if sheet_name in source_workbook.sheetnames else None
        )
        if source_sheet is not None:
            for row_number in range(1, header_row + 1):
                copy_source_row(source_sheet, target_sheet, row_number, row_number, max_columns)
            for column in range(1, max_columns + 1):
                letter = openpyxl_module.utils.get_column_letter(column)
                source_dimension = source_sheet.column_dimensions[letter]
                target_dimension = target_sheet.column_dimensions[letter]
                source_width = source_dimension.width
                if source_width is not None:
                    target_dimension.width = source_width
                target_dimension.hidden = source_dimension.hidden
                target_dimension.bestFit = source_dimension.bestFit
                target_dimension.outlineLevel = source_dimension.outlineLevel
                target_dimension.collapsed = source_dimension.collapsed
            target_sheet.sheet_view.showGridLines = source_sheet.sheet_view.showGridLines
            target_sheet.sheet_view.zoomScale = source_sheet.sheet_view.zoomScale
            target_sheet.sheet_view.zoomScaleNormal = (
                source_sheet.sheet_view.zoomScaleNormal
            )
            target_sheet.sheet_format.defaultRowHeight = (
                source_sheet.sheet_format.defaultRowHeight
            )
            target_sheet.sheet_format.defaultColWidth = (
                source_sheet.sheet_format.defaultColWidth
            )
            target_sheet.freeze_panes = source_sheet.freeze_panes
        else:
            fallback_headers = [
                "№ з/п", "Заголовок справи", "Крайні дати документів справи",
                "Кількість аркушів у справі", "Примітки",
            ]
            for column, value in enumerate(fallback_headers[:max_columns], start=1):
                target_sheet.cell(1, column, value)

        target_row = header_row + 1
        for record in sorted(by_sheet.get(sheet_name, []), key=lambda r: r.excel_row):
            if source_sheet is not None:
                copy_source_row(
                    source_sheet, target_sheet, record.excel_row,
                    target_row, max_columns,
                )
            else:
                values = [
                    record.case_id_raw, record.title_raw, record.dates_raw,
                    record.pages_raw, record.notes_raw,
                ]
                for column, value in enumerate(values[:max_columns], start=1):
                    target_sheet.cell(target_row, column, value)
            target_row += 1

        if (source_sheet is not None and source_sheet.auto_filter.ref
                and target_row > header_row + 1):
            last_column = openpyxl_module.utils.get_column_letter(max_columns)
            target_sheet.auto_filter.ref = f"A{header_row}:{last_column}{target_row - 1}"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    workbook.close()


def export_thematic_selections(
    openpyxl_module, records: list[Record], categories: list[Category]
) -> list[dict[str, Any]]:
    exports = ANALYSIS_CONFIG.get("exports", {})
    if not exports.get("enabled", True):
        print(tr('   Thematic exports are disabled in config/analysis.yaml.'))
        return []

    max_columns = int(exports.get("source_columns", 5))
    if not 1 <= max_columns <= 26:
        raise ValueError(tr('exports.source_columns must be between 1 and 26'))
    create_xlsx = bool(exports.get("xlsx", True))
    create_csv = bool(exports.get("csv", True))
    if not create_xlsx and not create_csv:
        raise ValueError(tr('Enable XLSX or CSV for thematic exports'))
    cases = [record for record in records if record.status == "case"]
    unclassified = [record for record in cases if not record.categories]
    service_records = [record for record in records if record.status != "case"]

    selections: list[tuple[str, str, list[Record]]] = [
        (category.id, category.export_filename,
         [r for r in cases if category.id in r.categories])
        for category in categories
    ]
    selections.extend(
        [
            (
                "unclassified",
                str(exports.get("unclassified_file", "unclassified.xlsx")),
                unclassified,
            ),
            (
                "service_records",
                str(exports.get("service_records_file", "service_records.xlsx")),
                service_records,
            ),
        ]
    )
    export_names: set[str] = set()
    for selection_id, filename, _ in selections:
        if not re.fullmatch(r'[^<>:"/\\|?*]+\.xlsx', filename, re.I):
            raise ValueError(
                tr('Invalid XLSX filename for {0}: {1}', selection_id, filename)
            )
        key = filename.casefold()
        if key in export_names:
            raise ValueError(tr('Duplicate thematic filename: {0}', filename))
        export_names.add(key)

    source_workbook = None
    if create_xlsx:
        source_workbook = openpyxl_module.load_workbook(
            INPUT_FILE, read_only=False, data_only=False
        )

    csv_dir = THEMATIC_DIR / "csv"
    manifest_rows: list[dict[str, Any]] = []
    total = len(selections)
    try:
        for index, (selection_id, filename, selected) in enumerate(selections, start=1):
            xlsx_path = THEMATIC_DIR / filename
            if create_xlsx:
                create_filtered_workbook(
                    openpyxl_module, source_workbook, selected,
                    xlsx_path, max_columns,
                )
            if create_csv:
                write_csv(
                    csv_dir / f"{Path(filename).stem}.csv",
                    CLASSIFICATION_INDEX_FIELDS,
                    (classification_index_row(record) for record in selected),
                )
            manifest_rows.append(
                {
                    "selection_id": selection_id,
                    "xlsx_file": filename if create_xlsx else "",
                    "csv_file": f"csv/{Path(filename).stem}.csv" if create_csv else "",
                    "records": len(selected),
                }
            )
            print(
                tr('\r   Thematic exports: {0}/{1} — {2} ({3} entries)', index, total, filename, format_count(len(selected))).ljust(115),
                end="\n" if index == total else "", flush=True,
            )
    finally:
        if source_workbook is not None:
            source_workbook.close()

    write_csv(
        THEMATIC_DIR / "export_manifest.csv",
        ["selection_id", "xlsx_file", "csv_file", "records"],
        manifest_rows,
    )
    return manifest_rows


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
        "record_uid": record.record_uid,
        "source_archive": record.source_archive,
        "source_fond": record.source_fond,
        "source_inventory": record.source_inventory,
        "source_id": record.source_id,
        "language": record.language,
        "detected_language": record.detected_language,
        "language_source": record.language_source,
        "title_normalized": normalize_text(record.title_raw),
        "section_label": record.section_label,
        "thematic_section": record.thematic_section,
        "chronology_basis": chronology_basis(record),
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


def chronology_basis(record: Record) -> str:
    if record.start_year is not None:
        if (not MIN_ALLOWED_YEAR <= record.start_year <= MAX_ALLOWED_YEAR
                or (record.end_year is not None and
                    (record.end_year < record.start_year or not MIN_ALLOWED_YEAR <= record.end_year <= MAX_ALLOWED_YEAR))):
            return "invalid_dates"
        return "dates_field"
    return "section_heading" if record.section_year else "unknown"


def get_decade(record: Record) -> int | None:
    if chronology_basis(record) == "invalid_dates":
        return None
    year = record.start_year or record.section_year
    return year // 10 * 10 if year is not None else None


def get_year_values(record: Record) -> list[int]:
    """Return every year represented by a case for the yearly chronology."""
    basis = chronology_basis(record)
    if basis in {"invalid_dates", "unknown"}:
        return []
    if record.start_year is None:
        return [record.section_year] if record.section_year is not None else []

    end_year = record.end_year or record.start_year
    chronology = ANALYSIS_CONFIG.get("chronology", {})
    maximum_span = int(chronology.get("maximum_span_years", 100))
    if end_year - record.start_year > maximum_span:
        return [record.start_year]
    return list(range(record.start_year, end_year + 1))


def build_yearly_description_counts(
    records: list[Record], active: list[Record]
) -> tuple[list[str], list[int], dict[str, Counter[int]]]:
    """Count yearly presence separately for every sheet-description."""
    components = chart_sheet_order(records)
    counts = {component: Counter() for component in components}
    for record in active:
        counts[record.sheet_name].update(get_year_values(record))
    observed_years = {
        year for counter in counts.values() for year in counter
    }
    years = (
        list(range(min(observed_years), max(observed_years) + 1))
        if observed_years else []
    )
    return components, years, counts


def create_geography_tables(active: list[Record], ordered_sheets: list[str]) -> dict[str, Any]:
    _, places = load_places()
    rows = []
    missing = []
    totals: Counter[str] = Counter()
    by_description: Counter[tuple[str, str]] = Counter()
    by_decade: Counter[tuple[str, str, str]] = Counter()
    for record in active:
        found = find_places(record.title_raw, places, record.language)
        decade = get_decade(record)
        for place, expression in found:
            row = {
                "record_uid": record.record_uid,
                "archive": record.source_archive, "fond": record.source_fond,
                "inventory": record.source_inventory, "sheet_name": record.sheet_name,
                "case_id": record.case_id_normalized, "decade": decade if decade is not None else "unknown",
                "place": place.name, "latitude": place.lat, "longitude": place.lon,
                "matched_form": expression, "title": record.title_raw,
            }
            rows.append(row)
            totals[place.name] += 1
            by_description[place.name, record.sheet_name] += 1
            by_decade[place.name, str(row["decade"]), record.sheet_name] += 1
        for candidate in unknown_candidates(record.title_raw, found, record.language):
            missing.append({
                "record_uid": record.record_uid,
                "sheet_name": record.sheet_name, "case_id": record.case_id_normalized,
                "candidate": candidate, "title": record.title_raw,
            })
    write_csv(WORK_DIR / "geography_mentions.csv",
              ["record_uid", "archive", "fond", "inventory", "sheet_name",
               "case_id", "decade", "place", "latitude", "longitude",
               "matched_form", "title"], rows)
    write_csv(WORK_DIR / "geography_by_description.csv",
              ["place", "sheet_name", "description", "titles"],
              ({"place": place.name, "sheet_name": sheet,
                "description": configured_description_label(sheet),
                "titles": by_description[place.name, sheet]}
               for place in places for sheet in ordered_sheets))
    write_csv(WORK_DIR / "geography_by_decade.csv",
              ["place", "decade", "sheet_name", "description", "titles"],
              ({"place": place, "decade": decade, "sheet_name": sheet,
                "description": configured_description_label(sheet), "titles": count}
               for (place, decade, sheet), count in sorted(by_decade.items(),
                   key=lambda item: (item[0][0], item[0][1], item[0][2]))))
    write_csv(WORK_DIR / "geography_unmapped_candidates.csv",
              ["record_uid", "sheet_name", "case_id", "candidate", "title"], missing)
    return {"rows": rows, "totals": totals,
            "matched_cases": len({row["record_uid"] for row in rows}),
            "unmapped_candidates": len(missing)}


def create_service_tables(records: list[Record], categories: list[Category]):
    record_fields = [
        "record_uid", "source_archive", "source_fond", "source_inventory", "source_id",
        "language", "detected_language", "language_source", "title_normalized",
        "section_label", "thematic_section", "chronology_basis",
        "sheet_name", "excel_row", "case_id_raw", "case_id_normalized", "status",
        "section_year", "start_year", "end_year", "pages",
        "title_raw", "dates_raw", "pages_raw", "notes_raw",
        "category_ids", "category_labels", "macroblocks",
        "scores", "evidence", "context_category_ids",
        "context_category_labels", "context_evidence", "review_flags",
    ]
    active = [record for record in records if record.status == "case"]
    topic_unclassified = [record for record in active if not record.categories]
    context_only = [record for record in topic_unclassified if record.context_categories]
    unclassified = [record for record in topic_unclassified if not record.context_categories]
    needs_review = [record for record in active if record.review_flags]
    context_mentions = [record for record in active if record.context_categories]
    for filename, selected in (
        ("records.csv", records),
        ("topic_unclassified_cases.csv", topic_unclassified),
        ("unclassified_cases.csv", unclassified),
        ("context_only_cases.csv", context_only),
        ("needs_review.csv", needs_review),
        ("context_mentions.csv", context_mentions),
    ):
        written = write_csv(
            WORK_DIR / filename,
            record_fields,
            (record_to_row(record) for record in selected),
        )
        if written != len(selected):
            raise RuntimeError(
                tr('{0}: wrote {1} rows instead of {2}', filename, written, len(selected))
            )

    description_rows: list[dict[str, Any]] = []
    present_sheets = {record.sheet_name for record in records}
    ordered_sheets = [name for name in SHEET_NAMES if name in present_sheets]
    ordered_sheets += sorted(present_sheets.difference(ordered_sheets))
    for sheet_name in ordered_sheets:
        sheet_records = [record for record in records if record.sheet_name == sheet_name]
        sheet_active = [record for record in sheet_records if record.status == "case"]
        subject = sum(bool(record.categories) for record in sheet_active)
        context_only_count = sum(
            not record.categories and bool(record.context_categories)
            for record in sheet_active
        )
        description_rows.append(
            {
                "sheet_name": sheet_name,
                "description": configured_description_label(sheet_name),
                "cases_in_analysis": len(sheet_active),
                "withdrawn_records": sum(
                    record.status == "withdrawn" for record in sheet_records
                ),
                "subject_classified": subject,
                "context_only": context_only_count,
                "unclassified": len(sheet_active) - subject - context_only_count,
                "category_assignments": sum(
                    len(record.categories) for record in sheet_active
                ),
            }
        )
    write_csv(
        WORK_DIR / "description_summary.csv",
        [
            "sheet_name", "description", "cases_in_analysis",
            "withdrawn_records", "subject_classified", "context_only",
            "unclassified", "category_assignments",
        ],
        description_rows,
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
    chronology_counts = Counter((get_decade(r), chronology_basis(r)) for r in active)
    write_csv(WORK_DIR / "chronology_sources.csv", ["decade", "basis", "titles"],
              ({"decade": decade if decade is not None else "", "basis": basis, "titles": count}
               for (decade, basis), count in sorted(chronology_counts.items(), key=lambda x: (x[0][0] or 0, x[0][1]))))
    write_csv(
        WORK_DIR / "cases_by_decade.csv",
        ["decade", "cases"],
        (
            {"decade": f"{decade}–{decade + 9}", "cases": count}
            for decade, count in sorted(decade_counts.items())
        ),
    )

    year_components, years, year_counts = build_yearly_description_counts(
        records, active
    )
    write_csv(
        WORK_DIR / "cases_by_year.csv",
        ["year", *year_components],
        (
            {
                "year": year,
                **{
                    component: year_counts[component][year]
                    for component in year_components
                },
            }
            for year in years
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

    document_type_counts: Counter[str] = Counter()
    document_type_by_sheet: dict[str, Counter[str]] = {
        sheet_name: Counter() for sheet_name in ordered_sheets
    }
    document_type_index: list[dict[str, Any]] = []
    document_type_multi = 0
    for record in active:
        matches = match_document_types(normalize_text(record.title_raw), record.language)
        ids = [document_type.id for document_type, _ in matches]
        document_type_counts.update(ids)
        document_type_by_sheet[record.sheet_name].update(ids)
        document_type_multi += len(ids) > 1
        document_type_index.append({
            "record_uid": record.record_uid,
            "archive": record.source_archive,
            "fond": record.source_fond,
            "inventory": record.source_inventory,
            "sheet_name": record.sheet_name,
            "excel_row": record.excel_row,
            "case_id": record.case_id_raw,
            "title": record.title_raw,
            "document_type_ids": " | ".join(ids),
            "document_type_labels": " | ".join(
                document_type.label for document_type, _ in matches
            ),
            "matched_expressions": " | ".join(
                f"{document_type.id}: {expression}"
                for document_type, expression in matches
            ),
        })

    write_csv(
        WORK_DIR / "document_type_index.csv",
        ["record_uid", "archive", "fond", "inventory", "sheet_name",
         "excel_row", "case_id", "title", "document_type_ids",
         "document_type_labels", "matched_expressions"],
        document_type_index,
    )
    write_csv(
        WORK_DIR / "document_type_counts.csv",
        ["document_type_id", "document_type_label", "titles",
         "percent_of_analyzed_titles"],
        ({"document_type_id": document_type.id,
          "document_type_label": document_type.label,
          "titles": document_type_counts[document_type.id],
          "percent_of_analyzed_titles": (
              f"{document_type_counts[document_type.id] / len(active) * 100:.2f}"
              if active else "0.00"
          )} for document_type in DOCUMENT_TYPES),
    )
    sheet_totals = Counter(record.sheet_name for record in active)
    write_csv(
        WORK_DIR / "document_types_by_description.csv",
        ["sheet_name", "description", "document_type_id", "document_type_label",
         "titles", "description_titles_total", "percent_of_description_titles"],
        ({"sheet_name": sheet_name,
          "description": configured_description_label(sheet_name),
          "document_type_id": document_type.id,
          "document_type_label": document_type.label,
          "titles": document_type_by_sheet[sheet_name][document_type.id],
          "description_titles_total": sheet_totals[sheet_name],
          "percent_of_description_titles": (
              f"{document_type_by_sheet[sheet_name][document_type.id] / sheet_totals[sheet_name] * 100:.2f}"
              if sheet_totals[sheet_name] else "0.00"
          )}
         for sheet_name in ordered_sheets for document_type in DOCUMENT_TYPES),
    )
    geography = create_geography_tables(active, ordered_sheets)
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
        "year_components": year_components,
        "years": years,
        "year_counts": year_counts,
        "theme_decades": theme_decades,
        "description_rows": description_rows,
        "document_type_counts": document_type_counts,
        "document_type_by_sheet": document_type_by_sheet,
        "document_type_matched": sum(bool(row["document_type_ids"])
                                     for row in document_type_index),
        "document_type_multi": document_type_multi,
        "geography": geography,
    }


def one_line(value: str, limit: int = 500) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[:limit - 1] + "…"


def write_error_log(issues: list[Issue], records: list[Record]) -> None:
    errors = [issue for issue in issues if issue.level == "ERROR"]
    warnings = [issue for issue in issues if issue.level == "WARNING"]
    statuses = Counter(record.status for record in records)
    lines = [
        tr('ARCHIVAL INVENTORY VALIDATION'),
        tr('File: {0}', INPUT_FILE),
        tr('Worksheets processed: ')
        + ", ".join(sorted({record.sheet_name for record in records})),
        tr('Run date: {0}', f'{datetime.now():%d.%m.%Y %H:%M:%S}'),
        "",
        tr('SUMMARY'),
        tr('Files included in the analysis: {0}', statuses['case']),
        tr('Withdrawn entries: {0}', statuses['withdrawn']),
        tr('Year headings: {0}', statuses['year_heading']),
        tr('File group headings: {0}', statuses['group_heading']),
        tr('Inventory headings: {0}', statuses['inventory']),
        tr('Unrecognised rows: {0}', statuses['unknown']),
        tr('Errors: {0}', len(errors)),
        tr('Warnings: {0}', len(warnings)),
        "",
    ]

    number = 1
    for heading, group in ((tr('ERRORS'), errors), (tr('WARNINGS'), warnings)):
        lines.extend([heading, ""])
        if not group:
            lines.extend([tr('None detected.'), ""])
            continue
        for issue in group:
            location = []
            if issue.sheet_name:
                location.append(tr('worksheet “{0}”', issue.sheet_name))
            if issue.row is not None:
                location.append(tr('row {0}', issue.row))
            if issue.case_id:
                location.append(tr('file no. {0}', issue.case_id))
            suffix = f" ({', '.join(location)})" if location else ""
            lines.append(f"{number}. {issue.message}{suffix}")
            if issue.field:
                lines.append(tr('   Field: {0}', issue.field))
            if issue.value:
                lines.append(tr('   Value: {0}', one_line(issue.value)))
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
    visual = Visualization.from_config(ANALYSIS_CONFIG)
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

    lines = [
        tr('# Results of archival finding aid analysis'),
        "",
        tr('Run date: {0}.', f'{datetime.now():%d.%m.%Y %H:%M:%S}'),
        tr('Script version: `{0}`. Dictionary version: `{1}`.', SCRIPT_VERSION, dictionary_version),
        tr('Worksheets processed: ')
        + ", ".join(sorted({record.sheet_name for record in records})) + ".",
        "",
        tr('## Corpus composition'),
        "",
        tr('| Metric | Value |'),
        "|---|---:|",
        tr('| File titles included in the analysis | {0} |', format_count(len(active))),
        tr('| Withdrawn entries | {0} |', format_count(status_counts['withdrawn'])),
        tr('| Year headings | {0} |', format_count(status_counts['year_heading'])),
        tr('| File group headings | {0} |', format_count(status_counts['group_heading'])),
        tr('| Inventory headings | {0} |', format_count(status_counts['inventory'])),
        tr('| Unrecognised rows | {0} |', format_count(status_counts['unknown'])),
        tr('| Errors | {0} |', format_count(error_count)),
        tr('| Warnings | {0} |', format_count(warning_count)),
        "",
        tr('## Distribution by inventory'),
        "",
        tr('| Inventory | Files analysed | Withdrawn | Subject assigned | Context only | Unassigned |'),
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in table_data["description_rows"]:
        lines.append(
            f"| {visual.description(row['sheet_name'], row['description'])} | {format_count(row['cases_in_analysis'])} | "
            f"{format_count(row['withdrawn_records'])} | "
            f"{format_count(row['subject_classified'])} | "
            f"{format_count(row['context_only'])} | "
            f"{format_count(row['unclassified'])} |"
        )

    registry = LanguageRegistry.load()
    for message, languages in registry.notices({r.language for r in records}):
        lines.extend(["", tr(message, languages), ""])

    lines.extend(
        [
        "",
        tr('## Chronological and quantitative indicators'),
        "",
        tr('- Recognised year range: {0}–{1}.', min(years) if years else '—', max(years) if years else '—'),
        tr('- Files with a recognised folio count: {0}.', format_count(len(pages))),
        tr('- Total folios, using populated numeric values only: {0}.', format_count(sum(pages))),
        tr('- Titles with an empty date field: {0}.', sum((not r.dates_raw for r in active))),
        tr('- Titles without a recognised folio count: {0}.', len(active) - len(pages)),
        tr('- Chronology uses the first year in the date field, or the group-heading year when it is absent. These distinct bases are recorded in records.csv and chronology_sources.csv. A group-heading year is not a file date. Reversed ranges and years outside the configured bounds are excluded from chronological charts.'),
        (
            tr('- Mean folio count: {0}.', f'{statistics.mean(pages):.2f}')
            if pages else tr('- Mean folio count: —.')
        ),
        (
            tr('- Median folio count: {0}.', f'{statistics.median(pages):.2f}')
            if pages else tr('- Median folio count: —.')
        ),
        "",
        tr('## Thematic classification coverage'),
        "",
        tr('- Subject assigned: {0} ({1}).', format_count(len(classified)), percent(len(classified), len(active))),
        tr('- Person or institution context only: {0} ({1}).', format_count(len(context_only)), percent(len(context_only), len(active))),
        tr('- Neither subject nor context assigned: {0} ({1}).', format_count(len(unclassified)), percent(len(unclassified), len(active))),
        tr('- Assigned to multiple categories: {0} ({1}).', format_count(len(multilabel)), percent(len(multilabel), len(active))),
        tr('- Flagged for contextual review: {0}.', format_count(len(needs_review))),
        tr('- Separate person or institution context mentions: {0} ({1}).', format_count(len(context_mentions)), percent(len(context_mentions), len(active))),
        "",
        tr('## Thematic categories'),
        "",
        tr('| Category | Files | Share of files included in the analysis |'),
        "|---|---:|---:|",
        ]
    )
    for category_id, count in category_counts.most_common():
        lines.append(
            f"| {visual.label("categories", category_id, category_by_id[category_id].label)} | "
            f"{format_count(count)} | {percent(count, len(active))} |"
        )

    lines.extend(
        [
            "",
            tr('Shares may sum to more than 100% because one file may belong to multiple categories.'),
            "",
            tr('## Thematic blocks'),
            "",
            tr('| Block | Files | Share of files included in the analysis |'),
            "|---|---:|---:|",
        ]
    )
    for macroblock, count in macroblock_counts.most_common():
        lines.append(
            f"| {visual.label("macroblocks", macroblock, macroblock_labels.get(macroblock, macroblock))} | "
            f"{format_count(count)} | {percent(count, len(active))} |"
        )

    document_type_counts = table_data["document_type_counts"]
    lines.extend([
        "",
        tr('## Document types mentioned in titles'),
        "",
        tr('Document type dictionary version: `{0}`. Classification permits multiple labels: one title may name several document types. A match indicates a mention in the title and does not confirm the contents of the file. Generic phrases meaning “file concerning” are not treated as document types.', DOCUMENT_TYPE_RULES_VERSION),
        "",
        tr('- At least one document type mentioned: {0} ({1}).', format_count(table_data['document_type_matched']), percent(table_data['document_type_matched'], len(active))),
        tr('- Multiple document types mentioned: {0} ({1}).', format_count(table_data['document_type_multi']), percent(table_data['document_type_multi'], len(active))),
        "",
        tr('| Document type | Titles | Share of titles |'),
        "|---|---:|---:|",
    ])
    document_type_labels = {document_type.id: document_type.label
                            for document_type in DOCUMENT_TYPES}
    for document_type_id, count in document_type_counts.most_common():
        lines.append(
            f"| {visual.label("document_types", document_type_id, document_type_labels[document_type_id])} | "
            f"{format_count(count)} | {percent(count, len(active))} |"
        )

    geography = table_data["geography"]
    lines.extend([
        "", tr('## Place mentions in titles'), "",
        tr('Place dictionary version: `{0}`. Found {1} file–place pairs in {2} titles ({3}). One file may mention several places. Coordinates indicate the approximate modern city centre, rather than the location of an event. Institution names and administrative adjectives without an explicit settlement name are not treated as geographical evidence.', load_places()[0], format_count(len(geography['rows'])), format_count(geography['matched_cases']), percent(geography['matched_cases'], len(active))),
        "",
        tr('Names with an explicit geographical prefix that were not matched to the dictionary: {0}. Review `geography_unmapped_candidates.csv` before extending the dictionary.', format_count(geography['unmapped_candidates'])),
        "", tr('| Place | Mentions |'), "|---|---:|",
    ])
    for place, count in geography["totals"].most_common(20):
        lines.append(f'| {visual.label("places", place, place)} | {format_count(count)} |')

    terminology = table_data["terminology"]
    lines.extend([
        "", tr('## Terminology and ideological vocabulary over time'), "",
        tr('Lexical rules version: `{0}`. Found {1} term–title pairs in {2} corpus titles; {3} titles have a usable date. Matches can outnumber files because one title may receive several terms. The charts show mentions in archival titles, rather than the prevalence of ideas or events in historical society. Compare frequencies per 1,000 titles separately by inventory. Interactive report: `figures/terminology_evolution.html`.', TERMINOLOGY_RULES_VERSION, format_count(terminology['matches']), format_count(terminology['titles']), format_count(terminology['dated_titles'])),
    ])

    theme_links = table_data["theme_links"]
    lines.extend([
        "", tr('## Relationships between subjects / File co-classification network'), "",
        tr('{0} of {1} file titles have at least two subject categories. Found {2} category pairs. One shared file can contribute several pairs. For individual inventories, open `figures/theme_links.html`. Full counts are in `tables/theme_links_by_description.csv`, and the files contributing to each pair are in `tables/theme_link_cases.csv`. Context mentions do not create subject relationships.', format_count(theme_links['multi']), format_count(theme_links['titles']), format_count(theme_links['category_pairs'])),
    ])

    lines.extend(
        [
            "",
            tr('## Generated materials'),
            "",
            tr('- reports/error.log: errors and warnings.'),
            tr('- tables/records.csv: all recognised rows.'),
            tr('- tables/description_summary.csv: control totals for each inventory.'),
            tr('- tables/unclassified_cases.csv: files without subject or context labels.'),
            tr('- tables/topic_unclassified_cases.csv: all files without a subject label, including context-only files.'),
            tr('- tables/context_only_cases.csv: files with person or institution context only.'),
            tr('- tables/needs_review.csv: files with ambiguous terms.'),
            tr('- tables/context_mentions.csv: person and institution mentions that do not themselves establish the subject.'),
            tr('- tables/category_counts.csv: file counts by category.'),
            tr('- tables/context_category_counts.csv: context mention counts by category.'),
            tr('- tables/cases_by_decade.csv: chronological distribution.'),
            tr('- tables/cases_by_year.csv: annual distribution separately by inventory.'),
            tr('- tables/themes_by_decade.csv: subjects by decade.'),
            tr('- tables/document_type_index.csv: document types mentioned in each title and the matching expressions.'),
            tr('- tables/document_type_counts.csv: mention totals by document type.'),
            tr('- tables/document_types_by_description.csv: document types by inventory.'),
            tr('- tables/geography_mentions.csv: each place mention, its coordinates and the file title.'),
            tr('- tables/geography_by_description.csv: place mentions by inventory, including zero values.'),
            tr('- tables/geography_by_decade.csv: mentions by decade and inventory.'),
            tr('- tables/geography_unmapped_candidates.csv: place names to review for possible dictionary inclusion.'),
            tr('- figures/geography_south.html, geography_europe.html, geography_russia.html: separate interactive views of the same map.'),
            tr('- tables/term_mentions.csv: titles, archival references and exact term forms.'),
            tr('- tables/terms_by_decade_and_description.csv: frequencies per 1,000 titles by decade and inventory.'),
            tr('- figures/terminology_evolution.html: interactive report on title vocabulary.'),
            tr('- tables/theme_links_by_description.csv: relationships between subjects and blocks by inventory.'),
            tr('- tables/theme_link_cases.csv: files contributing to each subject or block pair.'),
            tr('- figures/theme_links.html: interactive file co-classification network.'),
            tr('- thematic_exports/: derived XLSX/CSV selections for all enabled categories, plus unclassified and service entries.'),
        ]
    )
    if figures_created:
        lines.append(tr('- figures/: charts in PNG and SVG formats.'))
    else:
        lines.extend(
            [
                "",
                tr('> Charts were not created because matplotlib is not installed. The rest of the analysis was completed.'),
            ]
        )
    lines.extend(
        [
            "",
            tr('## Methodological note'),
            "",
            tr('This is automated classification using dictionary version {0}. Subject categories describe the subject of the file. Institution names, offices and social designations that only identify a participant or document creator receive separate context labels. Before using numerical results in research, review needs_review.csv and unclassified_cases.csv, then revise the dictionaries as appropriate. Classification coverage is not a measure of accuracy.', dictionary_version),
            "",
            tr('The thematic XLSX files are derived research selections, rather than new archival inventories. The input workbook remains the source. One file can appear in several selections because classification permits multiple labels.'),
        ]
    )
    (REPORTS_DIR / "analysis_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def save_figure(plt, name: str) -> None:
    plt.tight_layout()
    buffer = BytesIO()
    plt.savefig(buffer, format="png", dpi=220, bbox_inches="tight")
    png = buffer.getvalue()
    if not png.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"):
        raise RuntimeError(tr('{0}.png: the image was not fully written', name))
    (FIGURES_DIR / f"{name}.png").write_bytes(png)
    plt.savefig(FIGURES_DIR / f"{name}.svg", bbox_inches="tight")
    plt.close()


CHART_PALETTES = (
    ("#4C78A8", "#6F98BC", "#91B5D0", "#B8D1E3", "#D8E8F5"),
    ("#F4E0BE", "#E6BE78", "#D39B48", "#B9782C", "#92591D"),
    ("#557A46", "#729661", "#91B181", "#B2CCAA", "#D6E5D1"),
    ("#70477C", "#8C6797", "#AA89B3", "#C8AECF", "#E3D5E7"),
)


def configured_description_label(sheet_name: str) -> str:
    """Return a complete archival reference for legends and control tables."""
    config = SOURCE_CONFIG.get(sheet_name, {})
    archive = clean_cell(config.get("archive")) or sheet_name
    fond = clean_cell(config.get("fond"))
    inventory = clean_cell(config.get("inventory"))
    reference = archive
    if fond:
        reference += f", ф. {fond}"
    if inventory:
        reference += f": опис {inventory}"
    elif sheet_name.lower().startswith("опис "):
        reference += f": {sheet_name.lower()}"
    return reference


def chart_sheet_order(records: Iterable[Record]) -> list[str]:
    present = {record.sheet_name for record in records}
    configured = [name for name in SHEET_NAMES if name in present]
    return configured + sorted(present.difference(configured))


def chart_sheet_colors(components: Iterable[str]) -> dict[str, str]:
    """Use one tonal family per archive while keeping descriptions distinct."""
    components = list(components)
    all_sheets = list(SHEET_NAMES) + sorted(
        set(components).difference(SHEET_NAMES)
    )
    source_order: list[str] = []
    source_sheets: dict[str, list[str]] = defaultdict(list)
    for sheet_name in all_sheets:
        source_id = SOURCE_CONFIG.get(sheet_name, {}).get("source_id", sheet_name)
        if source_id not in source_order:
            source_order.append(source_id)
        source_sheets[source_id].append(sheet_name)

    colors: dict[str, str] = {}
    for source_index, source_id in enumerate(source_order):
        palette = CHART_PALETTES[source_index % len(CHART_PALETTES)]
        sheets = source_sheets[source_id]
        if len(sheets) == 1:
            shades = [palette[2]]
        else:
            shades = [
                palette[round(index * (len(palette) - 1) / (len(sheets) - 1))]
                for index in range(len(sheets))
            ]
        colors.update(zip(sheets, shades))
    return {component: colors[component] for component in components}


def build_chart_breakdowns(records, active) -> dict[str, Any]:
    """Prepare mutually exclusive description segments for stacked charts."""
    components = chart_sheet_order(records)
    decades = {component: Counter() for component in components}
    categories = {component: Counter() for component in components}
    coverage = {component: Counter() for component in components}
    statuses = {component: Counter() for component in components}

    for record in active:
        decade = get_decade(record)
        if decade is not None:
            decades[record.sheet_name][decade] += 1
        categories[record.sheet_name].update(record.categories)
        if record.categories:
            coverage[record.sheet_name]["subject"] += 1
        elif record.context_categories:
            coverage[record.sheet_name]["context_only"] += 1
        else:
            coverage[record.sheet_name]["unclassified"] += 1

    for record in records:
        if record.status in {"case", "withdrawn"}:
            statuses[record.sheet_name][record.status] += 1

    return {
        "components": components,
        "colors": chart_sheet_colors(components),
        "labels": {
            component: configured_description_label(component)
            for component in components
        },
        "decades": decades,
        "categories": categories,
        "coverage": coverage,
        "statuses": statuses,
    }


def _label_color(hex_color: str) -> str:
    color = hex_color.lstrip("#")
    red, green, blue = (int(color[index:index + 2], 16) for index in (0, 2, 4))
    luminance = (0.299 * red + 0.587 * green + 0.114 * blue) / 255
    return "#202020" if luminance > 0.62 else "white"


def _segment_labels(
    values: list[int], totals: list[int], chart_maximum: int, horizontal: bool
) -> list[str]:
    minimum_scale_share = 0.018 if horizontal else 0.035
    return [
        str(value)
        if (
            value >= 10
            and value / max(total, 1) >= 0.025
            and value / max(chart_maximum, 1) >= minimum_scale_share
        )
        else ""
        for value, total in zip(values, totals)
    ]


def draw_stacked_bars(
    ax,
    labels: list[str],
    components: list[str],
    values: dict[str, list[int]],
    colors: dict[str, str],
    component_labels: dict[str, str],
    *,
    horizontal: bool = False,
    visual: Visualization | None = None,
) -> list[int]:
    visual = visual or Visualization()
    totals = [
        sum(values[component][index] for component in components)
        for index in range(len(labels))
    ]
    chart_maximum = max(totals, default=0)
    offsets = [0] * len(labels)
    for component in components:
        segment = values[component]
        kwargs = {
            "label": component_labels[component],
            "color": colors[component],
            "edgecolor": "white",
            "linewidth": 0.2,
        }
        if horizontal:
            bars = ax.barh(labels, segment, left=offsets, **kwargs)
        else:
            bars = ax.bar(labels, segment, bottom=offsets, **kwargs)
        ax.bar_label(
            bars,
            labels=_segment_labels(
                segment, totals, chart_maximum, horizontal
            ),
            label_type="center",
            fontsize=7,
            color=_label_color(colors[component]),
        )
        offsets = [offset + value for offset, value in zip(offsets, segment)]

    margin = max(chart_maximum * 0.012, 0.5)
    for index, total in enumerate(totals):
        if not total:
            continue
        total_label = f"{visual.text('Total:')} {total}"
        if horizontal:
            ax.text(
                total + margin, index, total_label,
                va="center", fontsize=8, fontweight="bold",
            )
        else:
            ax.text(
                index, total + margin, total_label,
                ha="center", fontsize=8, fontweight="bold",
            )
    ax.legend(
        title=visual.text('Inventory'),
        loc="lower center",
        bbox_to_anchor=(0.5, 1.03),
        ncol=min(len(components), 3),
        frameon=False,
        fontsize=8,
        title_fontsize=8,
    )
    return totals


def create_figures(plt, records, categories, table_data,
                   visual: Visualization | None = None) -> bool:
    visual = visual or Visualization()
    if plt is None:
        print(
            tr('Matplotlib is unavailable; static charts were skipped.\nTo enable charts, run: "{0}" -m pip install matplotlib', sys.executable)
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
    breakdowns = build_chart_breakdowns(records, active)
    components = breakdowns["components"]
    colors = breakdowns["colors"]
    component_labels = {s: visual.description(s, configured_description_label(s))
                        for s in components}

    decades = sorted(decade_counts)
    decade_labels = [f"{decade}–{decade + 9}" for decade in decades]
    decade_values = {
        component: [breakdowns["decades"][component][decade] for decade in decades]
        for component in components
    }
    _, ax = plt.subplots(figsize=(10, 5.6))
    draw_stacked_bars(
        ax, decade_labels, components, decade_values, colors, component_labels, visual=visual
    )
    ax.set_title(visual.text('Distribution of case titles by decade'))
    ax.set_xlabel(visual.text('Start year of the case, or section year if unavailable'))
    ax.set_ylabel(visual.text('Number of case files'))
    ax.tick_params(axis="x", rotation=45)
    for label in ax.get_xticklabels():
        label.set_ha("right")
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    save_figure(plt, "cases_by_decade")

    year_components = table_data["year_components"]
    years = table_data["years"]
    year_counts = table_data["year_counts"]
    if year_components and years:
        figure, axes = plt.subplots(
            len(year_components), 1,
            figsize=(11, max(4.8, 2.7 * len(year_components))),
            sharex=True,
            squeeze=False,
        )
        for index, component in enumerate(year_components):
            axis = axes[index][0]
            axis.plot(
                years,
                [year_counts[component][year] for year in years],
                color=colors[component],
                linewidth=1.8,
            )
            axis.set_title(component_labels[component], loc="left", fontsize=10)
            axis.set_ylabel(visual.text('Files'))
            axis.grid(alpha=0.22)
            axis.set_axisbelow(True)
        axes[-1][0].set_xlabel(visual.text('Year'))
        figure.suptitle(visual.text('Chronological distribution of case files'), fontsize=13)
        save_figure(plt, "cases_by_year")

    ordered = category_counts.most_common()
    category_ids = [item[0] for item in ordered][::-1]
    labels = [visual.label("categories", key, category_by_id[key].label) if visual.language == "uk" else
              fill(visual.label("categories", key, category_by_id[key].label), 45)
              for key in category_ids]
    category_values = {
        component: [
            breakdowns["categories"][component][category_id]
            for category_id in category_ids
        ]
        for component in components
    }
    _, ax = plt.subplots(figsize=(12 if visual.bilingual else 10,
                                  6.5 if visual.language == "uk" else
                                  max(6.5, sum(label.count("\n") + 1 for label in labels) * 0.3)))
    draw_stacked_bars(
        ax, labels, components, category_values, colors, component_labels,
        horizontal=True, visual=visual,
    )
    ax.set_title(visual.text('Thematic distribution of case titles'))
    ax.set_xlabel(visual.text('Number of case files'))
    ax.grid(axis="x", alpha=0.25)
    ax.set_axisbelow(True)
    save_figure(plt, "thematic_categories")

    document_type_counts = table_data["document_type_counts"]
    if document_type_counts:
        document_type_ids = [key for key, _ in document_type_counts.most_common()][::-1]
        document_type_by_id = {item.id: item for item in DOCUMENT_TYPES}
        document_type_labels = [document_type_by_id[key].label if visual.language == "uk" else
                                fill(visual.label("document_types", key,
                                                  document_type_by_id[key].label), 42)
                                for key in document_type_ids]
        document_type_values = {
            component: [table_data["document_type_by_sheet"][component][key]
                        for key in document_type_ids]
            for component in components
        }
        figure, (axis, details) = plt.subplots(
            1, 2, sharey=True,
            figsize=(18 if visual.bilingual else 16,
                     max(7.0, len(document_type_ids) * 0.48 + 1.8) if visual.language == "uk" else
                     max(7.0, sum(label.count("\n") + 1 for label in document_type_labels) * 0.4 + 1.8)),
            gridspec_kw={"width_ratios": [3.8, 1.8]},
        )
        draw_stacked_bars(
            axis, document_type_labels, components,
            document_type_values, colors, component_labels,
            horizontal=True, visual=visual,
        )
        axis.set_title(visual.text('Document types mentioned in case titles'))
        axis.set_xlabel(visual.text('Number of case titles'))
        axis.grid(axis="x", alpha=0.25)
        axis.set_axisbelow(True)
        axis.set_xlim(right=max(document_type_counts.values()) * 1.22)

        details.axis("off")
        details.set_xlim(0, len(components))
        details.set_title(visual.text('By archival inventory'), fontsize=10)
        for column, component in enumerate(components):
            source = SOURCE_CONFIG.get(component, {})
            header = (f"{source.get('archive', component)}\n"
                      f"ф. {source.get('fond', '')}, оп. {source.get('inventory', '')}")
            if visual.language == "en":
                header = fill(visual.reference(str(source.get('archive', component)),
                                              str(source.get('fond', '')),
                                              str(source.get('inventory', ''))), 28)
            details.text(column + 0.5, len(document_type_ids) - 0.13,
                         header, ha="center", va="bottom", fontsize=7,
                         clip_on=False)
            for row, document_type_id in enumerate(document_type_ids):
                count = table_data["document_type_by_sheet"][component][document_type_id]
                details.text(column + 0.5, row, str(count) if count else "—",
                             ha="center", va="center", fontsize=8)
        save_figure(plt, "document_types")

    coverage_keys = ["subject", "context_only", "unclassified"]
    coverage_labels = [
        "Предметну тему\nвизначено", "Лише контекст", "Не визначено"
    ]
    coverage_labels = [visual.text(label) for label in coverage_labels]
    coverage_values = {
        component: [
            breakdowns["coverage"][component][key] for key in coverage_keys
        ]
        for component in components
    }
    _, ax = plt.subplots(figsize=(8.4, 5.2))
    draw_stacked_bars(
        ax, coverage_labels, components, coverage_values, colors,
        component_labels, visual=visual,
    )
    ax.set_title(visual.text('Classification coverage'))
    ax.set_ylabel(visual.text('Number of case files'))
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    save_figure(plt, "classification_coverage")

    status_keys = ["case", "withdrawn"]
    status_labels = [visual.text(label) for label in ("Включено до аналізу", "Вибулі")]
    status_values = {
        component: [
            breakdowns["statuses"][component][key] for key in status_keys
        ]
        for component in components
    }
    _, ax = plt.subplots(figsize=(8.4, 5.2))
    draw_stacked_bars(
        ax, status_labels, components, status_values, colors, component_labels, visual=visual
    )
    ax.set_title(visual.text('Case files included in the analysis and withdrawn records'))
    ax.set_ylabel(visual.text('Number of records'))
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)
    save_figure(plt, "included_and_withdrawn")

    if decades and ordered:
        category_ids = [category_id for category_id, _ in ordered]
        matrix = [
            [theme_decades[category_id][decade] for decade in decades]
            for category_id in category_ids
        ]
        plt.figure(figsize=(13 if visual.bilingual else 11,
                            7 if visual.language == "uk" else
                            max(7, len(category_ids) * (0.7 if visual.bilingual else 0.5))))
        image = plt.imshow(matrix, aspect="auto", cmap="Blues")
        plt.colorbar(image, label=visual.text('Number of case files'))
        plt.xticks(
            range(len(decades)),
            [f"{decade}–{str(decade + 9)[-2:]}" for decade in decades],
            rotation=45, ha="right",
        )
        plt.yticks(
            range(len(category_ids)),
            [visual.label("categories", key, category_by_id[key].label) if visual.language == "uk" else
             fill(visual.label("categories", key, category_by_id[key].label), 45)
             for key in category_ids],
        )
        plt.title(visual.text('Thematic categories by decade'))
        plt.xlabel(visual.text('Decade'))
        save_figure(plt, "themes_by_decade")
    return True


def print_summary(records, issues, table_data, figures_created) -> None:
    statuses = Counter(record.status for record in records)
    print(tr("\nANALYSIS COMPLETE"))
    summary = [
        ("Case entries analysed:", statuses['case']),
        ("Withdrawn entries:", statuses['withdrawn']),
        ("Subject classified:", sum(bool(record.categories) for record in table_data['active'])),
        ("Context only:", len(table_data['context_only'])),
        ("No subject assigned:", len(table_data['unclassified'])),
        ("Flagged for review:", len(table_data['needs_review'])),
        ("Context mentions:", len(table_data['context_mentions'])),
        ("Errors:", sum(issue.level == 'ERROR' for issue in issues)),
        ("Warnings:", sum(issue.level == 'WARNING' for issue in issues)),
        ("Charts created:", tr('yes' if figures_created else 'no')),
    ]
    for label, value in summary:
        print(f"{tr(label):<30}{value}")
    print(tr("\nMain results:"))
    for path in [REPORTS_DIR / 'error.log', REPORTS_DIR / 'analysis_report.md',
                 WORK_DIR / 'records.csv', RUN_DIR / 'tables' / 'classification_index.csv',
                 THEMATIC_DIR, *([FIGURES_DIR] if figures_created else [])]:
        print(f"  {path}")


def analyze_workbook(openpyxl_module, yaml_module, plt, categories, ambiguities,
                     macroblock_labels, dictionary_version, run_id) -> dict[str, Any]:
    global RUN_DIR, REPORTS_DIR, FIGURES_DIR, WORK_DIR, THEMATIC_DIR
    visual = Visualization.from_config(ANALYSIS_CONFIG)
    configure_workbook_sources(openpyxl_module)
    print(tr('Input file: {0}; worksheets: {1}', INPUT_FILE.name, ', '.join(SHEET_NAMES)))
    REPORTS_DIR = RUN_DIR / "reports"
    FIGURES_DIR = RUN_DIR / "figures"
    WORK_DIR = RUN_DIR / "tables"
    THEMATIC_DIR = RUN_DIR / "thematic_exports"
    ensure_directories()

    print(tr('2. Reading and checking the workbook...'))
    records, issues, _headers = read_records(openpyxl_module)
    for source in sorted({r.source_id for r in records}):
        subset = [r for r in records if r.source_id == source and r.status == "case"]
        missing_pages = sum(not r.pages_raw for r in subset)
        if subset and missing_pages and not SOURCE_CONFIG[subset[0].sheet_name].get("pages_expected", True):
            issues.append(Issue("WARNING", None, "", tr('Folio count'), str(missing_pages),
                                tr('{0}: folio counts are missing for {1} titles; consolidated warning.', source, missing_pages), subset[0].sheet_name))
    print(tr('   Rows read: {0}', len(records)))

    print(tr('3. Thematic classification...'))
    macroblock_order = list(macroblock_labels)
    classify_records(records, categories, ambiguities, macroblock_order)

    roots = REPORTS_DIR, FIGURES_DIR, WORK_DIR
    scopes = {source: [r for r in records if r.source_id == source]
              for source in sorted({r.source_id for r in records})}
    scopes["combined"] = records
    summary_rows = []
    for scope, subset in scopes.items():
        print(tr('4–7. Tables, charts and report: {0}...', scope), flush=True)
        REPORTS_DIR, FIGURES_DIR, WORK_DIR = [p / scope for p in roots]
        ensure_directories()
        sheets = {r.sheet_name for r in subset}
        scoped_issues = [i for i in issues if i.sheet_name in sheets or not i.sheet_name] if scope != "combined" else issues
        table_data = create_service_tables(subset, categories)
        sheets_for_map = chart_sheet_order(subset)
        labels = {sheet: configured_description_label(sheet) for sheet in sheets_for_map}
        colors = chart_sheet_colors(sheets_for_map)
        scope_title = "Спільний зріз" if scope == "combined" else scope
        table_data["terminology"] = write_terminology_report(
            table_data["active"], sheets_for_map,
            labels,
            colors, get_decade,
            WORK_DIR, FIGURES_DIR,
            scope_title,
            visual=visual,
        )
        table_data["theme_links"] = write_theme_links(
            table_data["active"], sheets_for_map,
            labels,
            categories, macroblock_labels, WORK_DIR, FIGURES_DIR,
            scope_title,
            visual=visual,
        )
        write_error_log(scoped_issues, subset)
        figures_created = create_figures(plt, subset, categories, table_data, visual)
        write_geography_maps(
            FIGURES_DIR, table_data["geography"]["rows"], sheets_for_map,
            labels,
            colors,
            scope_title,
            visual=visual,
        )
        write_analysis_report(subset, scoped_issues, categories, macroblock_labels,
                              table_data, figures_created, dictionary_version)
        cases = table_data["active"]
        summary_rows.append({"source": scope, "titles": len(cases),
                             "subject": sum(bool(r.categories) for r in cases),
                             "context_only": len(table_data["context_only"]),
                             "no_evidence": len(table_data["unclassified"]),
                             "missing_dates": sum(not r.dates_raw for r in cases),
                             "missing_pages": sum(r.pages is None for r in cases)})
    write_csv(roots[2] / "source_summary.csv", list(summary_rows[0]), summary_rows)
    print(tr('8. Exporting thematic XLSX/CSV selections...'), flush=True)
    write_combined_indexes(records, categories, roots[2])
    export_manifest = export_thematic_selections(
        openpyxl_module, records, categories
    )

    tracked = sorted({INPUT_FILE, PRESENTATION_CATALOG, GAZETTEER, *BASE_DIR.glob("*.py"),
                      *CONFIG_DIR.glob("*.yaml"), *CONFIG_DIR.glob("*.json"),
                      *DICTIONARIES_DIR.glob("*.yaml"),
                      *(BASE_DIR / "maps").glob("*.html"),
                      *(BASE_DIR / "maps").glob("*.geojson")})
    manifest = {
        "status": "complete",
        "script_version": SCRIPT_VERSION,
        "dictionary_version": dictionary_version,
        "document_type_rules_version": DOCUMENT_TYPE_RULES_VERSION,
        "terminology_rules_version": TERMINOLOGY_RULES_VERSION,
        "geography_rules_version": load_places()[0],
        "run_id": run_id,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "openpyxl": openpyxl_module.__version__,
        "pyyaml": yaml_module.__version__,
        "visualization": visual.metadata(),
        "report_language": visual.language,
        "analysis_languages": {code: analysis_languages().metadata(code) for code in sorted({r.language for r in records})},
        "configured_sheets": list(SHEET_NAMES),
        "sources": SOURCE_CONFIG,
        "header_rows": HEADER_ROWS_BY_SHEET,
        "enabled_categories": [category.id for category in categories],
        "source_summary": summary_rows,
        "thematic_exports": export_manifest,
        "sha256": {
            str(path.relative_to(BASE_DIR) if path.is_relative_to(BASE_DIR) else path): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in tracked
        },
    }
    write_html_report(RUN_DIR, INPUT_FILE.name, scopes, issues,
                      SCRIPT_VERSION, dictionary_version, macroblock_labels, visual=visual,
                      language_registry=analysis_languages(),
                      manifest_path=RUN_DIR / "run_manifest.json")
    manifest["outputs"] = sorted(path.relative_to(RUN_DIR).as_posix()
                                 for path in RUN_DIR.rglob("*") if path.is_file())
    (RUN_DIR / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(tr('HTML report:            {0}', RUN_DIR / 'report.html'))
    print_summary(records, issues, table_data, figures_created)
    print(tr('Run ID: {0}. Earlier outputs are retained.', run_id))
    print(tr('Workbook output folder:     {0}', RUN_DIR))
    return {"file": INPUT_FILE.name, "folder": RUN_DIR.name,
            "status": "complete", "sheets": len(SHEET_NAMES),
            "cases": next(row["titles"] for row in summary_rows if row["source"] == "combined"),
            "message": ""}


def main() -> None:
    global INPUT_FILE, RUN_DIR
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    print(tr('=== ARCHIVAL FINDING AID ANALYSIS — {0} ===', SCRIPT_VERSION))
    print(tr('Project folder: {0}', BASE_DIR))
    openpyxl_module, yaml_module, plt = load_dependencies()
    configure_analysis(yaml_module)
    workbooks = input_workbooks()
    print(tr('Workbooks to analyse: {0}', len(workbooks)))
    categories, ambiguities, macroblock_labels, dictionary_version = load_dictionaries(yaml_module)
    LANGUAGE_CATEGORIES.clear()
    LANGUAGE_AMBIGUITIES.clear()
    LANGUAGE_CATEGORIES["uk"] = categories
    LANGUAGE_AMBIGUITIES["uk"] = ambiguities
    for language in analysis_languages().languages:
        if language == "uk":
            continue
        loaded, language_ambiguities, _, _ = load_dictionaries(yaml_module, language)
        LANGUAGE_CATEGORIES[language] = loaded
        LANGUAGE_AMBIGUITIES[language] = language_ambiguities
    batch_dir = OUTPUTS_DIR / run_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    occupied = set()
    for index, path in enumerate(workbooks, 1):
        INPUT_FILE = path
        RUN_DIR = batch_dir / workbook_folder(path, occupied)
        print(f"\n[{index}/{len(workbooks)}] {path.name}", flush=True)
        try:
            summary.append(analyze_workbook(
                openpyxl_module, yaml_module, plt, categories, ambiguities,
                macroblock_labels, dictionary_version, run_id,
            ))
        except Exception as error:
            RUN_DIR.mkdir(parents=True, exist_ok=True)
            (RUN_DIR / "failure.txt").write_text(
                f"{type(error).__name__}: {error}\n\n{traceback.format_exc()}", encoding="utf-8"
            )
            summary.append({"file": path.name, "folder": RUN_DIR.name,
                            "status": "failed", "sheets": "", "cases": "",
                            "message": str(error)})
            print(tr('Workbook failed: {0}', error), flush=True)
    write_csv(batch_dir / "run_summary.csv",
              ["file", "folder", "status", "sheets", "cases", "message"], summary)
    print(tr('\nBatch summary: {0}', batch_dir / 'run_summary.csv'))
    if any(row["status"] == "failed" for row in summary):
        raise RuntimeError(tr('Some workbooks failed; see run_summary.csv and failure.txt'))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print(tr('\nFATAL ERROR'))
        print(str(error))
        print(tr('\nTechnical details:'))
        traceback.print_exc()
        raise SystemExit(1)
