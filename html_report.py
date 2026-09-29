"""Workbook report assembled from existing results, without reclassification."""
from __future__ import annotations

import csv
import html
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from models import Issue, Record


CHARTS = {
    "cases_by_decade": "Справи за десятиліттями",
    "cases_by_year": "Справи за роками й описами",
    "thematic_categories": "Тематичні категорії",
    "classification_coverage": "Покриття класифікацією",
    "included_and_withdrawn": "Включені та вибулі записи",
    "document_types": "Згадки типів документів",
    "themes_by_decade": "Теми за десятиліттями",
}
INTERACTIVE = {
    "theme_links.html": "Зв’язки між темами справ",
    "terminology_evolution.html": "Еволюція термінології",
    "geography_south.html": "Географія: Південь України",
    "geography_europe.html": "Географія: Європа",
    "geography_russia.html": "Географія: європейська частина РФ",
}


def _escape(value) -> str:
    return html.escape(str(value if value is not None else "—"), quote=True)


def _url(path: Path, root: Path) -> str:
    return quote(path.relative_to(root).as_posix(), safe="/")


def _link(path: Path, root: Path, label: str | None = None) -> str:
    return f'<a href="{_url(path, root)}">{_escape(label or path.name)}</a>'


def _table(headers, rows) -> str:
    rows = list(rows)
    if not rows:
        return '<p class="muted">Немає даних для цього зрізу.</p>'
    head = "".join(f'<th scope="col">{_escape(value)}</th>' for value in headers)
    body = "".join("<tr>" + "".join(f"<td>{_escape(value)}</td>" for value in row)
                   + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _csv_table(path: Path, root: Path, columns, limit: int = 50) -> str:
    if not path.is_file():
        return '<p class="muted">Таблицю не створено.</p>'
    # Keep the HTML bounded even for large source collections.
    rows = []
    count = 0
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            count += 1
            if len(rows) < limit:
                rows.append([row.get(key, "") for key, _ in columns])
    note = f"Показано {len(rows)} із {count} рядків. " if count > limit else ""
    return (_table([label for _, label in columns], rows)
            + f'<p class="muted">{note}{_link(path, root, "Повна таблиця CSV")}</p>')


def _files(paths, root: Path) -> str:
    links = "".join(f"<li>{_link(path, root)}</li>" for path in sorted(paths) if path.is_file())
    return f"<ul>{links}</ul>" if links else '<p class="muted">Файлів немає.</p>'


def write_html_report(
    root: Path, workbook_name: str, scopes: dict[str, list[Record]],
    issues: list[Issue], script_version: str, dictionary_version: str,
    macroblock_labels: dict[str, str],
) -> Path:
    """Write one report per workbook; combined is not added to fond totals."""
    sections, navigation = [], []
    ordered = sorted(scopes, key=lambda key: (key != "combined", key))
    for number, scope in enumerate(ordered):
        records = scopes[scope]
        active = [record for record in records if record.status == "case"]
        sheets = {record.sheet_name for record in records}
        scoped_issues = issues if scope == "combined" else [
            issue for issue in issues if not issue.sheet_name or issue.sheet_name in sheets]
        counts = Counter(issue.level for issue in scoped_issues)
        refs = sorted({f"{r.source_archive}, ф. {r.source_fond}" for r in records})
        title = "Спільний зріз книги" if scope == "combined" else "; ".join(refs) or scope
        anchor = f"scope-{number}"
        navigation.append(f'<a href="#{anchor}">{_escape(title)}</a>')
        tables, figures, reports = (root / folder / scope for folder in ("tables", "figures", "reports"))
        years = [year for record in active for year in (record.start_year, record.end_year)
                 if year is not None]
        year_range = f"{min(years)}–{max(years)}" if years else "Не визначено"
        subject = sum(bool(record.categories) for record in active)
        context = sum(not record.categories and bool(record.context_categories) for record in active)

        def percent(value):
            return f"{value / len(active) * 100:.2f}" if active else "—"

        cards = "".join(f'<article class="card"><strong>{_escape(value)}</strong><span>{label}</span></article>'
                        for value, label in ((len(active), "справ в аналізі"),
                                             (len(sheets), "описів"), (year_range, "крайні роки справ")))
        quality = _table(["Показник", "Кількість"], [
            ("Помилки", counts["ERROR"]), ("Попередження", counts["WARNING"]),
            ("Порожні крайні дати", sum(not r.dates_raw for r in active)),
            ("Не визначено жодного року справи", sum(r.start_year is None and r.end_year is None for r in active)),
            ("Не визначено кількість аркушів", sum(r.pages is None for r in active)),
            ("Справи з позначками експертної перевірки", sum(bool(r.review_flags) for r in active)),
            ("Вибулі записи", sum(r.status == "withdrawn" for r in records)),
        ])
        coverage = _table(["Стан класифікації", "Справ", "% усіх справ зрізу"], [
            (label, value, percent(value)) for label, value in (
                ("Тематично класифіковано", subject), ("Лише контекст", context),
                ("Не класифіковано", len(active) - subject - context))])
        descriptions = _csv_table(tables / "description_summary.csv", root, [
            ("description", "Архівний опис"), ("cases_in_analysis", "Справ"),
            ("withdrawn_records", "Вибулих"), ("subject_classified", "Тематично класифіковано"),
            ("context_only", "Лише контекст"), ("unclassified", "Не класифіковано")])
        categories = _csv_table(tables / "category_counts.csv", root, [
            ("category_label", "Категорія"), ("cases", "Справ"),
            ("percent_of_analyzed_titles", "% усіх справ зрізу")])
        blocks = Counter(block for record in active for block in set(record.macroblocks))
        block_table = _table(["Тематичний блок", "Справ", "% усіх справ зрізу"],
                             [(label, blocks[key], percent(blocks[key]))
                              for key, label in macroblock_labels.items()])
        chronology = _csv_table(tables / "cases_by_decade.csv", root, [("decade", "Десятиліття"), ("cases", "Справ")])
        types = _csv_table(tables / "document_type_counts.csv", root, [
            ("document_type_label", "Тип документа"), ("titles", "Заголовків зі згадкою"),
            ("percent_of_analyzed_titles", "% усіх справ зрізу")])
        charts = []
        for stem, label in CHARTS.items():
            image = next((figures / (stem + suffix) for suffix in (".png", ".svg")
                          if (figures / (stem + suffix)).is_file()), None)
            if image:
                charts.append(f'<figure><img loading="lazy" src="{_url(image, root)}" alt="{_escape(label)}">'
                              f'<figcaption>{_escape(label)}</figcaption></figure>')
        chart_html = "".join(charts) or '<p class="muted">Статичні графіки не створено. Таблиці та інтерактивні звіти доступні нижче.</p>'
        interactive = "".join(f"<li>{_link(figures / name, root, label)}</li>"
                              for name, label in INTERACTIVE.items() if (figures / name).is_file())
        interactive = f'<ul class="interactive">{interactive}</ul>' if interactive else "<p>Інтерактивні звіти відсутні.</p>"
        report_files = _files(reports.glob("*"), root)
        table_files = _files(tables.glob("*.csv"), root)
        sections.append(f'''<section id="{anchor}"><h2>{_escape(title)}</h2>
<p class="muted">{_escape('; '.join(refs))}</p><div class="cards">{cards}</div>
<h3>Склад за описами</h3>{descriptions}
<h3>Якість даних</h3>{quality}{report_files}
<h3>Покриття тематичною класифікацією</h3>{coverage}
<p>За 100% узято всі справи поточного зрізу. Три стани класифікації взаємовиключні.</p>
<h3>Тематичні категорії</h3>{categories}<h3>Тематичні блоки</h3>{block_table}
<p>Одна справа може належати до кількох категорій і блоків; сума їхніх часток може перевищувати 100%.</p>
<h3>Хронологія</h3>{chronology}
<p>Десятиліття визначено за початковим роком справи або роком розділу за чинними правилами аналізу.
Річні ряди враховують діапазон дат; деталі збережено в таблицях хронології.</p>
<h3>Типи документів</h3>{types}
<p>Показано згадки в заголовках, а не перевірений склад документів усередині справ.</p>
<h3>Графіки</h3>{chart_html}<h3>Інтерактивні звіти</h3>{interactive}
<details><summary>Усі таблиці цього зрізу</summary>{table_files}</details>
<p><a href="#top">До початку</a></p></section>''')
    exports = _files((root / "thematic_exports").rglob("*"), root)
    general = _files([root / "run_manifest.json", *(root / "tables").glob("*.csv")], root)
    page = f'''<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Аналіз архівних описів — {_escape(workbook_name)}</title>
<style>
:root{{color-scheme:light;--ink:#203549;--line:#d7e1ea;--blue:#245c87}}
*{{box-sizing:border-box}}body{{margin:0;background:#f5f7fa;color:var(--ink);font:16px/1.55 system-ui,sans-serif}}
main{{max-width:1200px;margin:auto;padding:28px}}h1{{font-size:30px}}h2{{margin-top:48px;border-bottom:3px solid var(--blue);padding-bottom:10px}}h3{{margin-top:28px}}
a{{color:var(--blue);overflow-wrap:anywhere}}nav{{display:flex;flex-wrap:wrap;gap:10px 22px}}.muted,figcaption{{color:#546778;font-size:14px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:20px 0}}.card{{background:white;border:1px solid var(--line);border-radius:10px;padding:18px}}.card strong,.card span{{display:block}}.card strong{{font-size:26px}}
.table-wrap{{overflow:auto;background:white;border:1px solid var(--line)}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}}th{{background:#e8f0f7}}tr:nth-child(even){{background:#f8fafc}}
figure{{margin:20px 0;padding:12px;background:white;border:1px solid var(--line)}}img{{max-width:100%;height:auto;display:block;margin:auto}}figcaption{{text-align:center}}
.note{{padding:14px 18px;background:#fff5db;border-left:4px solid #c38a25}}summary{{cursor:pointer;font-weight:600}}li{{margin:6px 0}}footer{{margin:32px 0;font-size:14px}}
@media(max-width:600px){{main{{padding:14px}}h1{{font-size:24px}}}}
@media print{{body{{background:white}}nav,details{{display:none}}main{{max-width:none;padding:0}}figure,.card{{break-inside:avoid}}}}
</style></head><body><main id="top"><h1>Аналіз архівних описів</h1>
<p>Вхідна книга: <strong>{_escape(workbook_name)}</strong></p>
<p class="muted">Програма {_escape(script_version)} · словники {_escape(dictionary_version)}</p>
<p class="note">Спільний зріз охоплює всі описи однієї книги. Підсумки окремих фондів є його складовими:
їх не потрібно додавати до спільного підсумку. Аналіз стосується заголовків справ.</p>
<nav aria-label="Розділи звіту">{' '.join(navigation)} <a href="#downloads">Файли результатів</a></nav>
{''.join(sections)}<section id="downloads"><h2>Файли результатів</h2>{general}
<h3>Тематичні вибірки</h3>{exports}</section>
<footer>Для передавання звіту збережіть усю папку результатів книги разом із підпапками.
Головний звіт, мережа тем і термінологія працюють локально. Географічні карти потребують інтернету для завантаження Leaflet.
Сучасні кордони на картах не відтворюють адміністративний поділ досліджуваного періоду.</footer>
</main></body></html>'''
    path = root / "report.html"
    path.write_text(page, encoding="utf-8")
    return path
