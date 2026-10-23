"""Declarative analysis languages, English reference concepts and UDC anchors.

This module never selects the report/interface language. New packs contain data,
not Python modules; no arbitrary code is imported from the registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache
import re
import unicodedata

import yaml

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "config" / "languages.yaml"


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently overwriting translations."""


def _unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def read_mapping(path: Path) -> dict:
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping")
    return data


def local_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Language-pack paths must stay inside the project")
    return path


@dataclass
class LanguageRegistry:
    root: Path
    data: dict
    reference: dict

    @classmethod
    def load(cls, path: Path | None = None):
        path = Path(path) if path is not None else REGISTRY
        data = read_mapping(path)
        root = path.parent.parent
        if data.get("schema_version") != 1 or data.get("reference_language") != "en":
            raise ValueError("languages.yaml: expected schema_version 1 and reference_language en")
        languages = data.get("languages")
        if not isinstance(languages, dict) or not {"en", "uk", "ru"} <= set(languages):
            raise ValueError("languages.yaml: languages must be a nonempty mapping")
        for code, pack in languages.items():
            if not re.fullmatch(r"[a-z]{2,3}", code) or not isinstance(pack, dict):
                raise ValueError("languages.yaml: invalid language entry")
            if pack.get("vocabulary") not in {"reference", "legacy"}:
                raise ValueError(f"{code}: vocabulary must be reference or legacy")
            if pack.get("vocabulary") == "legacy" and code not in {"uk", "ru"}:
                raise ValueError(f"{code}: legacy vocabulary is reserved for uk/ru")
            if code in {"uk", "ru"} and pack.get("matching") != "legacy_" + code:
                raise ValueError(f"{code}: legacy matching profile must match its language")
            if pack.get("matching") not in {"legacy_uk", "legacy_ru", "unicode_exact"}:
                raise ValueError(f"{code}: unsupported matching profile")
            if pack.get("matching") in {"legacy_uk", "legacy_ru"} and code not in {"uk", "ru"}:
                raise ValueError(f"{code}: legacy matching is reserved for uk/ru")
            if not isinstance(pack.get("version"), str) or not isinstance(pack.get("validation_status"), str):
                raise ValueError(f"{code}: version and validation_status are required")
            for field in ("detection_terms", "year_words", "withdrawn_terms"):
                cls._terms(pack.get(field, []), f"{code}:{field}")
            modules = pack.get("ancillary_modules", {})
            if not isinstance(modules, dict) or set(modules) - {"document_types", "terminology", "geography"} or any(not isinstance(v, bool) for v in modules.values()):
                raise ValueError(f"{code}: invalid ancillary_modules settings")
        reference = read_mapping(local_path(root, data["reference_file"]))
        if reference.get("language") != "en" or reference.get("schema_version") != 1:
            raise ValueError("Reference vocabulary must use schema 1 and language en")
        concepts = reference.get("concepts", [])
        if not isinstance(concepts, list) or not concepts:
            raise ValueError("Reference vocabulary has no concepts")
        seen = set()
        for concept in concepts:
            if not isinstance(concept, dict):
                raise ValueError("Each reference concept must be a mapping")
            cid = concept.get("id", "")
            if not re.fullmatch(r"[a-z0-9_]+", cid) or cid in seen:
                raise ValueError(f"Invalid or duplicate reference concept: {cid}")
            seen.add(cid)
            if concept.get("kind") not in {"subject", "context"}:
                raise ValueError(f"{cid}: expected subject or context")
            if not isinstance(concept.get("udc_codes"), list) or not all(isinstance(x, str) and re.fullmatch(r"[0-9./]+", x) for x in concept["udc_codes"]):
                raise ValueError(f"{cid}: UDC codes must be strings")
            cls._terms(concept.get("terms"), cid)
            if not concept["terms"] or not concept.get("scope_note") or not concept.get("label_en"):
                raise ValueError(f"{cid}: reference terms, label and scope note are required")
            relation = concept.get("udc_relation")
            if relation != ("broader_subject_anchor" if concept["udc_codes"] else "not_assigned"):
                raise ValueError(f"{cid}: inconsistent UDC relation")
        rule_ids = set()
        for rule in reference.get("rules", []):
            if not isinstance(rule, dict) or not re.fullmatch(r"[a-z0-9_]+", rule.get("id", "")) or rule["id"] in rule_ids:
                raise ValueError("Invalid or duplicate rule ID")
            rule_ids.add(rule["id"])
            for field in ("all", "any"):
                if not isinstance(rule.get(field, []), list) or any(cid not in seen for cid in rule.get(field, [])):
                    raise ValueError(f"Unknown concept in reference rule: {rule}")
            if not rule.get("all") or not rule.get("any"):
                raise ValueError("Reference rules require all and any concept IDs")
        return cls(root, data, reference)

    @staticmethod
    def _terms(terms, identifier):
        if not isinstance(terms, list) or not all(isinstance(term, str) and term.strip() for term in terms):
            raise ValueError(f"{identifier}: terms must be a list of nonempty strings")
        if len(terms) != len({unicodedata.normalize("NFC", t).casefold() for t in terms}):
            raise ValueError(f"{identifier}: duplicate terms")

    @property
    def languages(self):
        return self.data["languages"]

    def compile(self, language: str, category_index: dict):
        """Return category-aligned concepts and rules; absent aliases abstain."""
        if language not in self.languages:
            raise ValueError(f"No analysis language pack: {language}")
        pack = self.languages[language]
        if pack["vocabulary"] != "reference":
            raise ValueError("Legacy dictionaries use the existing category loader")
        ids = {row["id"]: row for row in self.reference["concepts"]}
        if language == "en":
            if self.reference.get("version") != pack["version"]:
                raise ValueError("en: registry/reference version mismatch")
            aliases = {cid: row["terms"] for cid, row in ids.items()}
            extra = self.reference
        else:
            extra = read_mapping(local_path(self.root, pack["terms_file"]))
            if extra.get("schema_version") != 1 or extra.get("language") != language or extra.get("reference_version") != self.reference["version"] or extra.get("version") != pack["version"] or extra.get("validation_status") != pack["validation_status"]:
                raise ValueError(f"{language}: language or reference_version mismatch")
            aliases = extra.get("concepts", {})
            if not isinstance(aliases, dict) or set(aliases) != set(ids):
                raise ValueError(f"{language}: concept IDs must exactly match the English reference; use [] for an unavailable equivalent")
        labels = extra.get("preferred_labels", {})
        if language != "en" and (not isinstance(labels, dict) or set(labels) != set(ids) or any(not isinstance(v, str) or not v.strip() for v in labels.values())):
            raise ValueError(f"{language}: preferred labels must cover every concept")
        for section in ("document_types", "terminology", "place_aliases"):
            values = extra.get(section, {})
            if not isinstance(values, dict) or set(values) - set(self.reference.get(section, {})):
                raise ValueError(f"{language}: unknown identifiers in {section}")
            for key, terms in values.items():
                self._terms(terms, f"{language}:{section}:{key}")
        categories = {row["id"] for row in category_index["categories"]}
        compiled = {key: {"concepts": [], "concept_rules": []} for key in categories}
        for cid, definition in ids.items():
            if definition["category"] not in categories and definition["category"] is not None:
                raise ValueError(f"{cid}: unknown category")
            self._terms(aliases[cid], f"{language}:{cid}")
            category = definition["category"]
            if category:
                compiled[category]["concepts"].append({**definition, "terms": aliases[cid]})
        for rule in self.reference.get("rules", []):
            category = rule["category"]
            if category not in categories:
                raise ValueError(f"Unknown rule category: {category}")
            # Every category needs its action concepts for rule evaluation.
            present = {c["id"] for c in compiled[category]["concepts"]}
            for cid in rule["all"] + rule["any"]:
                if cid not in present:
                    compiled[category]["concepts"].append({**ids[cid], "terms": aliases[cid]})
                    present.add(cid)
            compiled[category]["concept_rules"].append(rule)
        return compiled, extra

    def metadata(self, language):
        pack = self.languages.get(language)
        if not pack:
            return {"language": language, "status": "unsupported"}
        return {"language": language, "version": pack["version"],
                "validation_status": pack["validation_status"], "matching": pack["matching"],
                "reference_language": "en", "reference_version": self.reference["version"],
                "alignment": "legacy_category_ids_only" if pack["vocabulary"] == "legacy" else "reference_concepts",
                "ancillary_modules": pack.get("ancillary_modules", {})}

    def source_paths(self):
        return [local_path(self.root, self.data["reference_file"]), *(
            local_path(self.root, p["terms_file"]) for p in self.languages.values() if "terms_file" in p)]

    def notices(self, languages):
        languages = set(languages)
        unsupported = sorted(languages - set(self.languages))
        draft = sorted(code for code in languages if code in self.languages and self.languages[code]["vocabulary"] == "reference")
        if unsupported:
            yield ('Для мов {0} тематичні словники відсутні. Класифікацію пропущено; нульове покриття не характеризує зміст документів.', ', '.join(unsupported))
        if draft:
            yield ('Словники мов {0} є робочими та не пройшли незалежної експертної валідації. Покриття класифікацією не є оцінкою точності.', ', '.join(draft))
        for module, message in {
            'document_types': 'Для мов {0} не підключено словник типів документів. Нульові значення не доводять відсутності згадок.',
            'terminology': 'Для мов {0} не підключено термінологічний словник. Нульові значення не доводять відсутності згадок.',
            'geography': 'Для мов {0} не підключено географічний словник. Нульові значення не доводять відсутності згадок.',
        }.items():
            absent = sorted(code for code in languages if code in self.languages and not self.languages[code].get('ancillary_modules', {}).get(module, False))
            if absent:
                yield (message, ', '.join(absent))


