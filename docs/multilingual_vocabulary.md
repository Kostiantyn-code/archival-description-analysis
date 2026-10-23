# Shared multilingual vocabulary, version 1.0-reviewed-draft

## Identity and UDC alignment

The English reference defines **53 concepts**, their scope, subject/context role,
category, and eight co-occurrence rules. Ukrainian, Croatian and Italian files
provide labels and search expressions for precisely the same identifiers.
No language silently inherits English search words when its equivalent is absent.
English is the editorial reference language; concept identity, rather than the
English spelling, determines the classification rule.

This design follows the distinction in [W3C SKOS](https://www.w3.org/TR/skos-reference/)
between a concept, its labels in different languages, and mappings to other schemes.
The YAML files are not an RDF/SKOS export and do not claim SKOS conformance.

UDC numbers are **broader subject anchors**, not unique IDs for our terms and not
assertions of `skos:exactMatch`. For example, education, educational institutions,
and teaching staff have different concept IDs but can share the broader anchor 37.
An actor or institution mention alone contributes context, not a subject score.
Personal documentation is a documentary facet, so it has no invented subject UDC
number. Neutral actions (institution operation and appointment) have no UDC number.

The complete crosswalk, including every search form, label, role, scope and UDC
anchor, is in [vocabulary_alignment.csv](vocabulary_alignment.csv). It is generated
from the actual dictionaries, not maintained as a separate source of truth.

## Checked sources and boundaries

Sources consulted on 2026-10-23:

- [UDC Consortium: subject coverage](https://udcc.org/index.php/site/page?view=subject_coverage)
- [UDC Summary: English](https://udcsummary.info/php/index.php?lang=en),
  [Ukrainian](https://udcsummary.info/php/index.php?lang=uk),
  [Croatian](https://udcsummary.info/php/index.php?lang=hr),
  [Italian](https://udcsummary.info/php/index.php?lang=it)
- [UDC Consortium: factsheet and indexing use](https://udcc.org/index.php/site/page?view=factsheet)
- [W3C SKOS Reference](https://www.w3.org/TR/skos-reference/)

Search expressions and English scope notes are author-composed. They are **not
copied official UDC captions or certified translations**. UDC anchors establish
subject placement, not the correctness of every lexical equivalent. No complete
UDC schedule was imported. The current UDC Summary site states CC BY-NC 4.0 from
2026; older releases had different terms. A previous reference to CC BY-SA 3.0
must not be read as the licence of the current Summary.

The review checked concept identity, semantic scope, obvious ambiguity, explicit
forms, schema consistency and development examples. **No independent native-speaker
review or precision/recall evaluation on a held-out corpus has been completed.**
The version suffix `reviewed-draft` describes this limited development review;
`validation_status` explicitly records `structural_and_contrastive_checks_only`.

## Decisions recorded during this review

| Expression or issue | Decision and reason |
|---|---|
| Croatian `zatvaranje` | Removed from arrest/detention: can mean closure of a school or another institution. Use `uhićenje`, `pritvor`, or an explicit deprivation-of-liberty phrase. |
| Croatian `političko progonstvo` | Replaced with `politički progon`; political exile is not interchangeable with every political persecution event. |
| Croatian `preseljenje` | Qualified as `preseljenje stanovništva`: moving an office does not establish migration. |
| Generic injury, harm and loss phrases | Removed from `crime`: harm or damage alone does not prove a criminal offence. |
| Croatian `pljačka radne snage` | Removed from generic labour aliases. This historical corpus phrase needs source-specific interpretation, rather than an unqualified claim of lexical equivalence. |
| Italian `deliberazioni comunali` | Removed from the institution concept `local_government`; an administrative act is not the institution itself. |
| Ukrainian teacher/doctor mentions | Context only, as in the other aligned languages. Arrest of a teacher does not add education. Appointment of a physician has a shared healthcare rule. |
| Church finances | Both religion and economy are assigned: this is intentional multilabel classification in all four languages. |
| Household goods stolen | Both goods/economy and crime/law may be assigned; evidence describes lexical subject mentions. |
| Several aliases for the same concept | One direct concept score (3), not one score per synonym or word form. |
| A concept copied into another category's rule | Used only for that rule; its direct subject score remains in its own category. |

## Runtime and compatibility

Default `analysis.vocabulary_mode: aligned` uses shared concepts for EN/UK/HR/IT.
Russian retains the pre-existing rules and is explicitly marked
`legacy_category_ids_only`; it is not presented as part of the aligned comparison.
The previous Ukrainian dictionaries and ambiguity rules remain intact. Set
`analysis.vocabulary_mode: legacy_uk` to use them and reproduce their behaviour.
The Python loader also accepts `load_dictionaries(yaml, 'uk', legacy=True)`.
The new Ukrainian thematic results intentionally differ from version 0.8-draft;
this is a versioned replacement core vocabulary, not a claim that every legacy
rule was translated. Re-run a complete comparison using one frozen mode/version;
do not combine older Ukrainian percentages with new Croatian percentages.

Matching is language-specific: UK uses the existing light stemmer; EN/HR/IT use
Unicode NFC/casefold and exact tokens with explicit inflected forms. This is not
lemmatization or machine translation. Accents are preserved. Co-occurrence rules
operate across the title, not on syntax, negation or semantic attachment.

`D1=Language, E1=hr` in an input sheet overrides a configured language. Otherwise
`analysis.sheet_languages`, then `analysis.language`, then inference apply.
An unidentified Latin-language sheet is left `undetermined`, not sent to Ukrainian.
For reproducible studies, declare each sheet's language explicitly. A sheet is
analysed with one language pack; mixed-language records receive heuristic review
flags, not automatic sentence-level language switching.

The interface/report language remains only `uk` or `en` in `visualization.language`.
Ancillary document-form, terminology and place modules remain exploratory mention
lookups. UK/RU retain their existing regexes; EN/HR/IT include their own aliases.
They are **not** covered by the 53-concept thematic equivalence claim. Some legal
or social statuses deliberately have an empty list in a foreign pack. The city
list is limited and is not a Croatian or Italian gazetteer; zero mentions do not
prove geographic absence.

## Reproduction and extension

```bash
python -m unittest discover -s tests -q
python tools/validate_language_packs.py
python tools/validate_language_packs.py --write
```

The checks cover 42 independently authored synthetic contrast sets, each in four
languages (168 language cases), plus Unicode, score stability, unsupported-language
handling, schema/version failures, declarative extension and legacy compatibility.
A complete import/report smoke run on HR-DAST-208 processed 10,469 nonempty
Croatian descriptors; [its recorded result](split208_vocabulary_smoke.json)
includes the source XLSX checksum. All source descriptions match the exported
text after the program’s pre-existing outer-whitespace trimming. They are not
translated. This source contains short war-damage descriptors, so subject
coverage is not directly comparable to coverage of full Ukrainian file titles.

These are development fixtures; they are **not** an independent test set or an
accuracy estimate. `docs/vocabulary_checks.json` records counts and input hashes.

To add a language, register a data file in `config/languages.yaml`, use the same
reference IDs and version, provide preferred labels, explicit forms and metadata,
and set a supported matching profile. An unavailable equivalent is an empty list,
never a guessed translation. Add positive and negative development examples, then
have a subject specialist validate a separate frozen sample before claiming
comparative accuracy. No Python language switch or new interface is required.
