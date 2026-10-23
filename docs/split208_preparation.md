# Croatian corpus: reproducible source conversion

This converter prepares the published **Ratna šteta – MNO Split** inventory of
HR-DAST-208, City Commission for War Damage, held by the State Archives in Split.
It represents that inventory, not the entire fonds. The field analysed is a short
war-damage descriptor, not necessarily a full archival file title.

[Finding aids page](https://www.das.hr/obavijesna-pomagala/) ·
[Source XLSX](https://www.das.hr/wp-content/uploads/2021/09/HR-DAST-208-GRADSKA-KOMISIJA-ZA-RATNU-%C5%A0TETU-SPLIT_serija-Ratna-%C5%A1teta-MNO-Split.xlsx)

The documented snapshot has SHA-256
`3bba78d372ffdd33c81d975e0ee908e28dbe98fb84ae781c2e37c4c5cb557785`.
A changed source is rejected for review. Install `requirements.txt`, then run:

```bash
python tools/prepare_split208.py path/to/source.xlsx outputs/split208
```

One Python command creates:

- `HR-DAST-208_MNO-Split_input.xlsx`, ready to copy into `input/`;
- `split208_row_mapping.json`, linking derived IDs to source and output rows;
- `split208_conversion_manifest.json`, recording the algorithm, source/output
  checksums, mapping decisions, date checks and counts.

Algorithm version `split208-import-1.1` combines extraction and XLSX export;
version 1.0 used a separate Node exporter. No Node or proprietary authoring package
is now required. Extraction still reads the original XLSX/XML values so that date
strings and descriptions are preserved without spreadsheet date coercion.

## Mapping

Keep every nonempty source row from row 3 onwards, in source order. The snapshot
contains **10,487 records**, including **10,469 nonempty descriptions** and
18 records without a description. Repeated claim numbers are retained.

| Output | Meaning |
|---|---|
| A | Derived ID `HR-DAST-208_MNO-Split_rNNNNN`, based on source row |
| B | Source F: verbatim damage description |
| C | Source E: verbatim registration date |
| D | Empty; the source has no folio counts |
| E | JSON provenance, other source fields and date-quality status |
| F–L | Source row, claim, local committee, applicant, register, technical unit, date status |

The registration date is not the date of damage. Invalid or incomplete dates are
flagged, not repaired or imputed: 10,442 parsed, 14 unparsed, 19 missing, 12 invalid.
No translation, spelling correction, normalization, deduplication or classification
occurs during conversion. All strings, including a literal leading `=`, are
written as text. Derived IDs are technical row identifiers, not archive-assigned
file or claim numbers. Metadata D1/E1 explicitly declares `hr`; blank D4 suppresses
individual missing-folio warnings in the analyser.

## Analysis and interpretation

Copy the generated XLSX into `input/` and run the analyser. English reports are the
default. The Croatian pack uses shared English reference concepts; its independent
linguistic accuracy has not been established. Keep the conversion manifest with
the analysis manifest. The analyser retains the existing outer-whitespace trim
in CSV text fields; the source XLSX preserves exact input strings.

A full execution check on the imported snapshot processed all 10,469 nonempty
descriptions with the declared Croatian pack. That verifies execution and source
mapping, not classification accuracy. The source type and historical terminology
require separate manual review before comparison with Ukrainian finding aids.
