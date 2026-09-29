"""Keep serialization contracts stable when reports share their writers."""
import csv
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models import Record
from report_utils import json_for_script, write_csv


class SerializationTests(unittest.TestCase):
    def test_csv_generator_bom_quoting_count_and_extra_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "data.csv"
            rows = [{"title": 'Назва; "цитата"\nпродовження', "count": 0, "extra": 99},
                    {"title": "", "count": None}]
            self.assertEqual(write_csv(path, ["title", "count"], (r for r in rows)), 2)
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b"\r\n", raw)
            with path.open(encoding="utf-8-sig", newline="") as stream:
                self.assertEqual(list(csv.DictReader(stream, delimiter=";")),
                                 [{"title": rows[0]["title"], "count": "0"}, {"title": "", "count": ""}])

    def test_csv_strict_policy_empty_rows_and_missing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            with self.assertRaises(ValueError):
                write_csv(path, ["a"], [{"a": 1, "b": 2}], extrasaction="raise", create_parent=False)
            self.assertEqual(write_csv(path, ["a"], iter(()), extrasaction="raise", create_parent=False), 0)
            self.assertEqual(path.read_bytes(), b"\xef\xbb\xbfa\r\n")
            with self.assertRaises(FileNotFoundError):
                write_csv(Path(tmp) / "missing" / "data.csv", ["a"], [], create_parent=False)

    def test_json_preserves_source_text_without_closing_script_element(self):
        source = {"title": '</script><script>alert("x")</script> Миколаїв', "empty": None}
        encoded = json_for_script(source)
        self.assertNotIn("<", encoded)
        self.assertIn("Миколаїв", encoded)
        self.assertEqual(json.loads(encoded), source)

    def test_record_uid_does_not_change_dataclass_fields_or_merge_case_numbers(self):
        record = Record(5, "опис", "1", "1", "Текст", "", "", "", "case", None, source_id="fond")
        self.assertEqual(record.record_uid, "fond:опис:5")
        self.assertNotIn("record_uid", asdict(record))
        record.excel_row = 6
        self.assertEqual(record.record_uid, "fond:опис:6")


if __name__ == "__main__":
    unittest.main()
