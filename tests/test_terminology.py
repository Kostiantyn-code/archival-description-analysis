import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models import Record
from terminology import match_terms, write_terminology_report


def case(sheet, title, year, row):
    return Record(row, sheet, str(row), str(row), title, "", "", "",
                  "case", None, source_archive="Інший архів", source_fond="42",
                  source_inventory=sheet, source_id="new_fond", start_year=year)


class TerminologyTests(unittest.TestCase):
    def test_exact_phrases_and_multiple_labels(self):
        self.assertEqual([key for key, _ in match_terms("політичних політичних")], ["political"])
        self.assertEqual({key for key, _ in match_terms("Поліцейський нагляд і розшук")},
                         {"police_supervision", "supervision", "search"})
        self.assertNotIn("serf", {key for key, _ in match_terms("Кріпосне інженерне управління")})
        self.assertIn("serf", {key for key, _ in match_terms("Кріпосних селян")})
        self.assertIn("honorary", {key for key, _ in match_terms("Почетных граждан")})

    def test_report_handles_other_descriptions_and_undated_cases(self):
        records = [
            case("Книга А", "Політичний розшук і політичний нагляд", 1854, 5),
            case("Книга А", "Кріпосне інженерне управління", 1857, 6),
            case("Книга Б", "Политическая ссылка", 1886, 7),
            case("Книга Б", "Політичний розшук", None, 8),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            summary = write_terminology_report(
                records, ["Книга А", "Книга Б"],
                {"Книга А": "Архів N: опис А", "Книга Б": "Архів N: опис Б"},
                {"Книга А": "#225588", "Книга Б": "#cc8833"},
                lambda record: record.start_year // 10 * 10 if record.start_year else None,
                path, path, "Тестовий фонд",
            )
            self.assertEqual(summary["dated_titles"], 3)
            with (path / "terms_by_decade_and_description.csv").open(encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream, delimiter=";"))
            political = [r for r in rows if r["term_id"] == "political"]
            self.assertEqual([(r["titles_with_term"], r["titles_total"]) for r in political
                              if r["scope"] == "all"], [("1", "2"), ("1", "1")])
            self.assertEqual(next(r["per_1000_titles"] for r in political
                                  if r["scope"] == "Книга А" and r["decade"] == "1850"), "500.00")
            with (path / "term_mentions.csv").open(encoding="utf-8-sig") as stream:
                mentions = list(csv.DictReader(stream, delimiter=";"))
            self.assertEqual(sum(r["term_id"] == "political" for r in mentions), 3)
            self.assertTrue(any(r["decade"] == "unknown" for r in mentions))
            html = (path / "terminology_evolution.html").read_text(encoding="utf-8")
            self.assertIn("Тестовий фонд", html)
            self.assertIn("Архів N: опис Б", html)
            self.assertNotIn("__DATA__", html)


if __name__ == "__main__":
    unittest.main()
