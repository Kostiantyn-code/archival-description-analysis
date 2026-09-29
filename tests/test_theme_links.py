import csv
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models import Category, Record
from theme_links import write_theme_links


def category(id_, block):
    return Category(id_, id_.upper(), block, 3, [], [], [], [], [], [], [], [])


def record(sheet, row, assigned, blocks, *, status="case", archive="ДАМО"):
    item = Record(row, sheet, str(row), str(row), f"Заголовок <{row}>", "", "", "",
                  status, None, source_archive=archive, source_fond="230",
                  source_inventory="1", source_id=archive)
    item.categories = assigned
    item.macroblocks = blocks
    item.context_categories = ["ignored"]
    return item


class ThemeLinkTests(unittest.TestCase):
    def test_pairs_respect_case_status_descriptions_and_subject_only(self):
        records = [
            record("Опис А", 1, ["a", "b", "c"], ["political", "cultural"]),
            record("Опис Б", 2, ["a", "b"], ["political"], archive="ЦДІАК"),
            record("Опис Б", 3, [], [], archive="ЦДІАК"),
            record("Опис А", 4, ["a", "b"], ["political"], status="withdrawn"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            result = write_theme_links(
                records, ["Опис А", "Опис Б", "Порожній опис"],
                {"Опис А": "ДАМО, оп. 1", "Опис Б": "ЦДІАК, оп. 1",
                 "Порожній опис": "Оп. без справ"},
                [category("a", "political"), category("b", "political"),
                 category("c", "cultural")],
                {"political": "Політичний", "cultural": "Культурний"},
                path, path, "Збірка <архівів>",
            )
            self.assertEqual(result, {"titles": 3, "multi": 2, "category_pairs": 3})
            with (path / "theme_links_by_description.csv").open(encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f, delimiter=";"))
            ab = next(r for r in rows if r["scope"] == "__all__" and
                      r["level"] == "cat" and r["theme_a_id"] == "a" and
                      r["theme_b_id"] == "b")
            self.assertEqual((ab["titles_total"], ab["shared_titles"],
                              ab["relative_frequency"]), ("3", "2", "1.500"))
            self.assertEqual(next(r["shared_titles"] for r in rows if
                                  r["scope"] == "Опис Б" and r["level"] == "cat" and
                                  r["theme_a_id"] == "a" and r["theme_b_id"] == "c"), "0")
            self.assertTrue(any(r["scope"] == "Порожній опис" and
                                r["relative_frequency"] == "" for r in rows))
            with (path / "theme_link_cases.csv").open(encoding="utf-8-sig") as f:
                evidence = list(csv.DictReader(f, delimiter=";"))
            self.assertEqual(len(evidence), 5)  # 3 + 1 category pairs, 1 block pair.
            self.assertIn("ЦДІАК", {r["archive"] for r in evidence})
            page = (path / "theme_links.html").read_text(encoding="utf-8")
            self.assertIn("Збірка &lt;архівів&gt;", page)
            self.assertNotIn("__DATA__", page)
            self.assertNotIn("<1>", page)
            payload = json.loads(re.search(r'<script type="application/json" id="tl-data">(.*?)</script>',
                                           page, re.S).group(1))
            self.assertEqual(payload["scopes"]["Опис Б"]["cat"]["multi"], 1)
            self.assertEqual(payload["scopes"]["__all__"]["block"]["multi"], 1)
            self.assertEqual(ab["shared_per_1000_titles"], "666.667")
            self.assertEqual(len(payload["meta"]["descriptions"]), 3)
            zero = next(e for e in payload["scopes"]["Опис Б"]["cat"]["edges"]
                        if e["a"] == "a" and e["b"] == "c")
            self.assertEqual((zero["count"], zero["rate"], zero["lift"]), (0, 0, None))
            empty = payload["scopes"]["Порожній опис"]["cat"]["edges"]
            self.assertEqual(len(empty), 3)
            self.assertTrue(all(e["count"] == 0 and e["rate"] is None and e["lift"] is None
                                for e in empty))
            self.assertTrue(all(r["shared_per_1000_titles"] == "" for r in rows
                                if r["scope"] == "Порожній опис"))



if __name__ == "__main__":
    unittest.main()
