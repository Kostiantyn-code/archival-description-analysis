import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fond_analysis as analysis
from geography import find_places, unknown_candidates
from geography_maps import write_maps


class GeographyTests(unittest.TestCase):
    def test_two_languages_multiple_places_and_excluded_institution(self):
        title = "Перевезення з м. Миколаїв до Севастополя та Одеси"
        self.assertEqual({place.name for place, _ in find_places(title)},
                         {"Миколаїв", "Севастополь", "Одеса"})
        self.assertEqual({place.name for place, _ in find_places(
            "Дело о высылке из гор. Николаева в Москву")},
            {"Миколаїв", "Москва"})
        self.assertEqual(find_places("Лист Миколаївського губернатора до Николаева Ивана"), [])
        self.assertEqual(find_places("Лист Керч-Єнікальського градоначальника"), [])
        self.assertIn("Миколаїв", {place.name for place, _ in find_places(
            "Збори у містах Миколаєві та Севастополі")})
        self.assertIn("Миколаїв", {place.name for place, _ in find_places(
            "Дело о событии в гор. Николаеве Тимофеевой")})

    def test_other_geographies_and_unmapped_city(self):
        title = "Справа про подорож із Варшави до Берліна через м. Брюссель"
        self.assertEqual({place.name for place, _ in find_places(title)},
                         {"Варшава", "Берлін"})
        self.assertEqual(unknown_candidates(title, find_places(title)), ["Брюссель"])

    def test_descriptions_decades_and_standalone_maps(self):
        records = [
            analysis.Record(5, "Опис 1", "1", "1", "Листування між містами Миколаїв і Одеса",
                            "", "1", "", "case", 1850, source_archive="ДАМО",
                            source_fond="230", source_inventory="1", source_id="damo"),
            analysis.Record(5, "ЦДІАК", "1", "1", "Дело о высылке из гор. Николаева в Москву",
                            "", "1", "", "case", 1890, source_archive="ЦДІАК",
                            source_fond="356", source_inventory="1", source_id="cdiak"),
        ]
        sources = {r.sheet_name: {"archive": r.source_archive, "fond": r.source_fond,
                                  "inventory": r.source_inventory} for r in records}
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with patch.object(analysis, "WORK_DIR", folder), \
                 patch.object(analysis, "SHEET_NAMES", tuple(sources)), \
                 patch.object(analysis, "SOURCE_CONFIG", sources):
                result = analysis.create_geography_tables(records, list(sources))
                with (folder / "geography_by_decade.csv").open(encoding="utf-8-sig") as f:
                    decade_rows = list(csv.DictReader(f, delimiter=";"))
                write_maps(folder, result["rows"], list(sources),
                           {name: name for name in sources},
                           {"Опис 1": "#275c83", "ЦДІАК": "#dc8348"}, "Два фонди")
            self.assertEqual(result["matched_cases"], 2)
            self.assertEqual(len(result["rows"]), 4)
            self.assertIn(("Москва", "1890", "ЦДІАК", "1"),
                          {(r["place"], r["decade"], r["sheet_name"], r["titles"])
                           for r in decade_rows})
            for name in ("south", "europe", "russia"):
                content = (folder / f"geography_{name}.html").read_text()
                self.assertIn("Миколаїв", content)
                self.assertIn("Європейська частина РФ", content)
                self.assertNotIn("tile.openstreetmap.org", content)
                self.assertNotIn("__BASEMAP__", content)


if __name__ == "__main__":
    unittest.main()
