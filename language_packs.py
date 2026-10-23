"""One declarative file per analysis language; English defines shared concepts.

UDC numbers are broader subject anchors. Search forms and scoring stay separate
from the language used to present the report.
"""

from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import unicodedata
import yaml
from models import CATEGORY_RULE_FIELDS

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "dictionaries" / "en.yaml"


class UniqueKeyLoader(yaml.SafeLoader):
    """Do not silently overwrite duplicate vocabulary entries."""


def _unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping
)


def read_mapping(path: Path) -> dict:
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping")
    return data


@dataclass
class LanguageRegistry:
    root: Path
    languages: dict
    reference: dict

    @classmethod
    def load(cls, path: Path | None = None):
        reference_path = Path(path) if path is not None else REGISTRY
        packs = {}
        for file in sorted(reference_path.parent.glob("*.yaml")):
            if not re.fullmatch(r"[a-z]{2,3}", file.stem):
                continue
            pack = read_mapping(file)
            code = pack.get("language")
            if code != file.stem or pack.get("schema_version") != 1:
                raise ValueError(f"{file}: expected schema 1 and language {file.stem}")
            if pack.get("matching") not in {"uk_light", "ru_light", "unicode_exact"}:
                raise ValueError(f"{code}: unknown matching profile")
            if (
                pack["matching"] in {"uk_light", "ru_light"}
                and pack["matching"] != code + "_light"
            ):
                raise ValueError(
                    f"{code}: matching profile belongs to another language"
                )
            if pack.get("vocabulary") not in {"reference", "weighted_rules"}:
                raise ValueError(
                    f"{code}: expected reference concepts or weighted_rules"
                )
            if not isinstance(pack.get("version"), str) or not isinstance(
                pack.get("validation_status"), str
            ):
                raise ValueError(f"{code}: version and validation_status are required")
            for field in (
                "detection_terms",
                "year_words",
                "withdrawn_terms",
                "place_prefixes",
            ):
                cls._terms(pack.get(field, []), f"{code}:{field}")
            packs[code] = {**pack, "_path": file}
        if "en" not in packs or packs["en"]["vocabulary"] != "reference":
            raise ValueError("An English reference vocabulary is required")
        reference = packs["en"]
        concepts = reference.get("concepts")
        if not isinstance(concepts, list) or not concepts:
            raise ValueError("The English vocabulary must define concepts")
        seen = set()
        for concept in concepts:
            if not isinstance(concept, dict):
                raise ValueError("A concept must be a mapping")
            cid = concept.get("id", "")
            if not re.fullmatch(r"[a-z0-9_]+", cid) or cid in seen:
                raise ValueError(f"Invalid or duplicate concept ID: {cid}")
            seen.add(cid)
            if concept.get("kind") not in {"subject", "context"}:
                raise ValueError(f"{cid}: expected subject or context")
            if not concept.get("label_en") or not concept.get("scope_note"):
                raise ValueError(f"{cid}: label and scope note are required")
            codes = concept.get("udc_codes")
            if not isinstance(codes, list) or any(
                not isinstance(c, str) or not re.fullmatch(r"[0-9./]+", c)
                for c in codes
            ):
                raise ValueError(f"{cid}: UDC codes must be strings")
            if concept.get("udc_relation") != (
                "broader_subject_anchor" if codes else "not_assigned"
            ):
                raise ValueError(f"{cid}: inconsistent UDC relation")
            cls._terms(concept.get("terms"), cid)
            if not concept["terms"]:
                raise ValueError(f"{cid}: English search terms are required")
        rule_ids = set()
        for rule in reference.get("rules", []):
            rid = rule.get("id", "")
            if not re.fullmatch(r"[a-z0-9_]+", rid) or rid in rule_ids:
                raise ValueError(f"Invalid or duplicate rule ID: {rid}")
            rule_ids.add(rid)
            for field in ("all", "any"):
                if (
                    not isinstance(rule.get(field), list)
                    or not rule[field]
                    or set(rule[field]) - seen
                ):
                    raise ValueError(f"{rid}: unknown or missing concept IDs")
        return cls(reference_path.parent.parent, packs, reference)

    @staticmethod
    def _terms(terms, identifier):
        if not isinstance(terms, list) or any(
            not isinstance(t, str) or not t.strip() for t in terms
        ):
            raise ValueError(f"{identifier}: expected nonempty strings in a list")
        if len(terms) != len(
            {unicodedata.normalize("NFC", t).casefold() for t in terms}
        ):
            raise ValueError(f"{identifier}: duplicate terms")

    def compile(self, language, category_index):
        if language not in self.languages:
            raise ValueError(f"No analysis dictionary for: {language}")
        pack = self.languages[language]
        categories = {row["id"] for row in category_index["categories"]}
        if pack["vocabulary"] == "weighted_rules":
            rules = pack.get("categories", {})
            if not isinstance(rules, dict) or set(rules) != categories:
                raise ValueError(
                    f"{language}: weighted categories must match the category index"
                )
            for cid, data in rules.items():
                for field in CATEGORY_RULE_FIELDS:
                    if field != "context_rules":
                        self._terms(data.get(field, []), f"{language}:{cid}:{field}")
                for rule in data.get("context_rules", []):
                    for field in ("all", "any"):
                        self._terms(rule.get(field, []), f"{language}:{cid}:{field}")
            return rules, pack
        ids = {c["id"]: c for c in self.reference["concepts"]}
        aliases = (
            {cid: c["terms"] for cid, c in ids.items()}
            if language == "en"
            else pack.get("concepts", {})
        )
        if not isinstance(aliases, dict) or set(aliases) != set(ids):
            raise ValueError(
                f"{language}: concept IDs must match English; use [] for an unavailable equivalent"
            )
        if (
            language != "en"
            and pack.get("reference_version") != self.reference["version"]
        ):
            raise ValueError(f"{language}: reference version mismatch")
        for section in ("document_types", "terminology", "place_aliases"):
            values = pack.get(section, {})
            if not isinstance(values, dict) or set(values) - set(
                self.reference.get(section, {})
            ):
                raise ValueError(f"{language}: unknown {section} IDs")
            for key, terms in values.items():
                self._terms(terms, f"{language}:{section}:{key}")
        compiled = {cid: {"concepts": [], "concept_rules": []} for cid in categories}
        for cid, concept in ids.items():
            self._terms(aliases[cid], f"{language}:{cid}")
            category = concept["category"]
            if category is not None and category not in categories:
                raise ValueError(f"{cid}: unknown category {category}")
            if category is not None:
                compiled[category]["concepts"].append(
                    {**concept, "terms": aliases[cid]}
                )
        for rule in self.reference.get("rules", []):
            if rule["category"] not in categories:
                raise ValueError(f"Unknown rule category: {rule['category']}")
            target = compiled[rule["category"]]
            present = {c["id"] for c in target["concepts"]}
            for cid in rule["all"] + rule["any"]:
                if cid not in present:
                    target["concepts"].append({**ids[cid], "terms": aliases[cid]})
                    present.add(cid)
            target["concept_rules"].append(rule)
        return compiled, pack

    def modules(self, language):
        pack = self.languages.get(language, {})
        return {
            module: language in {"uk", "ru"} or section in pack
            for module, section in [
                ("document_types", "document_types"),
                ("terminology", "terminology"),
                ("geography", "place_aliases"),
            ]
        }

    def metadata(self, language):
        pack = self.languages.get(language)
        if not pack:
            return {"language": language, "status": "unsupported"}
        return {
            "language": language,
            "version": pack["version"],
            "validation_status": pack["validation_status"],
            "matching": pack["matching"],
            "reference_language": "en",
            "reference_version": self.reference["version"],
            "alignment": (
                "reference_concepts"
                if pack["vocabulary"] == "reference"
                else "language_specific_rules"
            ),
            "source": pack["_path"].relative_to(self.root).as_posix(),
            "ancillary_modules": self.modules(language),
        }

    def source_paths(self):
        return [pack["_path"] for pack in self.languages.values()]

    def notices(self, languages):
        languages = set(languages)
        unsupported = sorted(languages - set(self.languages))
        if unsupported:
            yield (
                "Для мов {0} тематичні словники відсутні. Класифікацію пропущено; нульове покриття не характеризує зміст документів.",
                ", ".join(unsupported),
            )
        draft = sorted(
            code
            for code in languages
            if code in self.languages
            and self.languages[code]["validation_status"] != "independently_validated"
        )
        if draft:
            yield (
                "Словники мов {0} є робочими та не пройшли незалежної експертної валідації. Покриття класифікацією не є оцінкою точності.",
                ", ".join(draft),
            )
        for module, message in {
            "document_types": "Для мов {0} не підключено словник типів документів. Нульові значення не доводять відсутності згадок.",
            "terminology": "Для мов {0} не підключено термінологічний словник. Нульові значення не доводять відсутності згадок.",
            "geography": "Для мов {0} не підключено географічний словник. Нульові значення не доводять відсутності згадок.",
        }.items():
            missing = sorted(
                code
                for code in languages
                if code in self.languages and not self.modules(code)[module]
            )
            if missing:
                yield (message, ", ".join(missing))


