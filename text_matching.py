"""Нормалізація та зіставлення UK/RU без читання або зміни файлів."""
from __future__ import annotations

import re
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

MATCH_LANGUAGE = ContextVar("match_language", default="uk")


WORD_RE = re.compile(
    r"[0-9A-Za-zА-Яа-яІіЇїЄєҐґЁё]+(?:[-'][0-9A-Za-zА-Яа-яІіЇїЄєҐґЁё]+)*"
)
YEAR_HEADING_RE = re.compile(
    r"^\s*"
    r"((?:17|18|19|20)\d{2}"
    r"(?:\s*(?:,|;|/|-|і|та)\s*(?:17|18|19|20)\d{2})*)"
    r"\s*(?:рік|роки|років|рр?|год|годы|годов|гг?)?\.?\s*$",
    re.I,
)
YEAR_RE = re.compile(r"(?<!\d)((?:17|18|19|20)\d{2})(?!\d)")
LONG_NUMBER_RE = re.compile(r"(?<!\d)\d{5,}(?!\d)")
WITHDRAWN_RE = re.compile(
    r"^(?:в\s*и\s*б\s*у\s*л\s*[аио]|в\s*ы\s*б\s*ы\s*л\s*[аои])(?=$|[\s.,;:—-])",
    re.I,
)

STEM_ENDINGS = sorted(
    {
        "остями", "істями", "остях", "істях", "остям", "істям",
        "остей", "істей", "ості", "істю", "ість",
        "ими", "іми", "ами", "ями",
        "ього", "ьому", "ого", "ому",
        "ій", "ої", "ьої", "ою", "ею", "єю",
        "ів", "їв", "ев", "ов", "ам", "ям", "ах", "ях",
        "ий", "им", "их", "іх", "ом", "ем",
        "а", "я", "у", "ю", "и", "і", "ї", "е", "о",
    },
    key=len,
    reverse=True,
)


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_text(text: str) -> str:
    return (
        text.lower()
        .replace("’", "'")
        .replace(chr(96), "'")
        .replace("ʼ", "'")
        .replace("–", "-")
        .replace("—", "-")
        .replace("\u00a0", " ")
    )


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    # У джерелі складні слова інколи набрано з пробілами біля дефіса:
    # «військово- морський». Для зіставлення це те саме складне слово.
    normalized = re.sub(
        r"(?<=[A-Za-zА-Яа-яІіЇїЄєҐґЁё])\s*-\s*"
        r"(?=[A-Za-zА-Яа-яІіЇїЄєҐґЁё])",
        "-",
        normalized,
    )
    return WORD_RE.findall(normalized)


UK_IRREGULAR = {
    'купець': 'купц',
    'купец': 'купц',
    'купц': 'купц',
    'купцеві': 'купц',
    'купцев': 'купц',
    'учень': 'учн',
    'учен': 'учн',
    'учн': 'учн',
    'будинок': 'будинк',
    'осіб': 'особ',
    'особи': 'особ',
    'ділянок': 'ділянк',
    'набор': 'набір',
    'рок': 'рік',
    'шпитал': 'шпиталь',
    'суден': 'судн',
    'недоїмок': 'недоїмк',
    'угідь': 'угідд',
    'угід': 'угідд',
    'платеж': 'платіж',
    'крадіжок': 'крадіжк',
    'грабеж': 'грабіж',
    'міщанин': 'міщан',
    'міщан': 'міщан',
    'дворянин': 'дворян',
    'дворян': 'дворян',
    'селянин': 'селян',
    'селян': 'селян',
    'громадянин': 'громадян',
    'громадян': 'громадян',
    'протоієрей': 'протоієр',
    'протоієре': 'протоієр',
    'священник': 'священик',
    'священик': 'священик',
    'правлінн': 'правлін',
    'правлін': 'правлін',
    'присутствіє': 'присутств',
    'присутстві': 'присутств',
    'присутствієм': 'присутств',
    'виданн': 'видан',
    'видан': 'видан',
    'вчинен': 'вчиненн',
    'нанесен': 'нанесенн',
    'церк': 'церкв',
    'режим': 'реж',
    'позов': 'поз',
    'друкарен': 'друкарн',
    'видавец': 'видавц',
    'шкіл': 'школ',
    'збор': 'збір',
    'звод': 'звід',
    'купален': 'купальн',
    'молебн': 'молебен',
    'гулян': 'гулянн',
    'ярмарок': 'ярмарк',
    'водосток': 'водостік',
    'укріплен': 'укріпленн',
}

RU_IRREGULAR = {
    'купец': 'купц',
    'мещанин': 'мещан',
    'крестьянин': 'крестьян',
    'дворянин': 'дворян',
    'дет': 'ребенок',
    'дети': 'ребенок',
    'люд': 'лиц',
    'суден': 'судн',
    'снимок': 'снимк',
    'церкв': 'церк',
    'издержек': 'издержк',
}


def light_stem_word(word: str) -> str:
    if MATCH_LANGUAGE.get() == "ru":
        return russian_stem_word(word)
    return ukrainian_stem_word(word)


