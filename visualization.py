"""Presentation-only localization; never changes source records or CSV data."""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


CATALOG = Path(__file__).resolve().parent / "config" / "visualization.en.json"


@lru_cache(maxsize=1)
def english_catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Visualization:
    language: str = "uk"
    bilingual_labels: bool = False
    label_overrides: dict = field(default_factory=dict)

    @classmethod
    def from_config(cls, config: dict) -> "Visualization":
        options = config.get("visualization", {})
        if not isinstance(options, dict):
            raise ValueError("visualization: expected a mapping")
        language = options.get("language", "uk")
        bilingual = options.get("bilingual_labels", False)
        overrides = options.get("label_overrides", {})
        if language not in ("uk", "en"):
            raise ValueError("visualization.language: expected uk or en")
        if not isinstance(bilingual, bool):
            raise ValueError("visualization.bilingual_labels: expected true or false")
        if not isinstance(overrides, dict) or any(
            not isinstance(group, str) or not isinstance(values, dict)
            or any(not isinstance(key, str) or not isinstance(value, str)
                   for key, value in values.items())
            for group, values in overrides.items()
        ):
            raise ValueError("visualization.label_overrides: expected groups of string labels")
        return cls(language, bilingual, overrides)

    @property
    def bilingual(self) -> bool:
        return self.language == "en" and self.bilingual_labels

    def text(self, original: str) -> str:
        """Translate program captions, never arbitrary archival text."""
        if self.language == "uk":
            return original
        return english_catalog()["ui"].get(original, original)

    def label(self, group: str, key: str, original: str) -> str:
        """Use stable IDs for categories/terms and exact names for places/archives."""
        if self.language == "uk":
            return original
        translated = self.label_overrides.get(group, {}).get(
            key, english_catalog().get(group, {}).get(key, original))
        if self.bilingual and translated != original:
            return f"{translated} ({original})"
        return translated

    def reference(self, archive: str, fond: str, inventory: str) -> str:
        archive = self.label("archives", archive, archive)
        if self.language == "uk":
            return archive + (f", ф. {fond}" if fond else "") + (f": опис {inventory}" if inventory else "")
        return archive + (f", fond {fond}" if fond else "") + (f": inventory {inventory}" if inventory else "")

    def description(self, key: str, original: str) -> str:
        if self.language == "uk":
            return original
        if key in self.label_overrides.get("descriptions", {}):
            return self.label("descriptions", key, original)
        # These strings are generated archival references, not case titles.
        archive, *rest = re.split(r"(, ф\. |: опис |, оп\. )", original, maxsplit=1)
        reference = self.label("archives", archive, archive) + "".join(rest)
        return (reference.replace(", ф. ", ", fond ")
                .replace(": опис ", ": inventory ").replace(", оп. ", ", inventory "))

    def template(self, source: str) -> str:
        """Localize trusted template text BEFORE embedding any source data.

        One regex pass prevents replacement of text introduced by a translation.
        HTML text and JavaScript literals are escaped in their own contexts.
        Original templates are returned byte-for-byte in the default mode.
        """
        if self.language == "uk":
            return source
        translations = english_catalog()["ui"]
        pattern = re.compile(r"(?<!\w)(?:" + "|".join(
            re.escape(key) for key in sorted(translations, key=len, reverse=True)
        ) + r")(?!\w)")

        def javascript(value: str) -> str:
            return (json.dumps(value, ensure_ascii=False)[1:-1]
                    .replace("'", r"\u0027").replace("`", r"\u0060")
                    .replace("$", r"\u0024").replace("<", r"\u003c")
                    .replace("\u2028", r"\u2028").replace("\u2029", r"\u2029"))

        parts = re.split(r"(<script\b[^>]*>.*?</script>)", source, flags=re.S | re.I)
        for index, part in enumerate(parts):
            escape = javascript if part.lower().startswith("<script") else html.escape
            parts[index] = pattern.sub(lambda match: escape(translations[match.group()]), part)
        return "".join(parts).replace('lang="uk"', 'lang="en"').replace("'uk-UA'", "'en-GB'")

    def metadata(self) -> dict:
        return {"language": self.language, "bilingual_labels": self.bilingual_labels,
                "label_overrides": self.label_overrides}
