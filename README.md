# Archival Finding Aid Analysis

[Українська](#українська) · [English](#english)

## Українська

Програма аналізує заголовки справ з архівних описів XLSX. Вона формує тематичні
вибірки, таблиці відповідностей УДК, хронологію та звіти про згадки населених пунктів.

1. Установіть Python 3.12 або новіший і покладіть книги XLSX у `input/`.
2. У Windows запустіть `run.bat`. У Linux або macOS скористайтеся [командами нижче](#linux-and-macos).
3. Відкрийте `outputs/<запуск>/<книга>/report.html`. Поруч збережено CSV, графіки,
   тематичні вибірки й `run_manifest.json` з контрольними сумами.

Один аркуш відповідає одному опису. У [зразку XLSX](#xlsx-layout) можна замінити
`Archive`, `Fonds`, `Inventory` на «Архів», «Фонд», «Опис» і використати
українські заголовки колонок. У D1 введіть `Language`, у E1 — код мови заголовків
`uk`, `en`, `hr`, `it` або `ru`. Якщо відомостей про аркуші немає, залиште D4 порожньою.

Головний звіт відкривається українською та має перемикач п’яти мов.
У `config/analysis.yaml` параметр `visualization.language` задає мову відкриття,
а `visualization.alternate_languages: false` залишає одну версію.
Карти завантажують Leaflet через інтернет.

### Новий реєстр населених пунктів

Окремий офлайн-інструмент збирає та поповнює базу SQLite з GeoNames.
Пошук за історичним чи сучасним написанням повертає можливі місця,
джерела й відомі дати вжитку назви. У знімку від 28 листопада 2026 року
понад мільйон населених пунктів. [Джерела, запуск і доповнення реєстру](docs/city_register.md)

[Методологія та перевірка](docs/methodology.md) · [Підготовка хорватського опису](docs/split208_preparation.md)

## English

Analyse archival file titles in XLSX finding aids. Results include thematic
selections, UDC correspondence tables, chronologies and place-mention reports.

1. Install Python 3.12 or newer and put the XLSX workbooks in `input/`.
2. Run `run.bat` on Windows or use the [commands below](#linux-and-macos).
3. Open `outputs/<run>/<workbook>/report.html`. CSV tables, charts, thematic
   selections and the checksum manifest are in the same folder.

Each sheet represents one inventory. Set D1 to `Language` and E1 to the language
of the file titles (`uk`, `en`, `hr`, `it` or `ru`). Leave D4 blank if folio
counts are unavailable. Ukrainian headers are also accepted.

The main report opens in Ukrainian with a five-language switcher.
In `config/analysis.yaml`, use `visualization.language` to change the opening
language and `visualization.alternate_languages: false` to produce one version.
Maps load Leaflet over the internet.

### New settlement register

A standalone tool builds and extends an offline GeoNames SQLite register.
Search by modern or historical spelling to find candidates, sources and any
recorded dates of use. [Sources and commands](docs/city_register.md)

[Method and validation](docs/methodology.md) · [Croatian source preparation](docs/split208_preparation.md)

### XLSX layout

| Row | A | B | C | D | E |
|---|---|---|---|---|---|
| 1 | Archive | Example archive | | Language | en |
| 2 | Fonds | 230 | | | |
| 3 | Inventory | 1 | | | |
| 4 | No. | Title | Dates | Folios | Notes |
| 5 | 1 | Opening a school | 1850 | 12 | |

### Linux and macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python fond_analysis.py
```
