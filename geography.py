"""Conservative matching of named settlements in archival case titles.

Locations are gazetteer entries, not inferred event sites. Do not silently
geocode an unknown title or interpret an administrative adjective as a city.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from language_packs import alias_hits, pack_content
import html
import json
from report_utils import json_for_script
from localization import Visualization

GAZETTEER = Path(__file__).resolve().parent / "config" / "geography.yaml"
BASEMAP = Path(__file__).resolve().parent / "maps" / "europe-basemap.geojson"


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float
    expression: re.Pattern[str]


BOUNDARY = r"[А-Яа-яЁёІЇЄҐіїєґA-Za-z0-9]"
NIKOLAEV_CONTEXT = re.compile(
    r"(?:^|[\s,(])(?:м\.|міст[аіоу]|город[аеуом]?|гор\.|г\.|"
    r"порт[аіуеом]?|у|в|із|з|из|от|до|по|через|між|между|при|біля)\s*$",
    re.I,
)
NIKOLAEV_EXPLICIT = re.compile(
    r"(?:^|[\s,(])(?:м\.|міст[аіоу]|город[аеуом]?|гор\.|г\.|порт[аіуеом]?)\s*$",
    re.I,
)
UNKNOWN_CONTEXT = re.compile(
    r"(?i)(?<!\w)(?:м\.|г\.|гор\.|міст(?:о|а|і|у|ах)|"
    r"город(?:а|е|у|ах)?|с\.|село|села|сел(?:і|а)|"
    r"фортец(?:я|і|ю|и|ь)|крепост(?:ь|и|ю)|порт(?:у|а|і|е|ом)?)"
    r"\s*((?-i:[А-ЯЁІЇЄҐ][а-яёіїєґ]+)(?:[- ](?-i:[А-ЯЁІЇЄҐ][а-яёіїєґ]+))?)"
)


@lru_cache(maxsize=1)
def load_places() -> tuple[str, tuple[Place, ...]]:
    config = yaml.safe_load(GAZETTEER.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("places"), list):
        raise ValueError("config/geography.yaml: очікується список places")
    found: set[str] = set()
    places = []
    for row in config["places"]:
        name = row["name"]
        if name in found:
            raise ValueError(f"Дубль географічної назви: {name}")
        found.add(name)
        lat, lon = float(row["lat"]), float(row["lon"])
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError(f"Некоректні координати: {name}")
        expression = re.compile(
            rf"(?<!{BOUNDARY})(?:{row['pattern']})(?!{BOUNDARY})", re.I
        )
        places.append(Place(name, lat, lon, expression))
    return str(config.get("version", "unknown")), tuple(places)


def find_places(
    title: str, places: tuple[Place, ...] | None = None, language: str = "uk"
) -> list[tuple[Place, str]]:
    """Return at most one mention per settlement per title."""
    if places is None:
        places = load_places()[1]
    if language not in {"uk", "ru"}:
        hits = alias_hits(title, language, "place_aliases")
        return [(place, hits[place.name]) for place in places if place.name in hits]
    matches = []
    for place in places:
        acceptable = []
        for hit in place.expression.finditer(title):
            if place.name == "Миколаїв" and hit.group().casefold().startswith(
                "николаев"
            ):
                before = title[max(0, hit.start() - 35) : hit.start()]
                if not NIKOLAEV_CONTEXT.search(before):
                    continue  # Also a surname; require a locative expression.
                if not NIKOLAEV_EXPLICIT.search(before) and re.match(
                    r"\s+[А-ЯЁІЇЄҐ][а-яёіїєґ]+", title[hit.end() :]
                ):
                    continue  # "Николаева Ивана": surname and given name.
            if place.name == "Керч" and title[hit.end() : hit.end() + 1] == "-":
                continue  # Kerch-Yenikale administrative institution.
            acceptable.append(hit)
        if acceptable:
            matches.append((place, acceptable[0].group()))
    return matches


def unknown_candidates(
    title: str, known: list[tuple[Place, str]], language: str = "uk"
) -> list[str]:
    """Explicit city/village/port prefixes whose names need manual review."""
    seen = set()
    result = []
    names = {expression.casefold() for _, expression in known}
    if language not in {"uk", "ru"}:
        prefixes = pack_content(language).get("place_prefixes", [])
        if not prefixes:
            return []
        pattern = re.compile(
            r"(?<!\w)(?:"
            + "|".join(re.escape(x) for x in prefixes)
            + r")\s+([^\W\d_]+(?:-[^\W\d_]+)*)",
            re.I,
        )
        for hit in pattern.finditer(title):
            candidate = hit.group(1)
            if (
                candidate[0].isupper()
                and candidate.casefold() not in names
                and candidate.casefold() not in seen
                and not find_places(candidate, language=language)
            ):
                result.append(candidate)
                seen.add(candidate.casefold())
        return result
    for hit in UNKNOWN_CONTEXT.finditer(title):
        candidate = hit.group(1)
        if candidate.casefold() in names or candidate.casefold() in seen:
            continue
        if find_places("м. " + candidate):
            continue
        seen.add(candidate.casefold())
        result.append(candidate)
    return result


MAP_TEMPLATE = Path(__file__).resolve().parent / "maps" / "map-template.html"
VIEWS = {
    "south": ("Південь України", [[44.1, 28.2], [48.5, 37.5]]),
    "europe": ("Європа", [[35.0, -12.0], [63.0, 50.0]]),
    "russia": ("Європейська частина РФ", [[43.0, 28.0], [62.5, 61.0]]),
}


def write_maps(
    destination: Path,
    mentions: list[dict[str, Any]],
    sheets: list[str],
    labels: dict[str, str],
    colors: dict[str, str],
    title: str,
    visual: Visualization | None = None,
) -> None:
    """Create three independent HTML files with embedded geography and data."""
    visual = visual or Visualization()
    destination.mkdir(parents=True, exist_ok=True)
    sites: dict[str, dict[str, Any]] = {}
    for row in mentions:
        name = row["place"]
        site = sites.setdefault(
            name,
            {
                "name": visual.label("places", name, name),
                "lat": row["latitude"],
                "lon": row["longitude"],
                "byDecade": {},
            },
        )
        for decade in ("all", str(row["decade"])):
            bucket = site["byDecade"].setdefault(
                decade, {"counts": [0] * len(sheets), "sample": [None] * len(sheets)}
            )
            index = sheets.index(row["sheet_name"])
            bucket["counts"][index] += 1
            if bucket["sample"][index] is None:
                bucket["sample"][index] = (
                    f"{row['archive']}, ф. {row['fond']}, оп. {row['inventory']}, "
                    f"спр. {row['case_id']}: {row['title'][:240]}"
                )
                if visual.language == "en":
                    bucket["sample"][index] = (
                        f"{visual.reference(row['archive'], row['fond'], row['inventory'])}, "
                        f"case file {row['case_id']}: {row['title'][:240]}"
                    )
    template = visual.template(MAP_TEMPLATE.read_text(encoding="utf-8"))
    basemap = json.loads(BASEMAP.read_text(encoding="utf-8"))
    decades = sorted(
        {str(row["decade"]) for row in mentions if row["decade"] != "unknown"}, key=int
    )
    common = {
        "__PLACES__": json_for_script(list(sites.values())),
        "__BASEMAP__": json_for_script(basemap),
        "__DECADES__": json_for_script(decades),
        "__LABELS__": json_for_script(
            [visual.description(s, labels[s]) for s in sheets]
        ),
        "__COLORS__": json_for_script([colors[s] for s in sheets]),
        "__BOUNDS__": json_for_script({key: val[1] for key, val in VIEWS.items()}),
        "__SCOPE__": html.escape(visual.text(title)),
    }
    for view, (name, _) in VIEWS.items():
        page = template
        for placeholder, value in common.items():
            page = page.replace(placeholder, value)
        page = page.replace(
            "__PAGE_TITLE__",
            html.escape(
                f"{visual.text('Geographical mentions')} · {visual.text(name)}"
            ),
        )
        page = page.replace("__VIEW_NAME__", html.escape(visual.text(name)))
        page = page.replace("__INITIAL_VIEW__", json_for_script(view))
        (destination / f"geography_{view}.html").write_text(page, encoding="utf-8")
