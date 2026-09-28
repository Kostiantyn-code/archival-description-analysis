"""Exploratory labels for document forms mentioned in archival case titles.

These are lexical mentions, not a verified inventory of documents within a file.
Several labels can apply to one title. Generic headings such as ``Справа про``
and ``Дело о`` intentionally have no label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


DOCUMENT_TYPE_RULES_VERSION = "0.1-draft"


@dataclass(frozen=True)
class DocumentType:
    id: str
    label: str
    pattern: re.Pattern[str]


_RULES = (
    ("correspondence", "Листування та листи",
     r"\b(?:листуван[а-яіїєґ]*|лист(?:и|а|ів|ами|ах|ом|у|і)?|переписк[а-яё]*|письм(?:о|а|у|ом|е|ами|ах)|писем)\b"),
    ("reports", "Рапорти та донесення",
     r"\b(?:рапорт[а-яіїєґё]*|донесенн[а-яіїєґ]*|донесени[а-яё]*)\b"),
    ("instructions", "Приписи та розпорядження",
     r"\b(?:припис(?:и|ів|а|у|ом|ами|ах)?|розпоряджен[а-яіїєґ]*|предписани[а-яё]*|распоряжени[а-яё]*)\b"),
    ("circulars", "Обіжники та циркуляри",
     r"\b(?:обіжник[а-яіїєґ]*|циркуляр[а-яіїєґё]*)\b"),
    ("petitions", "Клопотання та прохання",
     r"\b(?:клопотанн[а-яіїєґ]*|проханн[а-яіїєґ]*|прошенн[а-яіїєґ]*|ходатайств[а-яё]*|прошени[а-яё]*)\b"),
    ("statements", "Відомості та звіти",
     r"\b(?:відомост[а-яіїєґ]*|звіт[а-яіїєґ]*|ведомост[а-яё]*|отч[её]т[а-яё]*)\b"),
    ("decrees", "Укази та накази",
     r"\b(?:указ[а-яіїєґё]*|наказ[а-яіїєґ]*|приказ[а-яё]*)\b"),
    ("memoranda", "Доповіді та записки",
     r"\b(?:доповід[а-яіїєґ]*|записк[а-яіїєґё]*|доклад[а-яё]*)\b"),
    ("lists", "Списки та реєстри",
     r"\b(?:списк[а-яіїєґё]*|список|реєстр[а-яіїєґ]*|реестр[а-яё]*)\b"),
    ("minutes", "Протоколи та журнали",
     r"\b(?:протокол[а-яіїєґё]*|журнал[а-яіїєґё]*)\b"),
    ("certificates", "Паспорти та свідоцтва",
     r"\b(?:паспорт[а-яіїєґё]*|свідоцтв[а-яіїєґ]*|свидетельств[а-яё]*)\b"),
    ("plans", "Плани, проєкти та кошториси",
     r"\b(?:план(?:и|ів|у|ом|ах|ами|ов|а|е)?|проєкт[а-яіїєґ]*|проект[а-яё]*|кошторис[а-яіїєґ]*|смет[а-яё]*)\b"),
    ("complaints", "Скарги та заяви",
     r"\b(?:скарг[а-яіїєґ]*|заяв(?:а|и|ою|і|ами|ах)|жалоб[а-яё]*|заявлени[а-яё]*)\b"),
    ("acts", "Акти та постанови",
     r"\b(?:акт(?:и|ів|а|ом|у|ами|ах|ов|ы)?|постанов[а-яіїєґ]*|постановлени[а-яё]*)\b"),
    ("notifications", "Повідомлення та телеграми",
     r"\b(?:повідомленн[а-яіїєґ]*|телеграм[а-яіїєґё]*|уведомлени[а-яё]*|сообщени[а-яё]*)\b"),
)

DOCUMENT_TYPES = tuple(
    DocumentType(id, label, re.compile(pattern, re.IGNORECASE))
    for id, label, pattern in _RULES
)


def match_document_types(title: str) -> list[tuple[DocumentType, str]]:
    """Return each mentioned type once, with an example matched expression."""
    matches = []
    for document_type in DOCUMENT_TYPES:
        match = document_type.pattern.search(title)
        if match:
            matches.append((document_type, match.group(0)))
    return matches
