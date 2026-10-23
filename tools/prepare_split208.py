"""Prepare the published Split inventory as an auditable input matrix.

Standard-library extraction only. The matrix is exported to XLSX by
build_split208.mjs; no classification or translation occurs in this step.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

VERSION = "split208-import-1.0"
SOURCE_URL = "https://www.das.hr/wp-content/uploads/2021/09/HR-DAST-208-GRADSKA-KOMISIJA-ZA-RATNU-%C5%A0TETU-SPLIT_serija-Ratna-%C5%A1teta-MNO-Split.xlsx"
LANDING_URL = "https://www.das.hr/obavijesna-pomagala/"
EXPECTED_SHA256 = "3bba78d372ffdd33c81d975e0ee908e28dbe98fb84ae781c2e37c4c5cb557785"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
FIELDS = ["claim_number", "local_committee", "applicant", "register_number",
          "registration_date", "damage_description", "technical_unit"]


def read_rows(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as archive:
        shared = ["".join(item.itertext()) for item in
                  ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        rows = []
        for row in ET.fromstring(archive.read("xl/worksheets/sheet1.xml")).findall("s:sheetData/s:row", NS):
            source_row = int(row.attrib["r"])
            if source_row < 3:
                continue
            cells = {}
            for cell in row.findall("s:c", NS):
                raw = cell.find("s:v", NS)
                value = "" if raw is None else raw.text or ""
                if cell.get("t") == "s" and value:
                    value = shared[int(value)]
                elif cell.get("t") == "inlineStr":
                    value = "".join(cell.find("s:is", NS).itertext())
                cells[re.sub(r"\d", "", cell.attrib["r"])] = value
            values = [cells.get(column, "") for column in "ABCDEFG"]
            if any(value.strip() for value in values):
                rows.append({"source_row": source_row, **dict(zip(FIELDS, values))})
        return rows


def date_status(value: str) -> str:
    if not value.strip():
        return "missing"
    match = re.fullmatch(r"(\d{1,2})\.([IVX]+|\d{1,2})\.(\d{4})",
                         re.sub(r"\s+", "", value.upper()).rstrip("."))
    if not match:
        return "unparsed"
    romans = {v: i for i, v in enumerate("I II III IV V VI VII VIII IX X XI XII".split(), 1)}
    day, month, year = match.groups()
    try:
        date(int(year), int(month) if month.isdigit() else romans[month], int(day))
    except (ValueError, KeyError):
        return "invalid"
    return "parsed"


def prepare(source: Path, output: Path) -> dict:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError("Source SHA-256 differs from the documented inventory snapshot. Review the new source before adapting the converter.")
    rows = read_rows(source)
    matrix = [
        ["Архів", "Državni arhiv u Splitu", None, "Language", "hr"] + [None] * 7,
        ["Фонд", "HR-DAST-208", None, "Source", SOURCE_URL] + [None] * 7,
        ["Опис", "Ratna šteta – MNO Split", None, "SHA-256", digest] + [None] * 7,
        ["№ з/п", "Заголовок справи", "Крайні дати", "", "Примітки",
         "Source row", "Claim number", "Local committee", "Applicant", "Register number", "Technical unit", "Date status"],
    ]
    mapping = []
    for row in rows:
        source_row = row["source_row"]
        record_id = f"HR-DAST-208_MNO-Split_r{source_row:05d}"
        status = date_status(row["registration_date"])
        notes = json.dumps({"source_row": source_row, "date_basis": "registration_date",
                            "date_status": status, **{key: row[key] for key in FIELDS if key not in {"damage_description", "registration_date"}}}, ensure_ascii=False)
        matrix.append([record_id, row["damage_description"], row["registration_date"], None, notes,
                       source_row, row["claim_number"], row["local_committee"], row["applicant"],
                       row["register_number"], row["technical_unit"], status])
        mapping.append({"record_id": record_id, "source_row": source_row, "output_row": len(matrix)})
    manifest = {
        "algorithm_version": VERSION, "source_url": SOURCE_URL, "landing_url": LANDING_URL,
        "source_sha256": digest, "source_member": "xl/worksheets/sheet1.xml",
        "source_rows": [rows[0]["source_row"], rows[-1]["source_row"]], "records": len(rows),
        "nonempty_descriptions": sum(bool(row["damage_description"].strip()) for row in rows),
        "date_status_counts": dict(Counter(date_status(row["registration_date"]) for row in rows)),
        "original_claim_numbers_repeated": {key: value for key, value in Counter(row["claim_number"] for row in rows if row["claim_number"].strip()).items() if value > 1},
        "mapping": {"A": "derived unique identifier, based on source row", "B": "source F, verbatim damage description",
                    "C": "source E, verbatim registration date (not the date of damage)", "D": "blank: no folio counts in source",
                    "E": "JSON provenance and source A–D/G values; date quality flag", "F": "source row number",
                    "G": "source A", "H": "source B", "I": "source C", "J": "source D", "K": "source G", "L": "derived date quality flag"},
        "rules": ["Keep source order and every nonempty row from row 3 onward.",
                  "No translation, spelling correction, lowercasing, category assignment, deduplication or date imputation.",
                  "Retain blank descriptions and repeated claim numbers. The technical identifier is not an archival file number.",
                  "Only the published Ratna šteta – MNO Split inventory is represented, not the whole fonds.",
                  "The program reads A–E. Additional columns preserve accessible source metadata."]}
    output.mkdir(parents=True, exist_ok=True)
    for name, data in [("split208_matrix.json", matrix), ("split208_row_mapping.json", mapping), ("split208_conversion_manifest.json", manifest)]:
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = prepare(args.source, args.output)
    print(json.dumps({key: result[key] for key in ("algorithm_version", "records", "nonempty_descriptions", "date_status_counts", "source_sha256")}, indent=2))