@lru_cache(maxsize=100_000)
def ukrainian_stem_word(word: str) -> str:
    word = normalize_text(word)
    if "-" in word:
        return "-".join(light_stem_word(part) for part in word.split("-") if part)
    if "'" in word:
        return "'".join(light_stem_word(part) for part in word.split("'") if part)
    if word.isdigit() or len(word) <= 3:
        return word
    for ending in STEM_ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            word = word[:-len(ending)]
            break
    if word.endswith("ь") and len(word) > 3:
        word = word[:-1]
    return UK_IRREGULAR.get(word, word)


def stem_tokens(text: str) -> list[str]:
    return [light_stem_word(word) for word in tokenize(text)]


@lru_cache(maxsize=30000)
def cached_item_tokens(item: str, language: str) -> tuple[str, ...]:
    token = MATCH_LANGUAGE.set(language)
    try:
        return tuple(stem_tokens(item))
    finally:
        MATCH_LANGUAGE.reset(token)


def item_tokens(item: str) -> list[str]:
    return list(cached_item_tokens(item, MATCH_LANGUAGE.get()))


def find_phrase_positions(tokens: list[str], phrase: list[str]) -> list[int]:
    if not phrase or len(phrase) > len(tokens):
        return []
    positions: list[int] = []
    width = len(phrase)
    for index in range(len(tokens) - width + 1):
        if tokens[index:index + width] == phrase:
            positions.append(index)
    return positions


def contains_item(tokens: list[str], item: str) -> bool:
    wanted = item_tokens(item)
    if not wanted:
        return False
    if len(wanted) == 1:
        return any(
            wanted[0] == token or wanted[0] in token.split("-")
            for token in tokens
        )
    return bool(find_phrase_positions(tokens, wanted))


def item_matcher(tokens: list[str]):
    """Індекс одного заголовка після маскування; кеш діє лише для цієї категорії."""
    language = MATCH_LANGUAGE.get()
    words = {part for token in tokens for part in (token, *token.split("-"))}
    phrases: dict[int, set[tuple[str, ...]]] = {}
    matches: dict[str, bool] = {}

    def contains(item: str) -> bool:
        if item not in matches:
            wanted = cached_item_tokens(item, language)
            width = len(wanted)
            if width > 1 and width not in phrases:
                phrases[width] = {
                    tuple(tokens[start:start + width])
                    for start in range(len(tokens) - width + 1)
                }
            matches[item] = (
                wanted[0] in words if width == 1
                else width > 1 and wanted in phrases[width]
            )
        return matches[item]

    return contains


def mask_item(tokens: list[str], item: str) -> list[str]:
    phrase = item_tokens(item)
    if not phrase:
        return tokens
    result = list(tokens)
    if len(phrase) == 1:
        for index, token in enumerate(result):
            if phrase[0] == token or phrase[0] in token.split("-"):
                result[index] = "__masked__"
        return result
    for start in find_phrase_positions(result, phrase):
        for index in range(start, start + len(phrase)):
            result[index] = "__masked__"
    return result


def normalize_case_id(value: str) -> str:
    result = normalize_text(value)
    result = re.sub(r'["“”«»]', "", result)
    result = re.sub(r"\s+", "", result)
    result = re.sub(r"-+", "-", result)
    return result


# Легкий стемінг, НЕ повна лематизація. Мовні кеші ізольовано.
RU_ENDINGS = sorted({
    "иями", "иями", "иям", "ием", "ией", "ие", "ия", "ии", "ями", "ами", "ого", "ему", "ому", "ыми", "ими", "иях",
    "ов", "ев", "ей", "ам", "ям", "ах", "ях", "ом", "ем", "ий", "ый",
    "ой", "ая", "яя", "ое", "ее", "ые", "ие", "ую", "юю", "ых", "их",
    "ым", "им", "ою", "ею", "а", "я", "у", "ю", "ы", "и", "е", "о", "ь"
}, key=lambda s: (-len(s), s))


@lru_cache(maxsize=100000)
def russian_stem_word(word: str) -> str:
    word = normalize_text(word).replace("ё", "е")
    if word in {"режим", "режима", "режиме", "режиму", "режимом", "режимы", "режимов"}:
        return "режим"
    if re.fullmatch(r"погром(?:а|у|е|ом|ы|ов|ам|ами|ах)?", word):
        return "погром"
    if "-" in word:
        return "-".join(russian_stem_word(x) for x in word.split("-"))
    if len(word) <= 3 or word.isdigit():
        return word
    for ending in RU_ENDINGS:
        if word.endswith(ending) and len(word)-len(ending) >= 3:
            word = word[:-len(ending)]
            break
    return RU_IRREGULAR.get(word, word)


def detect_title_language(title: str) -> str:
    """Контрольна евристика; власні назви не змінюють налаштування аркуша."""
    tokens = tokenize(title)
    uk = sum(bool(re.search("[іїєґ]", w)) for w in tokens)
    ru = sum(bool(re.search("[ыэёъ]", w)) for w in tokens)
    uk += sum(w in {"справа", "про", "щодо", "з", "та", "відомості", "наказ"} for w in tokens)
    ru += sum(w in {"дело", "об", "переписка", "с", "при", "сведений", "рапорт"} for w in tokens)
    if uk >= 3 and ru >= 3:
        return "mixed"
    if uk >= 2 and uk > ru * 2:
        return "uk"
    if ru >= 2 and ru > uk * 2:
        return "ru"
    return "undetermined"


