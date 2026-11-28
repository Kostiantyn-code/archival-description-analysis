# Реєстр населених пунктів / Settlement register

`tools/city_register.py` builds, searches and extends an offline SQLite register
of present-day and historical names. Use it as a reference when checking
geographical mentions in archival descriptions. The report maps use the
project's [curated geography vocabulary](../config/geography.yaml).

## Джерела / Sources

The baseline uses [GeoNames](https://www.geonames.org/export/) data under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

| Source | Fields used |
|---|---|
| [allCountries.zip](https://download.geonames.org/export/dump/allCountries.zip) | Settlement ID, main name, coordinates, country and administrative codes, feature type, population and modification date |
| [alternateNamesV2.zip](https://download.geonames.org/export/dump/alternateNamesV2.zip) | Alternative spellings, language, historical and other flags, optional dates of use |
| [countryInfo.txt](https://download.geonames.org/export/dump/countryInfo.txt) | Country codes and the European coverage filter |
| [city_name_additions.tsv](../config/city_name_additions.tsv) | Manually sourced names and inflections, with the source cited on each row |

Coverage includes Europe, all of Russia, the Caucasus, Central Asia, Turkey,
Cyprus and Alaska. The import keeps GeoNames feature class `P`, which includes
cities, villages, neighbourhoods and some historical or abandoned settlements.
Country and administrative codes follow the source catalogue. Establish
historical jurisdiction using evidence from the date of the document.

The 2026-11-28 verification build contains **1,056,742 places** and
**3,450,875 name records**, including **19,666 marked historical**.
Only **9,236** name records carry at least one date boundary. Each search
returns all matching records for review, including records for different
settlements with the same spelling. Counts vary by GeoNames snapshot.

| Input used for the verification build | SHA-256 |
|---|---|
| `allCountries.zip` | `0968a68a49fef43ffffff13ca57f2a32a23cbac18e7b9d9ff856032e77bf7fa0` |
| `alternateNamesV2.zip` | `1a8950e43c0757611ca40d4bb9cf7d12e925fa64ab6623699d85cb30a45c495c` |
| `countryInfo.txt` | `79f8f59ea01cbb40438bf1856dd6c2ff201f03f8fc72d0530b2646aaf603ef04` |

## Збірка й пошук / Build and search

Save the three GeoNames input files in one directory, such as `geonames`.
The tool uses Python's standard library. The database records input checksums,
snapshot dates and imports in its `metadata` table.

```text
python -X utf8 tools/city_register.py build geonames outputs/registry.sqlite --additions config/city_name_additions.tsv
python -X utf8 tools/city_register.py find outputs/registry.sqlite "Катеринослава" --country UA
python -X utf8 tools/city_register.py names outputs/registry.sqlite 709930 --language uk
```

`find` searches a full spelling with Unicode case and punctuation normalization.
`names` lists spellings attached to a place ID. Both commands output one JSON
object per line, including the matched form, main name, coordinates and source.

## Доповнення / Add names and places

Add a row to [city_name_additions.tsv](../config/city_name_additions.tsv) for a new
name, variant or inflected form. Use an existing `place_id` and fill in a source.
Record date bounds where the source provides them. For a new settlement, add a
row to [city_place_additions.tsv](../config/city_place_additions.tsv) with an
unused negative ID, name, coordinates, country, feature code and source.

```text
python -X utf8 tools/city_register.py add outputs/registry.sqlite --places config/city_place_additions.tsv --names config/city_name_additions.tsv
```

The import is transactional and supports repeat imports of the same rows.
Keep the TSV files to reapply local additions to later GeoNames snapshots.

One source conflict illustrates why candidate review matters. GeoNames lists
`New Archangel` for two places near Sitka. The U.S. National Park Service
distinguishes Old Sitka (GeoNames ID `5846378`) from the later settlement
New Archangel (ID `5557293`). The additions cite the historical name for
the latter. [National Park Service account](https://www.nps.gov/sitk/learn/historyculture/the-russians.htm)
