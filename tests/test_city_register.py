import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from tools import city_register


def write_dump(directory, stem, rows):
    with ZipFile(directory / f"{stem}.zip", "w") as archive:
        archive.writestr(f"{stem}.txt", "".join("\t".join(row) + "\n" for row in rows))


def place(identifier, name, country, admin1="", feature_class="P"):
    return (identifier, name, "", "", "59", "24", feature_class, "PPL", country, "",
            admin1, "", "", "", "120", "", "", "", "2026-11-28")


class CityRegisterTests(unittest.TestCase):
    def test_build_filters_places_and_preserves_ambiguous_and_dated_aliases(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            country_data = ["EE", "", "", "", "", "", "", "", "EU"]
            (folder / "countryInfo.txt").write_text("\t".join(country_data), encoding="utf-8")
            write_dump(folder, "allCountries", [
                place("1", "Tartu", "EE"),
                place("2", "Sitka", "US", "AK"),
                place("3", "Other place", "US", "WA"),
                place("4", "A river", "EE", feature_class="H"),
            ])
            write_dump(folder, "alternateNamesV2", [
                ("101", "1", "de", "Dorpat", "", "", "", "1", "1224", ""),
                ("102", "2", "en", "Dorpat", "", "", "", "", "", ""),
                ("103", "3", "en", "Dorpat", "", "", "", "", "", ""),
                ("104", "1", "link", "https://example.com", "", "", "", "", "", ""),
            ])
            database = folder / "register.sqlite"
            city_register.build(folder, database, None, None)

            with closing(sqlite3.connect(database)) as db:
                self.assertEqual([row[0] for row in db.execute("SELECT id FROM places ORDER BY id")], [1, 2])
                matches = list(city_register.lookup(db, "DORPAT"))
                self.assertEqual([row["id"] for row in matches], [1, 2])
                match = next(iter(city_register.lookup(db, "Dorpat", "ee")))
                self.assertEqual((match["historic"], match["used_from"]), (1, "1224"))
                self.assertFalse(list(city_register.lookup(db, "https://example.com")))
                metadata = dict(db.execute("SELECT key,value FROM metadata"))
                self.assertIn("alternateNamesV2.zip", metadata["sources_sha256"])

    def test_additions_persist_once_with_source_and_normalized_apostrophes(self):
        with TemporaryDirectory() as temporary, closing(sqlite3.connect(":memory:")) as db:
            folder = Path(temporary)
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(city_register.SCHEMA)
            places = folder / "places.tsv"
            places.write_text(
                "place_id\tname\tcountry\tadmin1\tadmin2\tfeature\tlatitude\tlongitude\tsource\n"
                "-1\tTest settlement\tUA\t\t\tPPL\t48\t30\tFixture\n",
                encoding="utf-8",
            )
            names = folder / "names.tsv"
            names.write_text(
                "place_id\tspelling\tlanguage\tkind\tused_from\tused_to\tsource\n"
                "-1\tТестів'я\tuk\thistorical\t1850\t1870\tFixture\n",
                encoding="utf-8",
            )
            for _ in range(2):
                with db:
                    city_register.apply_place_additions(db, places)
                    city_register.apply_additions(db, names)
            matches = list(city_register.lookup(db, "ТЕСТІВ’Я", "UA"))
            self.assertEqual(len(matches), 1)
            self.assertEqual((matches[0]["name"], matches[0]["source"]), ("Test settlement", "Fixture"))
            self.assertEqual(len(list(city_register.names_for_place(db, -1))), 2)
