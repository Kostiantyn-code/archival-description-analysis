#!/usr/bin/env python3
"""Check shared vocabulary and optionally regenerate a reviewable crosswalk.

Run from any directory: python tools/validate_language_packs.py [--output outputs/validation]
This is a structural/development check, not an estimate of corpus accuracy.
"""

from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml
from language_packs import LanguageRegistry
import fond_analysis as f


def evaluate():
    registry = LanguageRegistry.load()
    index = yaml.safe_load((ROOT / "config/categories.yaml").read_text(encoding="utf-8"))
    languages = [
        code
        for code, pack in registry.languages.items()
        if pack["vocabulary"] == "reference"
    ]
    ordered = ["en", *sorted(code for code in languages if code != "en")]
    for code in ordered:
        registry.compile(code, index)
    alignment = list(registry.alignment_rows())
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(alignment[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(alignment)
    # Load production dictionaries and exercise separately authored contrast cases.
    f.ANALYSIS_CONFIG = {}
    f.LANGUAGE_CATEGORIES.clear()
    f.LANGUAGE_AMBIGUITIES.clear()
    for code in ordered:
        cats, amb, blocks, _ = f.load_dictionaries(yaml, code)
        f.LANGUAGE_CATEGORIES[code] = cats
        f.LANGUAGE_AMBIGUITIES[code] = amb
    cases = yaml.safe_load(
        (ROOT / "tests/fixtures/multilingual_cases.yaml").read_text(encoding="utf-8")
    )
    failures = []
    for case in cases:
        for code, title in case["titles"].items():
            result = f.classify_title(
                title,
                f.LANGUAGE_CATEGORIES[code],
                f.LANGUAGE_AMBIGUITIES[code],
                list(blocks),
                code,
            )
            if set(result[0]) != set(case["categories"]):
                failures.append(
                    {
                        "case": case["id"],
                        "language": code,
                        "expected": case["categories"],
                        "actual": result[0],
                    }
                )
    inputs = [
        ROOT / "config/categories.yaml",
        *registry.source_paths(),
        ROOT / "tests/fixtures/multilingual_cases.yaml",
        ROOT / "language_packs.py",
        ROOT / "fond_analysis.py",
        ROOT / "text_matching.py",
    ]
    manifest = {
        "reference_version": registry.reference["version"],
        "concept_count": len(registry.reference["concepts"]),
        "rule_count": len(registry.reference["rules"]),
        "aligned_languages": ordered,
        "concepts_without_udc": [
            c["id"] for c in registry.reference["concepts"] if not c["udc_codes"]
        ],
        "synthetic_case_sets": len(cases),
        "synthetic_language_cases": sum(len(c["titles"]) for c in cases),
        "failures": failures,
        "status": "passed" if not failures else "failed",
        "validation_scope": "Structural checks and developer-authored synthetic contrasts; no independent linguistic or corpus accuracy validation.",
        "sha256": {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(set(inputs))
        },
    }
    return stream.getvalue(), manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, help="Write the crosswalk and checks to this directory"
    )
    args = parser.parse_args()
    crosswalk, manifest = evaluate()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "vocabulary_alignment.csv").write_text(
            crosswalk, encoding="utf-8"
        )
        (args.output / "vocabulary_checks.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {k: v for k, v in manifest.items() if k != "sha256"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return bool(manifest["failures"])


if __name__ == "__main__":
    raise SystemExit(main())