@lru_cache(maxsize=32)
def pack_content(language):
    registry = LanguageRegistry.load()
    if language not in registry.languages:
        return {}
    pack = registry.languages[language]
    if pack["vocabulary"] == "legacy":
        return {}
    content = registry.reference if language == "en" else read_mapping(local_path(registry.root, pack["terms_file"]))
    return {**content, '_ancillary_modules': pack.get('ancillary_modules', {})}


@lru_cache(maxsize=128)
def lexical_patterns(language, section):
    patterns = {}
    content = pack_content(language)
    module = 'geography' if section == 'place_aliases' else section
    if not content.get('_ancillary_modules', {}).get(module, False):
        return patterns
    for key, terms in content.get(section, {}).items():
        if terms:
            variants = []
            for term in terms:
                words = re.findall(r"[^\W_]+", unicodedata.normalize("NFC", term))
                variants.append(r"[^\w_]+".join(re.escape(word) for word in words))
            patterns[key] = re.compile(r"(?<!\w)(?:" + "|".join(variants) + r")(?!\w)", re.I)
    return patterns


def alias_hits(title, language, section):
    title = unicodedata.normalize("NFC", title)
    return {key: hit.group() for key, pattern in lexical_patterns(language, section).items()
            if (hit := pattern.search(title))}


