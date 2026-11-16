"""Поиск персональных данных в файлах проекта — до того, как они попадут в репозиторий.

Ищет то, что надёжно узнаётся по виду: телефоны, электронные почты, номера банковских карт,
паспортов и СНИЛС. Имена, адреса и узнаваемые подробности скрипт надёжно не находит —
их убирает агент по процедуре навыка `interview`. Поэтому «ничего не найдено» не значит,
что персональных данных нет.

Не проверяется папка materials/private/ — туда кладут исходные записи с личными данными,
и она исключена из git. Исключения для заведомо публичных значений (телефон горячей линии
компании) — по строке в pii-allow.txt в папке проекта.
"""
import re
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt", ".csv", ".tsv", ".json", ".jsonl", ".html", ".htm"}

PATTERNS = [
    ("электронная почта", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("телефон", re.compile(r"(?<![\d\w])(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)")),
    ("СНИЛС", re.compile(r"(?<!\d)\d{3}-\d{3}-\d{3}[\s-]\d{2}(?!\d)")),
    ("паспорт", re.compile(r"(?i)паспорт\D{0,20}\d{2}\s?\d{2}\s?№?\s?\d{6}")),
    ("номер карты", re.compile(r"(?<!\d)(?:\d{4}[\s-]?){3}\d{4}(?!\d)")),
]


def _luhn(number):
    digits = [int(d) for d in re.sub(r"\D", "", number)]
    if len(set(digits)) == 1:
        return False  # заглушки вида 0000 0000 0000 0000 — не номер карты
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return len(digits) >= 13 and total % 10 == 0


def mask(value):
    keep = re.sub(r"\s", "", value)
    return keep[:2] + "…" + keep[-2:] if len(keep) > 6 else "…"


def scan(pdir):
    pdir = Path(pdir)
    allow_file = pdir / "pii-allow.txt"
    allow = {l.strip() for l in allow_file.read_text(encoding="utf-8").splitlines() if l.strip()} if allow_file.exists() else set()
    hits = []
    for path in sorted(pdir.rglob("*")):
        rel = path.relative_to(pdir)
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES or rel.parts[:2] == ("materials", "private"):
            continue
        if path.name == "pii-allow.txt":
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for kind, rx in PATTERNS:
                for m in rx.finditer(line):
                    value = m.group(0).strip()
                    if value in allow:
                        continue
                    if kind == "номер карты" and not _luhn(value):
                        continue
                    hits.append((str(rel), n, kind, mask(value)))
    return hits