@lru_cache(maxsize=32)
def pack_content(language):
    registry = LanguageRegistry.load()
    if language not in registry.languages:
        return {}
    pack = registry.languages[language]
    if pack["vocabulary"] == "weighted_rules":
        return {}
    content = pack
    return {**content, "_ancillary_modules": registry.modules(language)}


@lru_cache(maxsize=128)
def lexical_patterns(language, section):
    patterns = {}
    content = pack_content(language)
    module = "geography" if section == "place_aliases" else section
    if not content.get("_ancillary_modules", {}).get(module, False):
        return patterns
    for key, terms in content.get(section, {}).items():
        if terms:
            variants = []
            for term in terms:
                words = re.findall(r"[^\W_]+", unicodedata.normalize("NFC", term))
                variants.append(r"[^\w_]+".join(re.escape(word) for word in words))
            patterns[key] = re.compile(
                r"(?<!\w)(?:" + "|".join(variants) + r")(?!\w)", re.I
            )
    return patterns


def alias_hits(title, language, section):
    title = unicodedata.normalize("NFC", title)
    return {
        key: hit.group()
        for key, pattern in lexical_patterns(language, section).items()
        if (hit := pattern.search(title))
    }


@lru_cache(maxsize=32)
def structural_patterns(language):
    pack = LanguageRegistry.load().languages.get(language, {})
    words = pack.get("year_words", [])
    year = (
        re.compile(
            r"^\s*(?:1[5-9]|20)\d{2}\s*\.?\s*(?:"
            + "|".join(re.escape(word) for word in words)
            + r")\.?\s*$",
            re.I,
        )
        if words
        else None
    )
    terms = pack.get("withdrawn_terms", [])
    withdrawn = (
        re.compile(
            r"^\s*(?:" + "|".join(re.escape(term) for term in terms) + r")(?=$|[^\w])",
            re.I,
        )
        if terms
        else None
    )
    return year, withdrawn


