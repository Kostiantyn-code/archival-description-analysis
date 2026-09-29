"""Workbook HTML: safe local links, bounded tables and empty results."""
import csv
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from html_report import write_html_report
from models import Issue, Record


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.scripts.append(attrs)
        for key in ("href", "src"):
            if key in attrs:
                self.targets.append(attrs[key])


class HtmlReportTests(unittest.TestCase):
    def test_empty_report_has_no_broken_assets_or_nan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_html_report(root, "Порожня.xlsx", {"combined": []}, [], "test", "test", {})
            page = path.read_text()
            self.assertIn("Не визначено", page)
            self.assertIn("Статичні графіки не створено", page)
            self.assertNotIn("NaN", page)
            parser = Links()
            parser.feed(page)
            self.assertFalse(parser.scripts)
            self.assertFalse([target for target in parser.targets if not target.startswith("#")])

    def test_links_escaping_and_table_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scope = "фонд #1"
            for folder in ("tables", "figures", "reports"):
                (root / folder / scope).mkdir(parents=True)
            table = root / "tables" / scope / "description_summary.csv"
            with table.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, ["description", "cases_in_analysis"], delimiter=";")
                writer.writeheader()
                writer.writerows({"description": f"<опис {i}>", "cases_in_analysis": 1} for i in range(51))
            for name in ("theme_links.html", "terminology_evolution.html", "thematic_categories.svg"):
                (root / "figures" / scope / name).write_text("fixture")
            (root / "reports" / scope / "analysis_report.md").write_text("fixture")
            (root / "run_manifest.json").write_text("{}")
            exports = root / "thematic_exports"
            exports.mkdir()
            (exports / 'тема #1 & дані.xlsx').write_text("fixture")
            record = Record(5, "sheet", "1", "1", "Заголовок", "1850", "2", "", "case", None,
                            source_archive="<архів>", source_fond="230")
            record.start_year = record.end_year = 1850
            record.pages = 2
            record.categories = ["a"]
            page = write_html_report(root, '<script>alert(1)</script>.xlsx', {scope: [record]},
                                     [Issue("WARNING", 5, "1", "дата", "", "тест", "sheet")],
                                     "test", "test", {}).read_text()
            self.assertIn("Показано 50 із 51 рядків", page)
            self.assertIn("&lt;опис 0&gt;", page)
            self.assertIn("&lt;архів&gt;", page)
            self.assertIn("1850–1850", page)
            parser = Links()
            parser.feed(page)
            self.assertFalse(parser.scripts)
            for target in parser.targets:
                if not target.startswith("#"):
                    self.assertTrue((root / unquote(target)).is_file(), target)
            self.assertTrue(any("%23" in target for target in parser.targets))
            self.assertTrue(any(target.endswith(".svg") for target in parser.targets))


if __name__ == "__main__":
    unittest.main()
