# Method and reproducibility

## What is counted

The unit is a nonempty file description in a finding aid, not a document or an
historical event. Group/year headings and withdrawn entries are kept separate.
Counts may overlap: one description can receive several subject categories.
Incidental institutions, occupations and actors are recorded as context.

`dictionaries/en.yaml` defines 53 shared concepts, their scopes, subject/context
roles and eight co-occurrence rules. `uk.yaml`, `hr.yaml` and `it.yaml` supply
aliases for exactly those IDs. One subject concept contributes three points once,
regardless of the number of synonyms found. Context contributes no direct subject
score. A satisfied shared rule contributes three points in its target category.
The default threshold is three. These are heuristic weights, not probabilities.

Russian rules, in `ru.yaml`, retain their distinct weighted phrases, terms,
context rules and ambiguity masks. They have not been aligned to the 53 concepts.
Their existing decisions were preserved when consolidating the files. Do not
attribute differences between languages or sources solely to historical content.

UK/RU use light stemming, not full lemmatization. EN/HR/IT use Unicode NFC/casefold
and exact tokens with explicit word forms; accents are retained. Co-occurrence
operates across a whole title without resolving syntax, negation or attachment.
An arrest of a teacher does not itself establish an education subject. A repair
of a hospital satisfies an institutional-operation rule. Church finances can
receive both religion and economy. Multiple labels are intentional.

## Language and configuration

Each language is a single self-describing YAML file in `dictionaries/`. Adding a
file registers its language automatically. English is the reference; foreign
concept IDs and `reference_version` must match it. An unavailable equivalent is
`[]`, with no fallback to English search words. Versions, duplicate keys, unknown
IDs and word lists are validated on loading. Category labels, enable switches and
thresholds are controlled by `config/categories.yaml`; filenames default to IDs.

Language priority is: worksheet D1/E1, `analysis.sheet_languages`,
`analysis.language`, then heuristic inference. One pack is applied per worksheet;
mixed-language titles can be flagged but are not automatically translated.
Unidentified Latin-script sheets remain `undetermined`. Unsupported languages
are skipped with a notice. Use explicit language declarations for research.

Presentation is independently English or Ukrainian. Labels and trusted captions
come from `config/localization.json`. English category and lexical-marker labels in analytical tables remain
stable when the presentation language changes. Original descriptions are never
translated. As in earlier versions, CSV `*_raw` strings have outer whitespace
trimmed; the input XLSX is authoritative for exact cell contents.

## UDC and scope review

Concept IDs distinguish meanings even when they share a broader UDC number.
UDC anchors do not assert exact lexical equivalence or assign complete UDC numbers
to cases. Documentary forms and neutral actions receive no invented subject code.
The approach distinguishes concepts, labels and mappings as in
[W3C SKOS](https://www.w3.org/TR/skos-reference/); YAML is not an RDF/SKOS export.

Author-composed vocabulary and scope notes are not official UDC schedules or
certified translations. Sources consulted on 2026-10-23: [UDC subject coverage](https://udcc.org/index.php/site/page?view=subject_coverage),
[English](https://udcsummary.info/php/index.php?lang=en),
[Ukrainian](https://udcsummary.info/php/index.php?lang=uk),
[Croatian](https://udcsummary.info/php/index.php?lang=hr) and
[Italian](https://udcsummary.info/php/index.php?lang=it) UDC Summary, and the
[UDC factsheet](https://udcc.org/index.php/site/page?view=factsheet).
No complete schedule was imported. The Summary site states CC BY-NC 4.0 from
2026; the software licence does not replace the terms of external datasets.

Review decisions include removing Croatian `zatvaranje` from detention because
it also means institutional closure; qualifying `preseljenje` as population
resettlement; excluding generic injury/loss from crime; replacing political-exile
wording with `politički progon`; and keeping the historical descriptor
`pljačka radne snage` outside generic labour synonyms pending contextual review.
Italian `deliberazioni comunali` is not treated as the local-government institution.

## Outputs and verification

Every run creates a separate folder and records source/configuration checksums,
language-pack versions, software versions, selected categories and output paths
in `run_manifest.json`. A failed workbook is logged in `failure.txt` and the batch
summary; other workbooks continue. Tables and examples expose lexical evidence.

Subject XLSX selections copy original A–E values, metadata, selected rows, styles,
widths, row heights and worksheet order. `exports.source_columns` can include
additional columns. Empty worksheets remain. `unclassified.xlsx` contains all
case entries without a subject assignment, including context-only entries;
`service_records.xlsx` contains non-case rows. Original source-row identities
remain in CSV indexes. Selection counts overlap and must not be summed as unique
cases. These are search aids, not newly certified archival inventories.

```bash
python -m unittest discover -s tests -q
python tools/validate_language_packs.py --output outputs/validation
```

The second command generates a complete multilingual crosswalk and an input-hash
manifest, rather than storing duplicate generated tables in the repository. The
42 synthetic contrast sets contain 168 language cases. They test development
behaviour, not independent accuracy. No native-speaker certification or held-out
precision/recall estimate has been completed. Human review must include both
classified and unclassified titles, with the vocabulary frozen before evaluation.

Document forms, social/legal vocabulary and place mentions are exploratory
lookups, separate from the shared thematic-concept claim. Some foreign aliases
are deliberately empty. The small city list is not a full Croatian/Italian
gazetteer. Damage descriptors in the Croatian source are shorter and structurally
different from many Ukrainian file titles; coverage alone is not comparable.

## Map attribution

The offline basemap contains simplified modern boundaries. Ukrainian units derive
from [darmat1/ukraine-geo-data](https://github.com/darmat1/ukraine-geo-data/blob/main/geodata/Ukraine.geojson),
based on © OpenStreetMap contributors under [ODbL](https://www.openstreetmap.org/copyright).
Other European, Russian, Turkish and Georgian outlines derive from
[Natural Earth](https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson),
which is [public domain](https://www.naturalearthdata.com/about/terms-of-use/).
Geometry was simplified and attributes reduced. Attribution also appears on the
maps. These boundaries are not historical administrative divisions; approximate
city coordinates do not establish where an event occurred.
