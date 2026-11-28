"""Export the vocabulary alignment and the evidence used by the classifier."""

from report_utils import write_csv


EVIDENCE_FIELDS = [
    "record_uid", "archive", "fond", "inventory", "sheet", "row_number", "case_id",
    "language", "title_original", "evidence_origin", "evidence_text", "category_id",
    "decision", "category_score", "rule_id", "concept_id", "concept_role",
    "matched_dictionary_terms", "udc_codes", "udc_relation", "legacy_evidence",
]


def evidence_rows(records, concepts):
    for record in records:
        if record.status != "case":
            continue
        base = {
            "record_uid": record.record_uid, "archive": record.source_archive,
            "fond": record.source_fond, "inventory": record.source_inventory,
            "sheet": record.sheet_name, "row_number": record.excel_row,
            "case_id": record.case_id_raw, "language": record.language,
            "title_original": record.title_raw,
        }
        for decision, evidence, matches in (
            ("subject", record.evidence, record.subject_matches),
            ("context", record.context_evidence, record.context_matches),
        ):
            for category, reasons in evidence.items():
                inherited = decision == "subject" and category in record.inherited_categories
                row = {
                    **base, "category_id": category, "decision": decision,
                    "category_score": record.scores.get(category, "") if decision == "subject" else "",
                    "evidence_origin": "inventory_section" if inherited else "title",
                    "evidence_text": record.thematic_section if inherited else record.title_raw,
                }
                if category not in matches:
                    for reason in reasons:
                        if inherited and reason.startswith("inventory_section:"):
                            continue
                        yield {**row, "udc_relation": "not_mapped", "legacy_evidence": reason}
                    continue
                for match in matches[category]:
                    for cid, forms in match.matches.items():
                        concept = concepts[cid]
                        yield {
                            **row, "rule_id": match.rule_id, "concept_id": cid,
                            "concept_role": concept["kind"],
                            "matched_dictionary_terms": " | ".join(forms),
                            "udc_codes": " | ".join(concept["udc_codes"]),
                            "udc_relation": concept["udc_relation"],
                        }


def write_udc_tables(directory, records, registry):
    alignment = list(registry.alignment_rows())
    write_csv(directory / "vocabulary_alignment.csv", list(alignment[0]), alignment)
    concepts = {concept["id"]: concept for concept in registry.reference["concepts"]}
    write_csv(directory / "thematic_evidence.csv", EVIDENCE_FIELDS, evidence_rows(records, concepts))