def personal_section_matches(title, language):
    content = pack_content(language)
    if language == "en":
        terms = next(
            (
                c["terms"]
                for c in content.get("concepts", [])
                if c["id"] == "personal_documentation"
            ),
            [],
        )
    else:
        terms = content.get("concepts", {}).get("personal_documentation", [])
    return any(
        re.match(r"^\s*" + re.escape(term) + r"(?!\w)", title, re.I) for term in terms
    )


def evaluate_concepts(matches, concepts, rules, category_id):
    """Score each shared concept once; preserve matched lexical evidence."""
    hits = {c["id"]: [term for term in c["terms"] if matches(term)] for c in concepts}
    score, subject, context = 0, [], []
    for concept in concepts:
        forms = hits[concept["id"]]
        if not forms or concept["category"] != category_id:
            continue
        evidence = "concept:" + concept["id"] + ": " + " | ".join(forms)
        if concept["kind"] == "subject":
            score += 3
            subject.append(evidence)
        else:
            context.append(evidence)
    for rule in rules:
        if all(hits[cid] for cid in rule["all"]) and any(
            hits[cid] for cid in rule["any"]
        ):
            score += 3
            used = [cid for cid in rule["all"] + rule["any"] if hits[cid]]
            subject.append(
                "concept_rule:"
                + rule["id"]
                + ": "
                + "; ".join(cid + "=" + " | ".join(hits[cid]) for cid in used)
            )
    return score, subject, context
