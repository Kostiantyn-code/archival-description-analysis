"""Build and search an offline GeoNames settlement register (Python standard library)."""

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


EXTRA = set("AM AZ CY GE KG KZ TJ TM TR UZ".split())
BASE = "https://download.geonames.org/export/dump/"
SCHEMA = """
CREATE TABLE places (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, country TEXT NOT NULL,
    admin1 TEXT, admin2 TEXT, feature TEXT NOT NULL, latitude REAL NOT NULL,
    longitude REAL NOT NULL, population INTEGER, updated TEXT, source TEXT NOT NULL
);
CREATE TABLE names (
    place_id INTEGER NOT NULL REFERENCES places(id), spelling TEXT NOT NULL,
    search_key TEXT NOT NULL, language TEXT, kind TEXT NOT NULL, historic INTEGER,
    preferred INTEGER, short INTEGER, colloquial INTEGER, used_from TEXT, used_to TEXT,
    alternate_id INTEGER, source TEXT NOT NULL
);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def key(text):
    text = unicodedata.normalize("NFC", text).casefold()
    return " ".join(text.replace("’", "'").replace("ʼ", "'").replace("‑", "-").split())


def lines(directory, stem):
    with ZipFile(directory / (stem + ".zip")) as archive, archive.open(stem + ".txt") as stream:
        for raw in stream:
            yield raw.decode("utf-8").rstrip("\r\n").split("\t")


def batches(db, sql, values):
    batch = []
    for row in values:
        batch.append(row)
        if len(batch) >= 20000:
            db.executemany(sql, batch)
            batch.clear()
    db.executemany(sql, batch)


def place_rows(directory, countries, ids):
    for row in lines(directory, "allCountries"):
        if row[6] != "P" or not (row[8] in countries or (row[8], row[10]) == ("US", "AK")):
            continue
        pid = int(row[0])
        ids.add(pid)
        yield (pid, row[1], row[8], row[10], row[11], row[7], float(row[4]),
               float(row[5]), int(row[14]) if row[14] else None, row[18], "GeoNames")


def alias_rows(directory, ids):
    for row in lines(directory, "alternateNamesV2"):
        aid, pid, lang, name, pref, short, colloq, historic, start, end = row
        if int(pid) not in ids or not name:
            continue
        if lang and not (re.fullmatch(r"[a-z]{2,3}(?:[-_][a-zA-Z0-9_-]+)?", lang)
                             or lang == "abbr"):
            continue
        if lang == "wkdt" or lang in {"iata", "icao", "post", "link", "unlc", "faac"}:
            continue
        yield (int(pid), name, key(name), lang, "alternate", int(historic == "1"),
               int(pref == "1"), int(short == "1" or lang == "abbr"), int(colloq == "1"),
               start, end, int(aid), "GeoNames")


def tsv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        yield from csv.DictReader(stream, delimiter="\t")


def record_import(db, path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    db.execute("INSERT OR IGNORE INTO metadata VALUES (?,?)", ("import:" + digest, path.name))


def apply_place_additions(db, path):
    for row in tsv_rows(path):
        pid = int(row["place_id"])
        name = row["name"].strip()
        country = row["country"].strip().upper()
        lat, lon = float(row["latitude"]), float(row["longitude"])
        source = row["source"].strip()
        feature = row["feature"].strip().upper()
        if (pid >= 0 or not name or not source or not re.fullmatch(r"[A-Z]{2}", country)
                or not re.fullmatch(r"PPL[A-Z0-9]*", feature)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180):
            raise ValueError(f"Invalid local place: {row}")
        values = (pid, name, country, row["admin1"], row["admin2"], feature, lat, lon,
                  None, None, source)
        previous = db.execute("SELECT * FROM places WHERE id=?", (pid,)).fetchone()
        if previous is not None:
            if previous != values:
                raise ValueError(f"Local place ID {pid} is already assigned to a different place")
            continue
        db.execute("INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?,?,?)", values)
        db.execute("INSERT INTO names VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (pid, name, key(name), "", "primary", 0, 0, 0, 0, "", "", None, source))
    record_import(db, path)


def apply_additions(db, path):
    for row in tsv_rows(path):
        name = row["spelling"].strip()
        source = row["source"].strip()
        kind = row["kind"].strip()
        pid = int(row["place_id"])
        lang, start, end = (row[field].strip() for field in ("language", "used_from", "used_to"))
        if not name or not source or kind not in {"historical", "variant", "inflected"}:
            raise ValueError(f"Invalid name addition: {row}")
        exists = db.execute("""SELECT 1 FROM names WHERE place_id=? AND search_key=?
                             AND spelling=? AND language=? AND kind=? AND used_from=?
                             AND used_to=? AND source=? LIMIT 1""",
                            (pid, key(name), name, lang, kind, start, end, source)).fetchone()
        if not exists:
            db.execute("INSERT INTO names VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                pid, name, key(name), lang, kind, int(kind == "historical"),
                0, 0, 0, start, end, None, source))
    record_import(db, path)


def build(inputs, destination, additions, place_additions):
    if destination.exists():
        raise FileExistsError(f"{destination} already exists. Choose a new database path.")
    countries = set(EXTRA)
    for line in (inputs / "countryInfo.txt").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            fields = line.split("\t")
            if fields[8] == "EU":
                countries.add(fields[0])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temporary:
        output = Path(temporary) / "cities.sqlite"
        with closing(sqlite3.connect(output)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript(SCHEMA)
            ids = set()
            batches(db, "INSERT INTO places VALUES (?,?,?,?,?,?,?,?,?,?,?)", place_rows(inputs, countries, ids))
            sql = "INSERT INTO names VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            batches(db, sql, ((pid, name, key(name), "", "primary", 0, 0, 0, 0, "", "", None, "GeoNames")
                              for pid, name in db.execute("SELECT id,name FROM places")))
            batches(db, sql, alias_rows(inputs, ids))
            db.execute("CREATE INDEX name_lookup ON names(search_key, place_id)")
            db.execute("CREATE INDEX place_names ON names(place_id)")
            if place_additions:
                apply_place_additions(db, place_additions)
            if additions:
                apply_additions(db, additions)
            sources = {}
            snapshots = {}
            for filename in ("countryInfo.txt", "allCountries.zip", "alternateNamesV2.zip"):
                with (inputs / filename).open("rb") as file:
                    sources[BASE + filename] = hashlib.file_digest(file, "sha256").hexdigest()
                if filename.endswith(".zip"):
                    with ZipFile(inputs / filename) as archive:
                        timestamp = archive.getinfo(Path(filename).stem + ".txt").date_time
                    snapshots[filename] = f"{timestamp[0]:04}-{timestamp[1]:02}-{timestamp[2]:02}"
            meta = {"schema": "2", "sources_sha256": json.dumps(sources, ensure_ascii=False),
                    "snapshots": json.dumps(snapshots),
                    "countries": " ".join(sorted(countries)), "extra_region": "US-AK",
                    "attribution": "GeoNames, https://www.geonames.org/, CC BY 4.0"}
            db.executemany("INSERT INTO metadata VALUES (?,?)", meta.items())
            db.commit()
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Database integrity check failed")
        output.replace(destination)


NAME_COLUMNS = """SELECT DISTINCT p.id,p.name,p.country,p.admin1,p.admin2,p.feature,p.latitude,p.longitude,
                    n.spelling,n.language,n.kind,n.historic,n.used_from,n.used_to,n.source,n.alternate_id,
                    CASE WHEN p.id > 0 THEN 'https://www.geonames.org/' || p.id || '/' END AS place_url
             FROM names n JOIN places p ON p.id=n.place_id WHERE """
NAME_ORDER = " ORDER BY p.id,n.kind,n.language,n.spelling"


def lookup(db, spelling, country=None):
    db.row_factory = sqlite3.Row
    sql = NAME_COLUMNS + "n.search_key=?"
    args = [key(spelling)]
    if country:
        sql += " AND p.country=?"
        args.append(country.upper())
    return db.execute(sql + NAME_ORDER, args)


def names_for_place(db, place_id, language=None):
    db.row_factory = sqlite3.Row
    sql = NAME_COLUMNS + "p.id=?"
    args = [place_id]
    if language:
        sql += " AND n.language=?"
        args.append(language.lower())
    return db.execute(sql + NAME_ORDER, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("build")
    create.add_argument("inputs", type=Path)
    create.add_argument("database", type=Path)
    create.add_argument("--additions", type=Path)
    create.add_argument("--places", type=Path)
    search = sub.add_parser("find")
    search.add_argument("database", type=Path)
    search.add_argument("spelling")
    search.add_argument("--country")
    show = sub.add_parser("names", help="Show recorded names for a settlement ID")
    show.add_argument("database", type=Path)
    show.add_argument("place_id", type=int)
    show.add_argument("--language")
    extend = sub.add_parser("add", help="Import local names or settlements into an existing database")
    extend.add_argument("database", type=Path)
    extend.add_argument("--names", type=Path)
    extend.add_argument("--places", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        build(args.inputs, args.database, args.additions, args.places)
    elif args.command == "add":
        if not (args.names or args.places):
            extend.error("pass --names, --places, or both")
        with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=rw", uri=True)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                if args.places:
                    apply_place_additions(db, args.places)
                if args.names:
                    apply_additions(db, args.names)
    else:
        with closing(sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            rows = (lookup(db, args.spelling, args.country) if args.command == "find"
                    else names_for_place(db, args.place_id, args.language))
            for row in rows:
                print(json.dumps(dict(row), ensure_ascii=False))


if __name__ == "__main__":
    main()
