import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fond_analysis as analysis
from document_types import match_document_types


def ids(title):
    return {document_type.id for document_type, _ in match_document_types(title)}


class DocumentTypeTests(unittest.TestCase):
    def test_ukrainian_and_russian_forms_are_multilabel(self):
        self.assertEqual(
            ids("Листування з думою, рапорти поліції та циркуляри міністерства"),
            {"correspondence", "reports", "circulars"},
        )
        self.assertEqual(
            ids("Переписка с полицией, рапорты и циркуляры департамента"),
            {"correspondence", "reports", "circulars"},
        )
        self.assertIn("instructions", ids("Предписание и распоряжение губернатора"))
        self.assertIn("notifications", ids("Сообщение и телеграмма губернатора"))

    def test_generic_file_title_is_not_a_document_form(self):
        self.assertEqual(ids("Справа про призначення на посаду"), set())
        self.assertEqual(ids("Дело о розыске разных лиц"), set())
        # A mention does not prove that this document survives in the file.
        self.assertIn("certificates", ids("Дело о выдаче паспортов"))

    def test_combined_description_counts_preserve_archives_and_overlaps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = [
                analysis.Record(5, "Опис 1", "1", "1", "Листування та рапорт", "1850", "2", "", "case", None,
                                source_archive="ДАМО", source_fond="230", source_inventory="1", source_id="damo"),
                analysis.Record(5, "Опис 2", "1", "1", "Справа про школу", "1850", "2", "", "case", None,
                                source_archive="ДАМО", source_fond="230", source_inventory="2", source_id="damo"),
                analysis.Record(5, "ЦДІАК", "1", "1", "Переписка и циркуляр", "1850", "2", "", "case", None,
                                source_archive="ЦДІАК України", source_fond="356", source_inventory="1", source_id="cdiak"),
            ]
            sources = {
                r.sheet_name: {"archive": r.source_archive, "fond": r.source_fond,
                               "inventory": r.source_inventory}
                for r in records
            }
            with patch.object(analysis, "WORK_DIR", root), \
                 patch.object(analysis, "SHEET_NAMES", tuple(sources)), \
                 patch.object(analysis, "SOURCE_CONFIG", sources):
                data = analysis.create_service_tables(records, [])

            self.assertEqual(data["document_type_matched"], 2)
            self.assertEqual(data["document_type_multi"], 2)
            self.assertEqual(data["document_type_counts"]["correspondence"], 2)
            self.assertEqual(data["document_type_by_sheet"]["ЦДІАК"]["circulars"], 1)
            with (root / "document_types_by_description.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream, delimiter=";"))
            selected = [row for row in rows if row["document_type_id"] == "correspondence"]
            self.assertEqual([(row["sheet_name"], row["titles"]) for row in selected],
                             [("Опис 1", "1"), ("Опис 2", "0"), ("ЦДІАК", "1")])


if __name__ == "__main__":
    unittest.main()
