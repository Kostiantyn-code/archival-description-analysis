"""Workbook report assembled from existing results, without reclassification."""
from __future__ import annotations

import csv
import html
from collections import Counter
from functools import partial
from pathlib import Path
from urllib.parse import quote

from models import Issue, Record
from visualization import Visualization
from report_localization import Report


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


def _link(path: Path, root: Path, label: str | None = None, report: Report = Report()) -> str:
    return f'<a href="{_url(path, root)}">{_escape(label or report.filename(path))}</a>'


def _table(headers, rows, tr=Report().text) -> str:
    rows = list(rows)
    if not rows:
        return tr('<p class="muted">Немає даних для цього зрізу.</p>')
    head = "".join(f'<th scope="col">{_escape(value)}</th>' for value in headers)
    body = "".join("<tr>" + "".join(f"<td>{_escape(value)}</td>" for value in row)
                   + "</tr>" for row in rows)
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _csv_table(path: Path, root: Path, columns, limit: int = 50, report: Report = Report()) -> str:
    tr = report.text
    if not path.is_file():
        return tr('<p class="muted">Таблицю не створено.</p>')
    # Keep the HTML bounded even for large source collections.
    rows = []
    count = 0
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            count += 1
            if len(rows) < limit:
                rows.append([report.csv_value(row, key) for key, _ in columns])
    note = tr('Показано {0} із {1} рядків. ', len(rows), count) if count > limit else ""
    return (_table([label for _, label in columns], rows, tr=tr)
            + f'<p class="muted">{note}{_link(path, root, tr("Повна таблиця CSV"))}</p>')


def _files(paths, root: Path, report: Report = Report()) -> str:
    tr = report.text
    links = "".join(f"<li>{_link(path, root, report=report)}</li>" for path in sorted(paths) if path.is_file())
    return f"<ul>{links}</ul>" if links else tr('<p class="muted">Файлів немає.</p>')


