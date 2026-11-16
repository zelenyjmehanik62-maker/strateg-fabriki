"""Сверка фактов с источником: дословная цитата, числа, критичные факты.

Проверки здесь механические: они ловят выдуманную или искажённую цитату и цифру,
которой нет ни в цитате, ни в расчёте. Понять смысл — что цитата действительно
подтверждает утверждение, а не опровергает его, — скрипт не может. Это делает
смысловая сверка (команда `vet`), и скрипт следит только за тем, что она проведена.
"""
import re
from pathlib import Path

# Файлы, в которых стоят выводы, по которым принимают решение.
DECISION_FILES = ["options.md", "strategy-product.md", "strategy-comms.md", "verification.md", "summary.md"]
VERDICTS = {"supports": "подтверждает", "partial": "подтверждает частично", "no": "не подтверждает"}
NO_QUOTE_KINDS = {"user", "synthetic"}  # слова пользователя и синтетика: дословной цитаты из файла нет
TEXT_SUFFIXES = {".md", ".txt", ".csv", ".tsv", ".json", ".jsonl"}

NUM_RE = re.compile(r"\d{1,3}(?:[   ]\d{3})+(?:[.,]\d{1,2})?(?!\d)|\d+(?:\.\d+|,\d{1,2}(?!\d))?")
REF_RE = re.compile(r"\[(E-\d+(?:\s*,\s*E-\d+)*)\]")


def normalize(text):
    """Только буквы и цифры, нижний регистр, ё → е: так цитата находится независимо от
    пробелов, переносов, кавычек и разделителей таблицы."""
    text = (text or "").lower().replace("ё", "е")
    return "".join(ch for ch in text if ch.isalnum())


def numbers(text):
    out = []
    for m in NUM_RE.finditer(text or ""):
        raw = re.sub(r"[   ]", "", m.group(0)).replace(",", ".")
        try:
            out.append(float(raw))
        except ValueError:
            pass
    return out


def number_found(value, pool):
    for b in pool:
        if abs(value - b) < 1e-9 or abs(round(b, 1) - value) < 1e-9 or abs(round(b) - value) < 1e-9:
            return True
    return False


def missing_numbers(claim_text, support_text):
    """Числа от 10 и больше из утверждения, которых нет в подтверждающем тексте.
    Однозначные числа пропускаем: «3 квартал», «2 месяца» слишком часто пересказаны словами."""
    pool = numbers(support_text)
    out = []
    for value in numbers(claim_text):
        if value >= 10 and not number_found(value, pool):
            out.append(value)
    return out


def source_texts(pdir, source):
    """Тексты, в которых можно искать цитату: сама копия, если она текстовая, и её разбор из extract."""
    local = (source or {}).get("local")
    if not local:
        return []
    path = pdir / local
    texts = []
    if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
        texts.append(path.read_text(encoding="utf-8", errors="replace"))
    text_dir = pdir / "materials" / "_text"
    if text_dir.is_dir():
        for p in sorted(text_dir.glob(Path(local).name + ".*")):
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
    return texts


def needs_quote(claim, sources_by_id):
    """Факт из файла должен нести дословную цитату или ссылку на расчёт."""
    if claim.get("type") != "fact":
        return False
    kinds = {sources_by_id.get(r.get("id"), {}).get("kind") for r in claim.get("sources") or []}
    return bool(kinds - NO_QUOTE_KINDS - {None})


def ground(pdir, claim, sources_by_id):
    """Проверяет цитату и числа. Возвращает (ошибки, замечания, quote_checked)."""
    errors, warnings = [], []
    cid = claim.get("id", "?")
    quote, calc = (claim.get("quote") or "").strip(), (claim.get("calc") or "").strip()
    if not needs_quote(claim, sources_by_id):
        return errors, warnings, None
    if not quote and not calc:
        return errors, warnings, None  # отсутствие цитаты оценивает вызывающий: при записи — ошибка, в старых записях — по контексту
    support = ""
    checked = None
    if quote:
        texts = []
        for ref in claim.get("sources") or []:
            texts += source_texts(pdir, sources_by_id.get(ref.get("id")))
        if texts:
            nq = normalize(quote)
            if len(nq) < 12:
                errors.append(f"{cid}: цитата слишком короткая — возьмите фрагмент, по которому смысл понятен без догадок")
            checked = any(nq in normalize(t) for t in texts)
            if not checked:
                errors.append(f"{cid}: цитата не найдена в тексте источника дословно — "
                              "скопируйте фрагмент из материала, не пересказывайте")
        else:
            warnings.append(f"{cid}: цитату не с чем сверить — у источника нет текстовой копии "
                            "(сохраните выписку или выполните extract)")
        support += quote
    if calc:
        path = pdir / calc
        if not path.is_file():
            errors.append(f"{cid}: файл расчёта {calc} не найден")
        else:
            support += "\n" + path.read_text(encoding="utf-8", errors="replace")
    miss = missing_numbers(claim.get("text"), support)
    if miss:
        shown = ", ".join(f"{v:g}" for v in miss)
        errors.append(f"{cid}: числа {shown} есть в утверждении, но их нет ни в цитате, ни в расчёте")
    return errors, warnings, checked


def critical_ids(pdir, claims_by_id, decisions):
    """Утверждения, на которых стоят варианты, стратегии, план проверки, сводка и решения, —
    вместе со всем, на что они опираются через based_on."""
    start = set()
    for name in DECISION_FILES:
        path = pdir / name
        if path.exists():
            for m in REF_RE.finditer(path.read_text(encoding="utf-8")):
                start.update(x.strip() for x in m.group(1).split(","))
    for d in decisions:
        if d.get("status") == "active":
            start.update(d.get("based_on") or [])
    seen, frontier = set(), [i for i in start if i in claims_by_id]
    while frontier:
        cid = frontier.pop()
        if cid in seen:
            continue
        seen.add(cid)
        frontier += [b for b in claims_by_id[cid].get("based_on") or [] if b in claims_by_id]
    return seen
