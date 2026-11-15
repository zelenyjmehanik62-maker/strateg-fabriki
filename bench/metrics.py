#!/usr/bin/env python3
"""Считает по тексту результата: сколько строк с цифрами и у скольких из них указан источник.

Запуск из корня репозитория:  python3 bench/metrics.py
Строка «с цифрой» — непустая строка не-заголовок, где есть число (номер пункта списка не считается).
«Источник указан» — в строке есть ссылка на реестр [E-…] или название материала с местом.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ["findings.md", "options.md", "strategy-product.md", "strategy-comms.md", "verification.md"]
REF_AGENT = re.compile(r"\[E-\d+")
REF_CHAT = re.compile(r"(записк[аи],? абз|таблиц[аеы],? лист|поддержк[аи],? №|\(экран\)|Литрес,? п\.|Плюс,? п\.|Рынок-\S+,? п\.|№\d+)", re.I)
SEP = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def lines(text):
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or SEP.match(s):
            continue
        body = re.sub(r"^(\d+[.)]|[-*])\s+", "", s)
        body = re.sub(r"\[E-\d+(?:\s*,\s*E-\d+)*\]|№\s?\d+|абз\.\s?\d+|лист\s?\d+|п\.\s?[\d–, ]+", "", body)
        if re.search(r"\d", body):
            yield s


def measure(name, texts, ref):
    rows = [l for t in texts for l in lines(t)]
    with_ref = sum(1 for l in rows if ref.search(l))
    words = sum(len(t.split()) for t in texts)
    share = round(100 * with_ref / len(rows)) if rows else 0
    print(f"{name}: слов {words}, строк с цифрами {len(rows)}, из них с источником {with_ref} ({share}%)")


project = ROOT / "strateg" / "projects" / "polka"
measure("Агент «Стратег»", [(project / n).read_text(encoding="utf-8") for n in AGENT], REF_AGENT)
measure("Чат, простой запрос", [(ROOT / "bench/baseline/polka-chat-prostoy.md").read_text(encoding="utf-8")], REF_CHAT)
measure("Чат с хорошим промптом", [(ROOT / "bench/baseline/polka-chat-s-promptom.md").read_text(encoding="utf-8")], REF_CHAT)