def write_html_report(
    root: Path, workbook_name: str, scopes: dict[str, list[Record]],
    issues: list[Issue], script_version: str, dictionary_version: str,
    macroblock_labels: dict[str, str],
    visual: Visualization | None = None,
) -> Path:
    """Write one report per workbook; combined is not added to fond totals."""
    visual = visual or Visualization()
    report = Report(visual)
    tr = report.text
    table = partial(_table, tr=tr)
    csv_table = partial(_csv_table, report=report)
    files = partial(_files, report=report)
    sections, navigation = [], []
    ordered = sorted(scopes, key=lambda key: (key != "combined", key))
    for number, scope in enumerate(ordered):
        records = scopes[scope]
        active = [record for record in records if record.status == "case"]
        sheets = {record.sheet_name for record in records}
        scoped_issues = issues if scope == "combined" else [
            issue for issue in issues if not issue.sheet_name or issue.sheet_name in sheets]
        counts = Counter(issue.level for issue in scoped_issues)
        refs = sorted({tr('{0}, ф. {1}', visual.label('archives', r.source_archive, r.source_archive), r.source_fond) for r in records})
        title = tr('Спільний зріз книги') if scope == "combined" else "; ".join(refs) or scope
        anchor = f"scope-{number}"
        navigation.append(f'<a href="#{anchor}">{_escape(title)}</a>')
        tables, figures, reports = (root / folder / scope for folder in ("tables", "figures", "reports"))
        years = [year for record in active for year in (record.start_year, record.end_year)
                 if year is not None]
        year_range = f"{min(years)}–{max(years)}" if years else tr('Не визначено')
        subject = sum(bool(record.categories) for record in active)
        context = sum(not record.categories and bool(record.context_categories) for record in active)

        def percent(value):
            return f"{value / len(active) * 100:.2f}" if active else "—"

        cards = "".join(f'<article class="card"><strong>{_escape(value)}</strong><span>{label}</span></article>'
                        for value, label in ((len(active), tr('справ в аналізі')),
                                             (len(sheets), tr('описів')), (year_range, tr('крайні роки справ'))))
        unsupported = sorted({r.language for r in records if r.language not in {"uk", "ru"}})
        if unsupported:
            cards += '<p class="note">' + _escape(tr(
                'Для мов {0} тематичні словники відсутні. Класифікацію пропущено; нульове покриття не характеризує зміст документів.',
                ', '.join(unsupported))) + '</p>'
        quality = table([tr('Показник'), tr('Кількість')], [
            (tr('Помилки'), counts["ERROR"]), (tr('Попередження'), counts["WARNING"]),
            (tr('Порожні крайні дати'), sum(not r.dates_raw for r in active)),
            (tr('Не визначено жодного року справи'), sum(r.start_year is None and r.end_year is None for r in active)),
            (tr('Не визначено кількість аркушів'), sum(r.pages is None for r in active)),
            (tr('Справи з позначками експертної перевірки'), sum(bool(r.review_flags) for r in active)),
            (tr('Вибулі записи'), sum(r.status == "withdrawn" for r in records)),
        ])
        coverage = table([tr('Стан класифікації'), tr('Справ'), tr('% усіх справ зрізу')], [
            (label, value, percent(value)) for label, value in (
                (tr('Тематично класифіковано'), subject), (tr('Лише контекст'), context),
                (tr('Не класифіковано'), len(active) - subject - context))])
        descriptions = csv_table(tables / "description_summary.csv", root, [
            ("description", tr('Архівний опис')), ("cases_in_analysis", tr('Справ')),
            ("withdrawn_records", tr('Вибулих')), ("subject_classified", tr('Тематично класифіковано')),
            ("context_only", tr('Лише контекст')), ("unclassified", tr('Не класифіковано'))])
        categories = csv_table(tables / "category_counts.csv", root, [
            ("category_label", tr('Категорія')), ("cases", tr('Справ')),
            ("percent_of_analyzed_titles", tr('% усіх справ зрізу'))])
        blocks = Counter(block for record in active for block in set(record.macroblocks))
        block_table = table([tr('Тематичний блок'), tr('Справ'), tr('% усіх справ зрізу')],
                             [(visual.label("macroblocks", key, label), blocks[key], percent(blocks[key]))
                              for key, label in macroblock_labels.items()])
        chronology = csv_table(tables / "cases_by_decade.csv", root, [("decade", tr('Десятиліття')), ("cases", tr('Справ'))])
        types = csv_table(tables / "document_type_counts.csv", root, [
            ("document_type_label", tr('Тип документа')), ("titles", tr('Заголовків зі згадкою')),
            ("percent_of_analyzed_titles", tr('% усіх справ зрізу'))])
        charts = []
        for stem, label in CHARTS.items():
            label = visual.text(label)
            image = next((figures / (stem + suffix) for suffix in (".png", ".svg")
                          if (figures / (stem + suffix)).is_file()), None)
            if image:
                charts.append(f'<figure><img loading="lazy" src="{_url(image, root)}" alt="{_escape(label)}">'
                              f'<figcaption>{_escape(label)}</figcaption></figure>')
        chart_html = "".join(charts) or tr('<p class="muted">Статичні графіки не створено. Таблиці та інтерактивні звіти доступні нижче.</p>')
        interactive = "".join(f"<li>{_link(figures / name, root, visual.text(label))}</li>"
                              for name, label in INTERACTIVE.items() if (figures / name).is_file())
        interactive = f'<ul class="interactive">{interactive}</ul>' if interactive else tr('<p>Інтерактивні звіти відсутні.</p>')
        report_files = files(reports.glob("*"), root)
        table_files = files(tables.glob("*.csv"), root)
        sections.append(tr('''<section id="{0}"><h2>{1}</h2>
<p class="muted">{2}</p><div class="cards">{3}</div>
<h3>Склад за описами</h3>{4}
<h3>Якість даних</h3>{5}{6}
<h3>Покриття тематичною класифікацією</h3>{7}
<p>За 100% узято всі справи поточного зрізу. Три стани класифікації взаємовиключні.</p>
<h3>Тематичні категорії</h3>{8}<h3>Тематичні блоки</h3>{9}
<p>Одна справа може належати до кількох категорій і блоків; сума їхніх часток може перевищувати 100%.</p>
<h3>Хронологія</h3>{10}
<p>Десятиліття визначено за початковим роком справи або роком розділу за чинними правилами аналізу.
Річні ряди враховують діапазон дат; деталі збережено в таблицях хронології.</p>
<h3>Типи документів</h3>{11}
<p>Показано згадки в заголовках, а не перевірений склад документів усередині справ.</p>
<h3>Графіки</h3>{12}<h3>Інтерактивні звіти</h3>{13}
<details><summary>Усі таблиці цього зрізу</summary>{14}</details>
<p><a href="#top">До початку</a></p></section>''', anchor, _escape(title), _escape('; '.join(refs)), cards, descriptions, quality, report_files, coverage, categories, block_table, chronology, types, chart_html, interactive, table_files))
    exports = files((root / "thematic_exports").rglob("*"), root)
    general = files([root / "run_manifest.json", *(root / "tables").glob("*.csv")], root)
    page = tr('''<!doctype html>
<html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Аналіз архівних описів — {0}</title>
<style>
:root{color-scheme:light;--ink:#203549;--line:#d7e1ea;--blue:#245c87}
*{box-sizing:border-box}body{margin:0;background:#f5f7fa;color:var(--ink);font:16px/1.55 system-ui,sans-serif}
main{max-width:1200px;margin:auto;padding:28px}h1{font-size:30px}h2{margin-top:48px;border-bottom:3px solid var(--blue);padding-bottom:10px}h3{margin-top:28px}
a{color:var(--blue);overflow-wrap:anywhere}nav{display:flex;flex-wrap:wrap;gap:10px 22px}.muted,figcaption{color:#546778;font-size:14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:20px 0}.card{background:white;border:1px solid var(--line);border-radius:10px;padding:18px}.card strong,.card span{display:block}.card strong{font-size:26px}
.table-wrap{overflow:auto;background:white;border:1px solid var(--line)}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}th{background:#e8f0f7}tr:nth-child(even){background:#f8fafc}
figure{margin:20px 0;padding:12px;background:white;border:1px solid var(--line)}img{max-width:100%;height:auto;display:block;margin:auto}figcaption{text-align:center}
.note{padding:14px 18px;background:#fff5db;border-left:4px solid #c38a25}summary{cursor:pointer;font-weight:600}li{margin:6px 0}footer{margin:32px 0;font-size:14px}
@media(max-width:600px){main{padding:14px}h1{font-size:24px}}
@media print{body{background:white}nav,details{display:none}main{max-width:none;padding:0}figure,.card{break-inside:avoid}}
</style></head><body><main id="top"><h1>Аналіз архівних описів</h1>
<p>Вхідна книга: <strong>{1}</strong></p>
<p class="muted">Програма {2} · словники {3}</p>
<p class="note">Спільний зріз охоплює всі описи однієї книги. Підсумки окремих фондів є його складовими:
їх не потрібно додавати до спільного підсумку. Аналіз стосується заголовків справ.</p>
<nav aria-label="Розділи звіту">{4} <a href="#downloads">Файли результатів</a></nav>
{5}<section id="downloads"><h2>Файли результатів</h2>{6}
<h3>Тематичні вибірки</h3>{7}</section>
<footer>Для передавання звіту збережіть усю папку результатів книги разом із підпапками.
Головний звіт, мережа тем і термінологія працюють локально. Географічні карти потребують інтернету для завантаження Leaflet.
Сучасні кордони на картах не відтворюють адміністративний поділ досліджуваного періоду.</footer>
</main></body></html>''', _escape(workbook_name), _escape(workbook_name), _escape(script_version), _escape(dictionary_version), ' '.join(navigation), ''.join(sections), general, exports)
    path = root / "report.html"
    path.write_text(page, encoding="utf-8")
    return path
