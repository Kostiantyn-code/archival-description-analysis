"""Language affects presentation only, including standalone interactive reports."""
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import contextlib
import io
from pathlib import Path
from unittest.mock import patch

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yaml
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import fond_analysis as f
from geography_maps import write_maps
from html_report import CHARTS, write_html_report
from terminology import write_terminology_report, TERMS, GROUPS
from theme_links import write_theme_links
from visualization import Visualization, english_catalog


class VisualizationTests(unittest.TestCase):
    def test_defaults_validation_and_original_fallback(self):
        self.assertEqual(Visualization.from_config({}).metadata(),
                         {"language": "uk", "bilingual_labels": False, "label_overrides": {}})
        for options in ({"language": "fr"}, {"bilingual_labels": "false"},
                        {"label_overrides": {"terms": []}}, None):
            with self.assertRaises(ValueError):
                Visualization.from_config({"visualization": options})
        en = Visualization("en", True)
        self.assertEqual(en.label("categories", "education", "Освіта"), "Education (Освіта)")
        self.assertEqual(en.label("terms", "unknown", "Невідомий термін"), "Невідомий термін")
        self.assertEqual(Visualization().label("categories", "education", "Освіта"), "Освіта")

    def test_overrides_and_archival_references(self):
        en = Visualization.from_config({"visualization": {
            "language": "en", "bilingual_labels": True,
            "label_overrides": {"archives": {"ДАМО": "State Archives of Mykolaiv Region"},
                                "terms": {"burgher": "Townsman"}}}})
        self.assertEqual(en.label("terms", "burgher", "Міщанин"), "Townsman (Міщанин)")
        self.assertEqual(en.description("sheet", "ДАМО, ф. 230: опис 1"),
                         "State Archives of Mykolaiv Region (ДАМО), fond 230: inventory 1")

    def test_catalog_covers_identifiers_and_templates(self):
        catalog = english_catalog()
        config = yaml.safe_load((ROOT / "config/categories.yaml").read_text())
        self.assertFalse({c["id"] for c in config["categories"]} - catalog["categories"].keys())
        self.assertFalse(set(config["macroblocks"]) - catalog["macroblocks"].keys())
        self.assertFalse({t.id for t in f.DOCUMENT_TYPES} - catalog["document_types"].keys())
        self.assertFalse({t[0] for t in TERMS} - catalog["terms"].keys())
        self.assertFalse({g[0] for g in GROUPS} - catalog["term_groups"].keys())
        self.assertFalse({p.name for p in f.load_places()[1]} - catalog["places"].keys())
        for path in (ROOT / "maps").glob("*template.html"):
            source = path.read_text()
            self.assertEqual(Visualization().template(source), source)
            self.assertIsNone(re.search("[А-Яа-яІіЇїЄєҐґ]", Visualization("en").template(source)), path)

    def test_batch_passes_config_to_reports_and_manifest(self):
        from test_multi_workbook import workbook
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "input").mkdir()
            workbook(root / "input/book.xlsx", [
                ("one", "ДАМО", 230, 1, "Листування про школу в м. Миколаїв і політичний нагляд")])
            config = {"input_dir": str(root / "input"), "output_root": str(root / "outputs"),
                      "exports": {"enabled": False}, "visualization": {
                          "language": "en", "bilingual_labels": True,
                          "label_overrides": {"categories": {"education": "Education </script>"}}}}
            path = root / "analysis.yaml"
            path.write_text(yaml.safe_dump(config, allow_unicode=True))
            original_config_path = f.config_path
            def config_path(name, *args):
                return path if name == "analysis.yaml" else original_config_path(name, *args)
            with patch.object(f, "config_path", config_path), \
                 patch.object(f, "load_dependencies", lambda: (openpyxl, yaml, None)), \
                 patch.multiple(f, **{key: getattr(f, key) for key in (
                     "INPUT_DIR", "INPUT_FILE", "OUTPUTS_DIR", "ANALYSIS_CONFIG", "RUN_DIR",
                     "REPORTS_DIR", "FIGURES_DIR", "WORK_DIR", "THEMATIC_DIR",
                     "SOURCE_CONFIG", "SHEET_NAMES", "HEADER_ROWS_BY_SHEET")}), \
                 contextlib.redirect_stdout(io.StringIO()):
                f.main()
            folder = next((root / "outputs").glob("*/book"))
            manifest = json.loads((folder / "run_manifest.json").read_text())
            self.assertEqual(manifest["visualization"], config["visualization"])
            self.assertIn("config/visualization.en.json", manifest["sha256"])
            scopes = [row["source"] for row in manifest["source_summary"]]
            self.assertIn("Theme links", (folder / "report.html").read_text())
            for scope in scopes:
                network = (folder / "figures" / scope / "theme_links.html").read_text()
                self.assertIn('lang="en"', network)
                self.assertIn("Combined scope" if scope == "combined" else scope, network)
                self.assertNotIn("Education </script>", network)
                payload = json.loads(re.search(r'id="tl-data">(.*?)</script>', network, re.S)[1])
                self.assertEqual(payload["meta"]["cat"]["education"], "Education </script> (Освіта)")
                terminology = (folder / "figures" / scope / "terminology_evolution.html").read_text()
                self.assertIn("Political (Політичний / политический)", terminology)
                geography = (folder / "figures" / scope / "geography_south.html").read_text()
                self.assertIn("Mykolaiv (Миколаїв)", geography)

    def test_same_tables_and_analysis_in_all_modes(self):
        categories, ambiguities, blocks, _ = f.load_dictionaries(yaml)
        records = [
            f.Record(5, "Опис 1", "1", "1", "Листування про школу в м. Миколаїв і політичний нагляд",
                     "1854", "8", "", "case", None, start_year=1854, end_year=1854,
                     source_archive="ДАМО", source_fond="230", source_inventory="1", source_id="damo"),
            f.Record(6, "Опис 2", "2", "2", "Рапорт про лікарню в м. Одеса і паспорт міщанина",
                     "1862", "9", "", "case", None, start_year=1862, end_year=1862,
                     source_archive="ДАМО", source_fond="230", source_inventory="2", source_id="damo"),
        ]
        f.classify_records(records, categories, ambiguities, list(blocks))
        original_records = copy.deepcopy(records)
        sheets = [r.sheet_name for r in records]
        sources = {r.sheet_name: {"archive": r.source_archive, "fond": r.source_fond,
                                  "inventory": r.source_inventory, "source_id": r.source_id}
                   for r in records}
        labels = {s: f"ДАМО, ф. 230: опис {i+1}" for i, s in enumerate(sheets)}
        colors = {s: c for s, c in zip(sheets, ["#225588", "#cc8833"])}
        snapshots, summaries, term_data, network_data = [], [], [], []
        with tempfile.TemporaryDirectory() as tmp:
            for index, visual in enumerate([Visualization(), Visualization("en"), Visualization("en", True)]):
                folder = Path(tmp) / str(index)
                folder.mkdir()
                with patch.object(f, "WORK_DIR", folder), patch.object(f, "FIGURES_DIR", folder), \
                     patch.object(f, "SHEET_NAMES", tuple(sheets)), patch.object(f, "SOURCE_CONFIG", sources):
                    tables = f.create_service_tables(records, categories)
                    self.assertTrue(f.create_figures(plt, records, categories, tables, visual))
                    summaries.append((
                        write_terminology_report(records, sheets, labels, colors, f.get_decade,
                                                 folder, folder, "Спільний зріз", visual),
                        write_theme_links(records, sheets, labels, categories, blocks,
                                          folder, folder, "Спільний зріз", visual)))
                    write_maps(folder, tables["geography"]["rows"], sheets, labels, colors,
                               "Спільний зріз", visual)
                snapshots.append({p.name: p.read_bytes() for p in folder.glob("*.csv")})
                for stem in CHARTS:
                    self.assertTrue((folder / (stem + ".png")).is_file())
                    self.assertTrue((folder / (stem + ".svg")).is_file())
                page = (folder / "theme_links.html").read_text()
                network_data.append(json.loads(re.search(r'id="tl-data">(.*?)</script>', page, re.S)[1]))
                terminology = (folder / "terminology_evolution.html").read_text()
                term_data.append(json.loads(re.search(r'const DATA=(.*?);\n', terminology)[1]))
                if index:
                    self.assertIn('lang="en"', page)
                    self.assertIn("Theme links", page)
                    self.assertIn("inventory 1", page)
                    self.assertIn("Листування про школу", page)  # Evidence is never translated.
                    svg = (folder / "thematic_categories.svg").read_text()
                    self.assertIn("Education", svg)
                    self.assertIn("Number of case files", svg)
                    self.assertNotIn("Усього", svg)
                    self.assertNotIn("Архівний опис", svg)
                    if index == 2:
                        self.assertIn("Освіта", svg)
                        self.assertTrue(network_data[-1]["meta"]["bilingual"])
                    self.assertIn("Mykolaiv", (folder / "geography_south.html").read_text())
                if shutil.which("node"):
                    for html in folder.glob("*.html"):
                        for n, script in enumerate(re.findall(r'<script(?:\s[^>]*)?>(.*?)</script>', html.read_text(), re.S)):
                            if not script.strip() or script.lstrip().startswith('{'):
                                continue  # JSON payload and external scripts.
                            js = folder / f"{html.stem}-{n}.js"
                            js.write_text(script)
                            subprocess.run(["node", "--check", str(js)], check=True, capture_output=True)
            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(snapshots[0], snapshots[2])
            self.assertEqual(summaries[0], summaries[1])
            self.assertEqual(summaries[0], summaries[2])
            for data in term_data[1:]:
                for key in ("bases", "values", "examples", "periods"):
                    self.assertEqual(term_data[0][key], data[key])
            for data in network_data[1:]:
                for scope in network_data[0]["scopes"]:
                    for kind in ("cat", "block"):
                        original = network_data[0]["scopes"][scope][kind]
                        translated = data["scopes"][scope][kind]
                        self.assertEqual(original["nodes"], translated["nodes"])
                        for a, b in zip(original["edges"], translated["edges"]):
                            self.assertEqual({k: v for k, v in a.items() if k != "examples"},
                                             {k: v for k, v in b.items() if k != "examples"})
            self.assertEqual(records, original_records)


if __name__ == "__main__":
    unittest.main()
