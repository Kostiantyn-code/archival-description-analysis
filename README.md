# Archival Finding Aid Analysis

[English](#english) · [Українська](#українська)

## English

Explore the thematic structure of archival finding aids from XLSX inventories.
The program produces an HTML report, charts, auditable CSV tables and thematic
XLSX selections. It analyses descriptions, not the documents inside each file.

### Run

Install Python 3.12 or newer. On **Windows**, put your workbooks in `input/` and
run `run.bat`; it creates a local environment and installs the dependencies.
On **Linux/macOS**, run these commands in the downloaded project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python fond_analysis.py
```

### Input

Each worksheet represents one inventory. Use this layout; Ukrainian headers are
also accepted. `Fonds` identifies the archival collection. D1/E1 explicitly set
the language of the descriptions, independently of the report language.

| Row | A | B | C | D | E |
|---|---|---|---|---|---|
| 1 | Archive | Example archive | | Language | en |
| 2 | Fonds | 230 | | | |
| 3 | Inventory | 1 | | | |
| 4 | No. | Title | Dates | Folios | Notes |
| 5 | 1 | Opening a school | 1850 | 12 | |

Use language codes `en`, `uk`, `hr`, `it` or `ru`. Leave D4 empty when the source
has no folio counts. Keep original descriptions; no translation is required.
Each workbook is analysed separately, with inventory and fonds breakdowns.

### Settings and results

Edit `config/analysis.yaml`. Reports are **English by default**; set
`visualization.language: uk` for Ukrainian. `analysis.language: auto` uses the
worksheet declaration or language inference; explicit declarations are preferable
for research. `exports.enabled: false` skips thematic workbook/CSV selections.

Results appear in `outputs/<run>/<workbook>/report.html`. The same folder contains
`reports/`, `figures/`, `tables/`, `thematic_exports/` and `run_manifest.json` with
source/configuration checksums. Earlier runs and input workbooks are retained.
Maps need internet to load Leaflet; the other reports work locally.

### Method and reproducibility

English, Ukrainian, Croatian and Italian share 53 concepts and eight rules.
UDC numbers are broader subject anchors; concept IDs define equivalence.
Russian retains its separate historical-description rules. One YAML file per
language is in `dictionaries/`; categories are in `config/categories.yaml`.

Coverage is not accuracy. Context, spelling, language and descriptive conventions
can affect the results; independent linguistic and corpus validation is still
needed. Record the code revision and run manifest when citing results.

[Method, exports and data attribution](docs/methodology.md) ·
[Reproduce the Croatian source conversion](docs/split208_preparation.md)

```bash
python -m unittest discover -s tests -q
python tools/validate_language_packs.py --output outputs/validation
```

## Українська

Дослідження тематичної структури архівних описів у форматі XLSX. Програма створює
HTML-звіт, графіки, перевірні CSV-таблиці й тематичні XLSX-вибірки. Вона аналізує
описи, а не документи всередині справ.

### Запуск

Установіть Python 3.12 або новіший. У **Windows** покладіть книги в `input/`
і запустіть `run.bat`: він створить локальне середовище та встановить залежності.
У **Linux/macOS** виконайте ці команди в завантаженій папці проєкту:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python fond_analysis.py
```

### Вхідні дані

Кожен аркуш представляє один опис. Використовуйте наведену структуру; українські
назви колонок також підтримуються. `Fonds` означає архівний фонд. D1/E1 явно
задають мову описів незалежно від мови звіту.

| Рядок | A | B | C | D | E |
|---|---|---|---|---|---|
| 1 | Архів | Назва архіву | | Language | uk |
| 2 | Фонд | 230 | | | |
| 3 | Опис | 1 | | | |
| 4 | № | Заголовок справи | Крайні дати | Кількість аркушів | Примітки |
| 5 | 1 | Відкриття школи | 1850 | 12 | |

Коди мов: `en`, `uk`, `hr`, `it`, `ru`. Залиште D4 порожньою, якщо джерело не
містить кількості аркушів. Зберігайте оригінальні описи, переклад не потрібен.
Кожна книга аналізується окремо з розподілами за описами й фондами.

### Налаштування й результати

Редагуйте `config/analysis.yaml`. Звіти **типово англійською**; для української
встановіть `visualization.language: uk`. Параметр `analysis.language: auto`
використовує зазначення мови на аркуші або її евристичне визначення; для
дослідження бажано задавати мову явно. `exports.enabled: false` вимикає тематичні
XLSX/CSV-вибірки.

Результат: `outputs/<запуск>/<книга>/report.html`. Поруч містяться `reports/`,
`figures/`, `tables/`, `thematic_exports/` і `run_manifest.json` із контрольними
сумами джерела й налаштувань. Попередні результати та вхідні книги зберігаються.
Карти потребують інтернету для Leaflet, решта звітів працює локально.

### Метод і відтворюваність

Англійська, українська, хорватська й італійська використовують 53 спільні поняття
та вісім правил. Індекси УДК задають ширші тематичні орієнтири, а відповідність
визначають ідентифікатори понять. Російська зберігає окремі правила для історичних
описів. У `dictionaries/` є один YAML-файл на мову, категорії задані в
`config/categories.yaml`.

Покриття не є точністю. Контекст, правопис, мова та практика описування впливають
на результати; незалежна лінгвістична й корпусна перевірка ще потрібна. Для
цитування результатів фіксуйте версію коду та маніфест запуску.

[Метод, експорт і походження даних](docs/methodology.md) ·
[Відтворення конвертації хорватського джерела](docs/split208_preparation.md)

```bash
python -m unittest discover -s tests -q
python tools/validate_language_packs.py --output outputs/validation
```
