"""Standalone maps for the geographies mentioned in an archival workbook."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from geography import BASEMAP
from report_utils import json_for_script
from visualization import Visualization


TEMPLATE = Path(__file__).resolve().parent / "maps" / "map-template.html"
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
        site = sites.setdefault(name, {
            "name": visual.label("places", name, name), "lat": row["latitude"], "lon": row["longitude"],
            "byDecade": {},
        })
        for decade in ("all", str(row["decade"])):
            bucket = site["byDecade"].setdefault(decade, {
                "counts": [0] * len(sheets), "sample": [None] * len(sheets)
            })
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
    template = visual.template(TEMPLATE.read_text(encoding="utf-8"))
    basemap = json.loads(BASEMAP.read_text(encoding="utf-8"))
    decades = sorted({str(row["decade"]) for row in mentions
                      if row["decade"] != "unknown"}, key=int)
    common = {
        "__PLACES__": json_for_script(list(sites.values())),
        "__BASEMAP__": json_for_script(basemap),
        "__DECADES__": json_for_script(decades),
        "__LABELS__": json_for_script([visual.description(s, labels[s]) for s in sheets]),
        "__COLORS__": json_for_script([colors[s] for s in sheets]),
        "__BOUNDS__": json_for_script({key: val[1] for key, val in VIEWS.items()}),
        "__SCOPE__": html.escape(visual.text(title)),
    }
    for view, (name, _) in VIEWS.items():
        page = template
        for placeholder, value in common.items():
            page = page.replace(placeholder, value)
        page = page.replace("__PAGE_TITLE__", html.escape(f"{visual.text('Географічні згадки')} · {visual.text(name)}"))
        page = page.replace("__VIEW_NAME__", html.escape(visual.text(name)))
        page = page.replace("__INITIAL_VIEW__", json_for_script(view))
        (destination / f"geography_{view}.html").write_text(page, encoding="utf-8")
