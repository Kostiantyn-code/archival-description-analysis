# Preparing the Split war-damage inventory

Algorithm version: `split208-import-1.0`.

The input is the XLSX finding aid published by the State Archives in Split
for **HR-DAST-208, Gradska komisija za ratnu štetu Split, Ratna šteta – MNO Split**.
This is one published inventory within the fonds, rather than the entire fonds.

- Archive landing page: https://www.das.hr/obavijesna-pomagala/
- Source file: https://www.das.hr/wp-content/uploads/2021/09/HR-DAST-208-GRADSKA-KOMISIJA-ZA-RATNU-%C5%A0TETU-SPLIT_serija-Ratna-%C5%A1teta-MNO-Split.xlsx
- Snapshot retrieved on 22 October 2026.
- Source SHA-256: `3bba78d372ffdd33c81d975e0ee908e28dbe98fb84ae781c2e37c4c5cb557785`.

## Extraction and mapping

The Python preparation script reads the first worksheet directly from the
XLSX ZIP/XML structure, resolves shared strings, skips the two heading rows,
and retains every row with a non-whitespace value in source columns A–G.
Source order is retained. All 10,487 retained rows are from source rows
3–10,489; 10,469 have nonempty damage descriptions. There is no deduplication,
translation, spelling correction, category assignment, or date imputation.

The analysis workbook has one worksheet, MNO Split. The first three rows
contain archive, fonds and inventory metadata; row 4 contains column headings.
Ukrainian structural labels are retained for parser compatibility.
The metadata pair D1 = Language, E1 = hr declares the corpus language.
The source URL and checksum are recorded in D2:E3.

| Output | Value |
|---|---|
| A | Technical identifier HR-DAST-208_MNO-Split_rNNNNN, based on the source row |
| B | Verbatim damage description from source F |
| C | Verbatim registration date from source E |
| D | Empty; the source supplies no folio counts |
| E | JSON provenance: source row, date basis/quality, original source A–D/G values |
| F | Numeric source row |
| G–K | Original claim number, local committee, applicant, register number, technical unit |
| L | Date quality flag |

Only A–E are read by the analysis program. Extra columns are provided for
inspection. E retains the source metadata even when an export copies only
the five analytical columns. The generated identifier is a research key,
not a claim number or an archive-assigned file reference. Repeated claim
numbers remain separate rows. Empty descriptions remain empty; under the
current parser they are retained as 18 unrecognised rows and reported for review.

Dates in C concern registration and must not be described as dates of damage.
The converter separately flags 10,442 parsable dates, 14 unparsed strings,
12 invalid dates, and 19 missing dates. It does not change C. The analysis
program extracts years from that raw field, so a recognised year does not
establish that the complete calendar date is valid.

## Reproduction

Prepare the matrix and provenance with Python 3.10 or newer (standard library):

    python tools/prepare_split208.py path/to/original.xlsx path/to/prepared

Export the matrix in a Node environment with @oai/artifact-tool available:

    node tools/build_split208.mjs path/to/prepared --preview

The XLSX authoring stage requires that separate package; it is not installed
by the program's Python requirements or run.bat. The delivered XLSX is
already exported and can be placed directly in input/. Reproduction of the
row content is defined by the matrix and mapping. XLSX binary hashes can
differ between exports because of ZIP metadata; use row-level comparison in
addition to checksums.

Preparation writes split208_matrix.json, split208_row_mapping.json, and
split208_conversion_manifest.json. Export adds the output checksum and engine
to the manifest. The source checksum is checked before conversion; a changed
source is rejected and must be reviewed rather than silently treated as the
same dataset.

## Loading and interpretation

Copy HR-DAST-208_MNO-Split_input.xlsx into input/, select English report
presentation in config/analysis.yaml, and run run.bat (Python 3.12+).
No other workbook should be placed there unless it is also to be analysed.

The aligned vocabulary now includes Croatian. A declared hr corpus is analysed
with Croatian equivalents of the shared English reference concepts. These rules
are development-reviewed, not independently validated. See
[multilingual_vocabulary.md](multilingual_vocabulary.md). The earlier import-only
version skipped Croatian classification; any zero coverage from that version
was not an empirical finding about the archive. File conversion, dictionary
validation and report presentation remain separate reproducible operations.

## Suggested methods paragraph

The Croatian corpus was derived from the published XLSX inventory of the
Ratna šteta – MNO Split series within fonds HR-DAST-208 at the State Archives
in Split. A versioned extraction procedure resolved the workbook's shared
strings and retained all 10,487 nonempty data rows from the first worksheet,
including 18 entries without damage descriptions. The original Croatian
descriptors and registration dates were copied without translation or
normalisation into the analysis program's input schema. A stable research
identifier was generated from each source row number; original claim numbers
and other metadata were retained separately, including repeated values.
Absent folio counts were left blank. Date-quality flags were recorded without
correcting or imputing source dates. The original workbook, source and output
checksums, transformation specification and row-level mapping were retained
to support verification. This preparation stage performed no thematic coding.
