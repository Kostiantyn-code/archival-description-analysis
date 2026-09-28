"""Conservative matching of named settlements in archival case titles.

Locations are gazetteer entries, not inferred event sites. Do not silently
geocode an unknown title or interpret an administrative adjective as a city.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


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


def find_places(title: str, places: tuple[Place, ...] | None = None) -> list[tuple[Place, str]]:
    """Return at most one mention per settlement per title."""
    if places is None:
        places = load_places()[1]
    matches = []
    for place in places:
        acceptable = []
        for hit in place.expression.finditer(title):
            if place.name == "Миколаїв" and hit.group().casefold().startswith("николаев"):
                before = title[max(0, hit.start() - 35):hit.start()]
                if not NIKOLAEV_CONTEXT.search(before):
                    continue  # Also a surname; require a locative expression.
                if not NIKOLAEV_EXPLICIT.search(before) and re.match(
                    r"\s+[А-ЯЁІЇЄҐ][а-яёіїєґ]+", title[hit.end():]
                ):
                    continue  # "Николаева Ивана": surname and given name.
            if place.name == "Керч" and title[hit.end():hit.end() + 1] == "-":
                continue  # Kerch-Yenikale administrative institution.
            acceptable.append(hit)
        if acceptable:
            matches.append((place, acceptable[0].group()))
    return matches


def unknown_candidates(title: str, known: list[tuple[Place, str]]) -> list[str]:
    """Explicit city/village/port prefixes whose names need manual review."""
    seen = set()
    result = []
    names = {expression.casefold() for _, expression in known}
    for hit in UNKNOWN_CONTEXT.finditer(title):
        candidate = hit.group(1)
        if candidate.casefold() in names or candidate.casefold() in seen:
            continue
        if find_places("м. " + candidate):
            continue
        seen.add(candidate.casefold())
        result.append(candidate)
    return result
