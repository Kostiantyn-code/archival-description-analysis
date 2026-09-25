"""Classification of explicit personal-record headings and matching phrases."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fond_analysis as f


class PersonnelClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f.configure_analysis(yaml)
        f.configure_sources(yaml)
        cls.uk, cls.amb_uk, cls.blocks, _ = f.load_dictionaries(yaml)
        cls.ru, cls.amb_ru, _, _ = f.load_dictionaries(yaml, "ru")
        f.LANGUAGE_CATEGORIES.update(uk=cls.uk, ru=cls.ru)
        f.LANGUAGE_AMBIGUITIES.update(uk=cls.amb_uk, ru=cls.amb_ru)

    def topics(self, title: str, language: str = "uk") -> list[str]:
        return f.classify_title(
            title, self.uk, self.amb_uk, list(self.blocks), language,
        )[0]

    def test_residence_and_port_charges(self):
        self.assertIn("population_and_society", self.topics("Право на проживання євреїв"))
        self.assertIn("population_and_society", self.topics("Право проживання"))
        self.assertIn("economy", self.topics("Перегляд портових зборів"))
        self.assertIn("economy", self.topics("Пересмотр портовых сборов", "ru"))
        self.assertNotIn("economy", self.topics("Ремонт портових споруд"))

    def test_personnel_lists_and_unrelated_names(self):
        for title, language in [
            ("Особові справи лікарів", "uk"),
            ("Список учнів гімназії", "uk"),
            ("Личные дела заключённых", "ru"),
            ("Списки учеников гимназии", "ru"),
        ]:
            with self.subTest(title=title):
                self.assertIn("personal_files", self.topics(title, language))
        self.assertIn("education", self.topics("Списки учеников гимназии", "ru"))
        self.assertNotIn("personal_files", self.topics("Андрієв Іван"))

    def test_inventory_is_service_record(self):
        self.assertEqual(f.detect_status("2585", "Опис № 1 фонду № 229"), "inventory")
        self.assertEqual(f.detect_status("12", "Справа про видачу опису № 1"), "case")

    def test_headings_apply_through_letters_and_years_then_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            book = Workbook()
            sheet = book.active
            sheet.title = "Опис 1"
            sheet.append(["№", "Заголовок", "Крайні дати", "Кількість аркушів", "Примітки"])
            sheet.append([None, "Особові справи ув’язнених"])
            sheet.append([None, "«А»"])
            sheet.append([1, "Андрієв Іван (Андреев Иван)", "1902", "4"])
            sheet.append([None, "1903 рік"])
            sheet.append([2, "Бойко Петро (Бойко Петр)", "1903", "5"])
            sheet.append([None, "Поточна кореспонденція"])
            sheet.append([3, "Василенко Олег (Василенко Олег)", "1904", "6"])
            sheet.append([None, "Списки учнів гімназії"])
            sheet.append([4, "Гнатюк Марія (Гнатюк Мария)", "1905", "7"])
            sheet.append([5, "Опис № 1 фонду № 229 за 1900–1905 роки"])
            path = Path(temporary) / "input.xlsx"
            book.save(path)
            original_input = f.INPUT_FILE
            f.INPUT_FILE = path
            try:
                records, _, _ = f.read_records(__import__("openpyxl"))
            finally:
                f.INPUT_FILE = original_input
            f.classify_records(records, self.uk, self.amb_uk, list(self.blocks))
            cases = [record for record in records if record.status == "case"]
            self.assertEqual([r.thematic_section for r in cases], [
                "Особові справи ув’язнених", "Особові справи ув’язнених", "",
                "Списки учнів гімназії",
            ])
            self.assertEqual(set(cases[0].categories), {"personal_files", "law_and_police"})
            self.assertEqual(set(cases[1].categories), {"personal_files", "law_and_police"})
            self.assertFalse(cases[2].categories)
            self.assertEqual(set(cases[3].categories), {"personal_files", "education"})
            self.assertIn("розділ опису", f.record_to_row(cases[0])["evidence"])
            self.assertEqual(f.classification_index_row(cases[0])["thematic_section"],
                             "Особові справи ув’язнених")
            self.assertEqual(records[-1].status, "inventory")


if __name__ == "__main__":
    unittest.main()