@lru_cache(maxsize=32)
def structural_patterns(language):
    pack = LanguageRegistry.load().languages.get(language, {})
    words = pack.get('year_words', [])
    year = re.compile(r'^\s*(?:1[5-9]|20)\d{2}\s*\.?\s*(?:' + '|'.join(re.escape(word) for word in words) + r')\.?\s*$', re.I) if words else None
    terms = pack.get('withdrawn_terms', [])
    withdrawn = re.compile(r'^\s*(?:' + '|'.join(re.escape(term) for term in terms) + r')(?=$|[^\w])', re.I) if terms else None
    return year, withdrawn


def personal_section_matches(title, language):
    content = pack_content(language)
    if language == 'en':
        terms = next((c['terms'] for c in content.get('concepts', []) if c['id'] == 'personal_documentation'), [])
    else:
        terms = content.get('concepts', {}).get('personal_documentation', [])
    return any(re.match(r'^\s*' + re.escape(term) + r'(?!\w)', title, re.I) for term in terms)


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
        if all(hits[cid] for cid in rule["all"]) and any(hits[cid] for cid in rule["any"]):
            score += 3
            used = [cid for cid in rule["all"] + rule["any"] if hits[cid]]
            subject.append("concept_rule:" + rule["id"] + ": " + "; ".join(cid + "=" + " | ".join(hits[cid]) for cid in used))
    return score, subject, context
