"""Regression coverage for the workbook verification tables."""

import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import openpyxl
import yaml

import fond_analysis as analysis


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter=";"))


class UdcReportTests(unittest.TestCase):
    def test_batch_audits_shared_and_legacy_rules_and_language_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_dir = root / "input"
            input_dir.mkdir()
            book = openpyxl.Workbook()
            book.remove(book.active)
            for code, fond in (("en", "Р-1"), ("fr", "К-1"), ("ru", "Т-1")):
                sheet = book.create_sheet(code)
                for row in [
                    ("Archive", "Archive", None, "Language", code),
                    ("Fonds", fond), ("Inventory", "1"),
                    ("No.", "Title", "Dates", "Folios", "Notes"),
                ]:
                    sheet.append(row)
            book["en"].append((1, "Opening a school", 1850, 1))
            book["en"].append((2, "Arrest of a teacher", 1850, 1))
            book["en"].append((None, "Personal files of teachers"))
            book["en"].append((3, "John Smith", 1850, 1))
            book["fr"].append((1, "Une école", 1850, 1))
            book["ru"].append((1, "Дело об открытии училища", 1850, 1))
            book.save(input_dir / "source.xlsx")
            book.close()
            output_root = root / "outputs"
            with (
                patch.object(analysis, "INPUT_DIR", input_dir),
                patch.object(analysis, "OUTPUTS_DIR", output_root),
                patch.object(analysis, "ANALYSIS_CONFIG", {"exports": {"enabled": False}}),
                patch.object(analysis, "configure_analysis"),
                patch.object(analysis, "load_dependencies", return_value=(openpyxl, yaml, None)),
                patch.object(analysis, "match_terms", wraps=analysis.match_terms) as terminology,
                patch.object(analysis, "match_geography", wraps=analysis.match_geography) as geography,
                patch.object(analysis, "match_document_types", wraps=analysis.match_document_types) as types,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                analysis.main()
            report = next(output_root.iterdir()) / "source"
            manifest = json.loads((report / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len({row["source_id"] for row in manifest["sources"].values()}), 3)
            self.assertEqual((terminology.call_count, geography.call_count, types.call_count), (5, 5, 5))
            self.assertIn('href="tables/thematic_evidence.csv"', (report / "report.html").read_text(encoding="utf-8"))
            self.assertIn("tables/vocabulary_alignment.csv", manifest["outputs"])
            evidence = read_csv(report / manifest["udc_alignment"]["evidence_table"])
            self.assertTrue(any(
                row["rule_id"] == "educational_institution_operation"
                and row["udc_codes"] == "37" and row["row_number"] == "5"
                for row in evidence
            ))
            self.assertTrue(any(
                row["concept_id"] == "educational_actor" and row["decision"] == "context"
                and row["title_original"] == "Arrest of a teacher" for row in evidence
            ))
            self.assertTrue(any(
                row["evidence_origin"] == "inventory_section" and row["rule_id"] == "educational_personnel_records"
                and row["title_original"] == "John Smith" and row["evidence_text"] == "Personal files of teachers"
                for row in evidence
            ))
            self.assertTrue(any(row["language"] == "ru" and row["udc_relation"] == "not_mapped" for row in evidence))
            self.assertFalse(any(row["language"] == "fr" for row in evidence))
            tables = report / "tables"
            for path in (tables / "combined/category_counts.csv", tables / "thematic_summary.csv"):
                education = next(row for row in read_csv(path) if row["category_id"] == "education")
                self.assertEqual(education["total_titles"], "5")
                self.assertEqual(education["eligible_titles"], "4")
                self.assertEqual(education["skipped_language_titles"], "1")
                count = int(education["cases"])
                self.assertEqual(education["percent_of_analyzed_titles"], f"{count / 5 * 100:.2f}")
                self.assertEqual(education["percent_of_eligible_titles"], f"{count / 4 * 100:.2f}")

    def test_cached_export_preserves_cell_attributes(self):
        from openpyxl.comments import Comment
        from openpyxl.styles import Font

        source = openpyxl.Workbook()
        sheet = source.active
        font = Font(name="Arial", bold=True)
        for row in (5, 8):
            cell = sheet.cell(row, 2, f"Title {row}")
            cell.font = font
            cell.comment = Comment(f"Note {row}", "Author")
            cell.hyperlink = f"https://example.com/{row}"
        sheet["C8"] = "=a literal value"
        sheet["C8"].data_type = "s"
        records = [analysis.Record(row, sheet.title, str(row), str(row),
                                   "", "", "", "", "case", None) for row in (5, 8)]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "selection.xlsx"
            with (patch.object(analysis, "SHEET_NAMES", (sheet.title,)),
                  patch.object(analysis, "HEADER_ROWS_BY_SHEET", {sheet.title: 4})):
                analysis.create_filtered_workbook(openpyxl, source, records, path, 3)
            exported = openpyxl.load_workbook(path)
            try:
                for target_row, source_row in ((5, 5), (6, 8)):
                    result = exported.active[f"B{target_row}"]
                    self.assertEqual(result.font, font)
                    self.assertEqual(result.comment.text, f"Note {source_row}")
                    self.assertEqual(result.hyperlink.target, f"https://example.com/{source_row}")
                self.assertEqual(exported.active["C6"].data_type, "s")
                self.assertEqual(exported.active["C6"].value, "=a literal value")
            finally:
                exported.close()
                source.close()
