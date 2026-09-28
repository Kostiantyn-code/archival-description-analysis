"""Co-classification of case titles by subject categories and macroblocks."""
from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from models import Category, Record


TEMPLATE = Path(__file__).resolve().parent / "maps" / "theme-links-template.html"
SUMMARY_FIELDS = (
    "scope", "description", "level", "theme_a_id", "theme_a", "theme_b_id",
    "theme_b", "titles_total", "theme_a_titles", "theme_b_titles",
    "shared_titles", "relative_frequency",
)
CASE_FIELDS = (
    "record_uid", "sheet_name", "archive", "fond", "inventory", "case_id",
    "level", "theme_a_id", "theme_b_id", "title",
)


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def _example(record: Record) -> dict[str, str]:
    return {
        "ref": (f"{record.source_archive}, ф. {record.source_fond}, "
                f"оп. {record.source_inventory}, "
                f"спр. {record.case_id_normalized or record.case_id_raw}"),
        "title": record.title_raw,
        "archive": record.source_archive,
    }


def _examples(records: list[Record]) -> list[dict[str, str]]:
    """Include distinct archives when possible and avoid repeating one case."""
    selected: list[Record] = []
    archives: set[str] = set()
    for record in records:
        if record.source_archive not in archives:
            selected.append(record)
            archives.add(record.source_archive)
        if len(selected) == 3:
            break
    for record in records:
        if len(selected) == 3:
            break
        if record not in selected:
            selected.append(record)
    return [_example(record) for record in selected]


def write_theme_links(
    records: list[Record], sheets: list[str], sheet_labels: dict[str, str],
    categories: list[Category], macroblock_labels: dict[str, str],
    tables_dir: Path, figures_dir: Path, scope_title: str,
) -> dict[str, int]:
    """Write one standalone network and auditable pair counts per description.

    Only subject assignments from ``record.categories`` and their macroblocks
    participate. Context-only category mentions are deliberately excluded.
    """
    active = [record for record in records if record.status == "case"]
    configured_categories = {category.id: category.label for category in categories}
    blocks = dict(macroblock_labels)
    groups = {
        "cat": configured_categories,
        "block": blocks,
    }
    breakdown: dict[str, dict] = {}
    summary_rows: list[dict] = []
    case_rows: list[dict] = []

    for sheet in ["__all__", *sheets]:
        subset = active if sheet == "__all__" else [r for r in active if r.sheet_name == sheet]
        title = "Усі описи" if sheet == "__all__" else sheet_labels[sheet]
        breakdown[sheet] = {}
        for level, known in groups.items():
            key = "categories" if level == "cat" else "macroblocks"
            node_counts: Counter[str] = Counter()
            pair_counts: Counter[tuple[str, str]] = Counter()
            pair_records: dict[tuple[str, str], list[Record]] = defaultdict(list)
            multi = 0
            for record in subset:
                ids = sorted(set(getattr(record, key)) & known.keys())
                node_counts.update(ids)
                multi += len(ids) > 1
                for pair in combinations(ids, 2):
                    pair_counts[pair] += 1
                    pair_records[pair].append(record)
                    if sheet != "__all__":
                        case_rows.append({
                            "record_uid": f"{record.source_id}:{record.sheet_name}:{record.excel_row}",
                            "sheet_name": record.sheet_name, "archive": record.source_archive,
                            "fond": record.source_fond, "inventory": record.source_inventory,
                            "case_id": record.case_id_normalized or record.case_id_raw,
                            "level": level, "theme_a_id": pair[0], "theme_b_id": pair[1],
                            "title": record.title_raw,
                        })
            edges = []
            for a, b in combinations(known, 2):
                pair = tuple(sorted((a, b)))
                shared = pair_counts[pair]
                denominator = node_counts[a] * node_counts[b]
                lift = shared * len(subset) / denominator if denominator else None
                summary_rows.append({
                    "scope": sheet, "description": title, "level": level,
                    "theme_a_id": a, "theme_a": known[a],
                    "theme_b_id": b, "theme_b": known[b],
                    "titles_total": len(subset), "theme_a_titles": node_counts[a],
                    "theme_b_titles": node_counts[b], "shared_titles": shared,
                    "relative_frequency": f"{lift:.3f}" if lift is not None else "",
                })
                if shared:
                    edges.append({
                        "a": a, "b": b, "count": shared,
                        "lift": round(lift, 3),
                        "examples": _examples(pair_records[pair]),
                    })
            breakdown[sheet][level] = {
                "total": len(subset), "multi": multi,
                "nodes": dict(node_counts), "edges": edges,
            }

    _write_csv(tables_dir / "theme_links_by_description.csv", SUMMARY_FIELDS, summary_rows)
    _write_csv(tables_dir / "theme_link_cases.csv", CASE_FIELDS, case_rows)
    abbreviations = {
        "politics": "Політика", "public_administration": "Управління",
        "law_and_police": "Право і поліція", "military_affairs": "Військова справа",
        "economy": "Економіка", "population_and_society": "Населення",
        "personal_files": "Особові справи", "healthcare": "Здоров’я",
        "urban_infrastructure": "Інфраструктура", "education": "Освіта",
        "culture": "Культура і друк", "religion": "Релігія",
    }
    block_short = {
        "political": "Політика й управління",
        "socioeconomic": "Соціально-економічне",
        "cultural": "Культурне життя", "documentary": "Тип документації",
    }
    data = {
        "meta": {
            "cat": configured_categories,
            "short": {id_: abbreviations.get(id_, label[:21] + "…" if len(label) > 22 else label)
                      for id_, label in configured_categories.items()},
            "block": blocks,
            "blockShort": {id_: block_short.get(id_, label[:21] + "…" if len(label) > 22 else label)
                           for id_, label in blocks.items()},
            "catOrder": list(configured_categories),
            "catBlock": {category.id: category.macroblock for category in categories},
            "scopes": [["__all__", "Усі описи"], *[[s, sheet_labels[s]] for s in sheets]],
        },
        "scopes": breakdown,
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    page = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__DATA__", payload)
            .replace("__SCOPE__", html.escape(scope_title)))
    (figures_dir / "theme_links.html").write_text(page, encoding="utf-8")
    return {
        "titles": len(active), "multi": breakdown["__all__"]["cat"]["multi"],
        "category_pairs": len(breakdown["__all__"]["cat"]["edges"]),
    }
