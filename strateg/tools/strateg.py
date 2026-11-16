#!/usr/bin/env python3
"""Инструменты агента «Стратег»: проекты, реестр доказательств, состояние, журнал.

Запуск из папки strateg/:  python3 tools/strateg.py <команда> ...
Только стандартная библиотека, Python 3.9+. Форматы файлов — docs/CONTRACT.md.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grounding as gr  # noqa: E402

STEPS = ["frame", "collect", "research", "options", "strategy", "follow"]
STEP_NAMES = {
    "frame": "Постановка", "collect": "Материалы", "research": "Исследование",
    "options": "Варианты", "strategy": "Стратегии", "follow": "Сопровождение",
}
SOURCE_KINDS = ["doc", "table", "site", "image", "audio", "video", "interview", "synthetic", "user"]
CLAIM_TYPES = ["fact", "hypothesis", "forecast", "synthetic"]
RESULT_FILES = ["findings.md", "options.md", "strategy-product.md", "strategy-comms.md", "verification.md",
                "summary.md"]
MODES = {"fast": "быстрый", "full": "полный"}
REF_RE = re.compile(r"\[(E-\d+(?:\s*,\s*E-\d+)*)\]")
# Слова, которые показывают читателю, что перед ним не факт.
HEDGES = ("гипотез", "предполож", "прогноз", "оценк", "вероятн", "возможно", "ожида", "может быть", "допущен")
SYNTH_MARKS = ("синтет", "модельн")


class Fail(Exception):
    """Ошибка, которую нужно показать пользователю без трассировки."""


def projects_root():
    env = os.environ.get("STRATEG_PROJECTS")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "projects"


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def project_dir(name, must_exist=True):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name or ""):
        raise Fail(f"Имя проекта «{name}»: только латиница в нижнем регистре, цифры и дефисы.")
    path = projects_root() / name
    if must_exist and not (path / "state.json").exists():
        raise Fail(f"Проект «{name}» не найден. Создать: python3 tools/strateg.py new {name}")
    return path


def read_jsonl(path):
    rows, errors = [], []
    if not path.exists():
        return rows, errors
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            errors.append(f"{path.name}, строка {n}: не читается как JSON ({exc})")
    return rows, errors


def write_atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_jsonl(path, rows):
    write_atomic(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def append_jsonl(path, row):
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def next_id(rows, prefix):
    nums = [int(r["id"].split("-")[1]) for r in rows if str(r.get("id", "")).startswith(prefix + "-")]
    return f"{prefix}-{max(nums, default=0) + 1:03d}"


def load_state(pdir):
    return json.loads((pdir / "state.json").read_text(encoding="utf-8"))


def save_state(pdir, state):
    state["updated"] = now()
    write_atomic(pdir / "state.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def journal(pdir, **row):
    row = {"ts": now(), **row}
    append_jsonl(pdir / "journal.jsonl", row)
    return row


def split_ids(value):
    return [x.strip() for x in (value or "").split(",") if x.strip()]


# ---------- команды ----------

def cmd_new(args):
    pdir = project_dir(args.project, must_exist=False)
    if (pdir / "state.json").exists():
        raise Fail(f"Проект «{args.project}» уже есть. Продолжить: python3 tools/strateg.py status {args.project}")
    (pdir / "materials").mkdir(parents=True, exist_ok=True)
    (pdir / "materials" / ".gitkeep").touch()
    for name in ("sources.jsonl", "evidence.jsonl", "decisions.jsonl", "journal.jsonl"):
        (pdir / name).touch()
    (pdir / "brief.md").write_text(
        "# Постановка задачи\n\n"
        "## Вопрос\n\n## Цель\n\n## Кому нужен результат\n\n## Ограничения\n\n## Доступные данные\n",
        encoding="utf-8")
    save_state(pdir, {
        "project": args.project, "step": "frame", "done": [], "waiting_for_user": None,
        "next_action": "уточнить вопрос, цель, получателя, ограничения и данные", "open_questions": [],
    })
    journal(pdir, step="frame", action="создан проект", tool="strateg.py", minutes=0, cost_rub=None,
            cost_basis="оценка", result="ok", human_help=False)
    print(f"Проект «{args.project}» создан: {pdir}")
    print("Шаг 1 — Постановка. Материалы пользователя кладите в materials/.")


PAUSE_MIN = 20  # перерыв дольше этого считаем паузой в работе, а не работой


def cost_summary(rows):
    total_min = sum(float(r.get("minutes") or 0) for r in rows)
    total_cost = sum(float(r.get("cost_rub") or 0) for r in rows)
    return total_min, total_cost


def clock_minutes(rows):
    """Время по отметкам журнала: сумма промежутков между записями без длинных пауз."""
    stamps = []
    for r in rows:
        try:
            stamps.append(datetime.fromisoformat(r["ts"]))
        except (KeyError, ValueError):
            pass
    stamps.sort()
    total = 0.0
    for a, b in zip(stamps, stamps[1:]):
        gap = (b - a).total_seconds() / 60
        if gap <= PAUSE_MIN:
            total += gap
    return round(total)


def money_line(rows):
    # Ноль «по оценке» — это не замер: так агент раньше отмечал, что не знает расхода.
    measured = [r for r in rows if r.get("cost_rub") is not None
                and not (float(r["cost_rub"]) == 0 and r.get("cost_basis") != "точно")]
    if not measured:
        return "расходы не измерены"
    text = f"{sum(float(r['cost_rub']) for r in measured):g} ₽"
    if len(measured) < len(rows):
        text += f" (измерено у {len(measured)} действий из {len(rows)})"
    return text


def cmd_status(args):
    root = projects_root()
    if not args.project:
        found = sorted(p.parent for p in root.glob("*/state.json")) if root.exists() else []
        if not found:
            print("Проектов пока нет. Создать: python3 tools/strateg.py new <имя>")
            return
        states = [load_state(p) for p in found]
        own = [st for st in states if not st.get("example")]
        examples = [st for st in states if st.get("example")]
        if own:
            print("Проекты:")
            for st in own:
                wait = f" · ждёт пользователя: {st['waiting_for_user']}" if st.get("waiting_for_user") else ""
                print(f"- {st['project']}: шаг «{STEP_NAMES.get(st['step'], st['step'])}»{wait}")
                print(f"  дальше: {st.get('next_action') or '—'} (обновлено {st.get('updated', '—')})")
        else:
            print("Своих проектов пока нет. На вопрос пользователя создайте новый: python3 tools/strateg.py new <имя>")
        if examples:
            print("Готовые примеры (учебные результаты; не продолжать без прямой просьбы пользователя):")
            for st in examples:
                print(f"- {st['project']}: {st['example']}")
        return
    pdir = project_dir(args.project)
    st = load_state(pdir)
    sources, _ = read_jsonl(pdir / "sources.jsonl")
    claims, _ = read_jsonl(pdir / "evidence.jsonl")
    decisions, _ = read_jsonl(pdir / "decisions.jsonl")
    rows, _ = read_jsonl(pdir / "journal.jsonl")
    active = [c for c in claims if c.get("status") == "active"]
    by_type = {t: sum(1 for c in active if c.get("type") == t) for t in CLAIM_TYPES}
    print(f"Проект: {st['project']}")
    print(f"Шаг: {STEP_NAMES.get(st['step'], st['step'])} ({st['step']})")
    print(f"Режим: {MODES.get(st.get('mode'), 'не выбран')}")
    print("Завершено: " + (", ".join(STEP_NAMES.get(s, s) for s in st.get("done", [])) or "—"))
    print(f"Следующее действие: {st.get('next_action') or '—'}")
    if st.get("waiting_for_user"):
        print(f"Ждём пользователя: {st['waiting_for_user']}")
    for q in st.get("open_questions", []):
        print(f"Открытый вопрос: {q}")
    print(f"Источников: {len(sources)} · утверждений: фактов {by_type['fact']}, гипотез {by_type['hypothesis']}, "
          f"прогнозов {by_type['forecast']}, синтетических {by_type['synthetic']} · решений: {len(decisions)}")
    by_id = {c["id"]: c for c in claims}
    crit = gr.critical_ids(pdir, by_id, decisions)
    src_by_id = {x["id"]: x for x in sources}
    unvet = sum(1 for i in crit if by_id[i].get("type") == "fact" and by_id[i].get("status") == "active"
                and not by_id[i].get("vet") and gr.needs_quote(by_id[i], src_by_id))
    if unvet:
        print(f"Критичных фактов без смысловой сверки: {unvet} (vet {st['project']})")
    print(f"Потрачено: {clock_minutes(rows)} мин по отметкам журнала; {money_line(rows)}")
    if rows:
        print("Последние действия:")
        for r in rows[-5:]:
            mark = "" if r.get("result") == "ok" else f" [{r.get('result')}]"
            print(f"- {r.get('ts', '')[:16]} {r.get('step', '')}: {r.get('action', '')}{mark}")
    print(f"Обновлено: {st.get('updated', '—')}")


def cmd_source(args):
    pdir = project_dir(args.project)
    path = pdir / "sources.jsonl"
    rows, _ = read_jsonl(path)
    for r in rows:
        if r.get("ref") == args.ref:
            print(f"{r['id']} (уже в реестре, повторно не добавлен)")
            return
    if args.local and not (pdir / args.local).exists():
        raise Fail(f"Файл {args.local} не найден в папке проекта.")
    row = {"id": next_id(rows, "S"), "kind": args.kind, "title": args.title, "ref": args.ref,
           "local": args.local, "retrieved": now()[:10], "note": args.note or ""}
    append_jsonl(path, row)
    print(row["id"])


def parse_source_arg(value):
    sid, _, where = value.partition(":")
    return {"id": sid.strip(), "where": where.strip()}


def validate_claim(claim, sources_by_id, claims_by_id):
    """Возвращает список нарушений для одной записи реестра."""
    problems = []
    cid = claim.get("id", "?")
    ctype = claim.get("type")
    if ctype not in CLAIM_TYPES:
        problems.append(f"{cid}: неизвестный тип «{ctype}»")
    if not (claim.get("text") or "").strip():
        problems.append(f"{cid}: пустой текст утверждения")
    refs = claim.get("sources") or []
    for ref in refs:
        src = sources_by_id.get(ref.get("id"))
        if not src:
            problems.append(f"{cid}: источник {ref.get('id')} не найден в sources.jsonl")
        elif ctype == "fact" and src.get("kind") == "synthetic":
            problems.append(f"{cid}: факт опирается на синтетический источник {src['id']} — "
                            "ответы модельных респондентов фактов не подтверждают")
    if ctype == "fact":
        if not refs:
            problems.append(f"{cid}: факт без источника — найдите источник или понизьте до гипотезы")
        elif not any((r.get("where") or "").strip() for r in refs):
            problems.append(f"{cid}: у факта не указано место в источнике (where)")
    if ctype == "synthetic" and not any(
            sources_by_id.get(r.get("id"), {}).get("kind") == "synthetic" for r in refs):
        problems.append(f"{cid}: синтетическое утверждение должно ссылаться на источник вида synthetic")
    for dep in claim.get("based_on") or []:
        if dep not in claims_by_id:
            problems.append(f"{cid}: based_on ссылается на несуществующее {dep}")
    sup = claim.get("supersedes")
    if sup and sup not in claims_by_id:
        problems.append(f"{cid}: supersedes ссылается на несуществующее {sup}")
    return problems


def cmd_claim(args):
    pdir = project_dir(args.project)
    path = pdir / "evidence.jsonl"
    claims, _ = read_jsonl(path)
    sources, _ = read_jsonl(pdir / "sources.jsonl")
    by_id = {c["id"]: c for c in claims}
    row = {"id": next_id(claims, "E"), "text": args.text.strip(), "type": args.type,
           "sources": [parse_source_arg(s) for s in args.source or []],
           "based_on": split_ids(args.based_on), "confidence": args.confidence,
           "status": "active", "supersedes": args.supersedes, "added": now()[:10]}
    if args.quote:
        row["quote"] = args.quote.strip()
    if args.calc:
        row["calc"] = args.calc.strip()
    sources_by_id = {s["id"]: s for s in sources}
    problems = validate_claim(row, sources_by_id, by_id)
    notes = []
    if not problems and gr.needs_quote(row, sources_by_id):
        if not row.get("quote") and not row.get("calc"):
            problems.append("факт из материала нужно подкрепить дословной цитатой (--quote \"…\") "
                            "или файлом расчёта (--calc calc/out/…) — пересказ источника фактом не считается")
        else:
            errs, notes, checked = gr.ground(pdir, row, sources_by_id)
            problems += errs
            if checked is not None:
                row["quote_checked"] = checked
    if problems:
        raise Fail("Утверждение не записано:\n- " + "\n- ".join(problems))
    if args.supersedes:
        by_id[args.supersedes]["status"] = "superseded"
        by_id[args.supersedes]["superseded_by"] = row["id"]
        write_jsonl(path, claims + [row])
    else:
        append_jsonl(path, row)
    print(row["id"])
    for n in notes:
        print(f"внимание  {n}")
    if args.supersedes:
        print(f"{args.supersedes} заменено. Что затронуто:")
        print_impact(pdir, args.supersedes)


def vet_card(pdir, c, sources_by_id):
    lines = [f"{c['id']} · {c.get('text')}"]
    for ref in c.get("sources") or []:
        src = sources_by_id.get(ref.get("id"), {})
        local = f" · копия: {src['local']}" if src.get("local") else ""
        lines.append(f"  источник {ref.get('id')}: {src.get('title')} · место: {ref.get('where') or '—'}{local}")
        if src.get("local"):
            texts = sorted((pdir / "materials" / "_text").glob(Path(src["local"]).name + ".*"))
            if texts:
                lines.append("  текст для чтения: " + ", ".join(str(t.relative_to(pdir)) for t in texts))
    if c.get("quote"):
        lines.append(f"  цитата: «{c['quote']}»")
    if c.get("calc"):
        lines.append(f"  расчёт: {c['calc']}")
    return "\n".join(lines)


def cmd_vet(args):
    pdir = project_dir(args.project)
    path = pdir / "evidence.jsonl"
    claims, _ = read_jsonl(path)
    sources, _ = read_jsonl(pdir / "sources.jsonl")
    decisions, _ = read_jsonl(pdir / "decisions.jsonl")
    sources_by_id = {s["id"]: s for s in sources}
    by_id = {c["id"]: c for c in claims}
    if not args.id:
        crit = gr.critical_ids(pdir, by_id, decisions)
        todo = [by_id[i] for i in sorted(crit, key=lambda x: int(x.split("-")[1]))
                if by_id[i].get("type") == "fact" and by_id[i].get("status") == "active" and not by_id[i].get("vet")
                and gr.needs_quote(by_id[i], sources_by_id)]
        if not todo:
            print("Все критичные факты сверены.")
            return
        print(f"Критичных фактов без смысловой сверки: {len(todo)}. Для каждого: подтверждает ли цитата "
              "(или место в источнике) именно это утверждение?")
        for c in todo:
            print(vet_card(pdir, c, sources_by_id))
        return
    c = by_id.get(args.id)
    if not c:
        raise Fail(f"{args.id} нет в реестре.")
    if c.get("type") != "fact":
        raise Fail(f"{args.id} — не факт ({c.get('type')}): смысловая сверка нужна только фактам.")
    if not args.verdict:
        print(vet_card(pdir, c, sources_by_id))
        if c.get("vet"):
            v = c["vet"]
            print(f"  сверка: {gr.VERDICTS[v['verdict']]} ({v.get('by')}, {v.get('date')}) {v.get('note') or ''}")
        return
    if args.verdict != "supports" and not (args.note or "").strip():
        raise Fail("Объясните в --note, чего именно не хватает или что противоречит.")
    c["vet"] = {"verdict": args.verdict, "by": args.by, "date": now()[:10], "note": (args.note or "").strip()}
    write_jsonl(path, claims)
    print(f"{args.id}: {gr.VERDICTS[args.verdict]}")
    if args.verdict == "no":
        print("Факт не подтверждён источником. Отзовите его (revoke) или замените (claim … --supersedes) — "
              "и посмотрите, что на нём стоит:")
        print_impact(pdir, args.id)


def cmd_revoke(args):
    pdir = project_dir(args.project)
    path = pdir / "evidence.jsonl"
    claims, _ = read_jsonl(path)
    target = next((c for c in claims if c.get("id") == args.id), None)
    if not target:
        raise Fail(f"{args.id} нет в реестре.")
    target["status"] = "revoked"
    target["revoked_reason"] = args.reason
    target["revoked"] = now()[:10]
    write_jsonl(path, claims)
    print(f"{args.id} отозвано. Что затронуто:")
    print_impact(pdir, args.id)


def impact(pdir, claim_id):
    """Что опирается на утверждение: другие утверждения, решения, строки результатов."""
    claims, _ = read_jsonl(pdir / "evidence.jsonl")
    decisions, _ = read_jsonl(pdir / "decisions.jsonl")
    affected, frontier = {claim_id}, [claim_id]
    while frontier:
        cur = frontier.pop()
        for c in claims:
            if cur in (c.get("based_on") or []) and c["id"] not in affected:
                affected.add(c["id"])
                frontier.append(c["id"])
    dependent = [c for c in claims if c["id"] in affected and c["id"] != claim_id]
    hit_decisions = [d for d in decisions if affected & set(d.get("based_on") or [])]
    lines = []
    for name in RESULT_FILES:
        path = pdir / name
        if not path.exists():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            ids = {i for m in REF_RE.finditer(line) for i in split_ids(m.group(1))}
            if ids & affected:
                lines.append((name, n, line.strip()))
    return dependent, hit_decisions, lines


def print_impact(pdir, claim_id):
    dependent, decisions, lines = impact(pdir, claim_id)
    if not (dependent or decisions or lines):
        print("- ничего: на это утверждение пока никто не опирается")
        return
    for c in dependent:
        print(f"- утверждение {c['id']} ({c.get('type')}): {c.get('text')}")
    for d in decisions:
        print(f"- решение {d['id']}: {d.get('text')} — ответственный: {d.get('owner') or 'не указан'}")
    for name, n, text in lines:
        print(f"- {name}:{n}: {text[:160]}")


def cmd_impact(args):
    pdir = project_dir(args.project)
    claims, _ = read_jsonl(pdir / "evidence.jsonl")
    if not any(c.get("id") == args.id for c in claims):
        raise Fail(f"{args.id} нет в реестре.")
    print(f"Если {args.id} изменится, затронуто:")
    print_impact(pdir, args.id)


def cmd_decide(args):
    pdir = project_dir(args.project)
    path = pdir / "decisions.jsonl"
    decisions, _ = read_jsonl(path)
    claims, _ = read_jsonl(pdir / "evidence.jsonl")
    known = {c["id"] for c in claims}
    based = split_ids(args.based_on)
    missing = [b for b in based if b not in known]
    if missing:
        raise Fail("Решение не записано: в реестре нет " + ", ".join(missing))
    if not based:
        raise Fail("Решение не записано: укажите основания (--based-on E-001,E-002).")
    row = {"id": next_id(decisions, "D"), "date": now()[:10], "text": args.text.strip(), "based_on": based,
           "owner": args.owner, "metric": args.metric, "review_if": args.review_if, "status": "active"}
    append_jsonl(path, row)
    print(row["id"])


def cmd_decision(args):
    pdir = project_dir(args.project)
    path = pdir / "decisions.jsonl"
    decisions, _ = read_jsonl(path)
    target = next((d for d in decisions if d.get("id") == args.id), None)
    if not target:
        raise Fail(f"{args.id} нет в decisions.jsonl.")
    if args.status == "confirmed":
        target["reviewed"] = now()[:10]
    else:
        target["status"] = args.status
        target["closed"] = now()[:10]
    if args.note:
        target["note"] = args.note
    write_jsonl(path, decisions)
    words = {"confirmed": "подтверждено после пересмотра", "revised": "пересмотрено", "cancelled": "отменено"}
    print(f"{args.id}: {words[args.status]}")


def review(pdir, days):
    """Что требует внимания после принятых решений."""
    decisions, _ = read_jsonl(pdir / "decisions.jsonl")
    claims, _ = read_jsonl(pdir / "evidence.jsonl")
    sources, _ = read_jsonl(pdir / "sources.jsonl")
    claims_by_id = {c["id"]: c for c in claims}
    sources_by_id = {s["id"]: s for s in sources}
    today = datetime.now().date()
    urgent, shaky, aging, incomplete, watch = [], [], [], [], []
    for d in decisions:
        if d.get("status") != "active":
            continue
        text = d.get("text") or ""
        label = f"{d['id']} «{text if len(text) <= 90 else text[:87] + '…'}»"
        unproven = []
        for dep in d.get("based_on") or []:
            c = claims_by_id.get(dep)
            if not c:
                continue
            if c.get("status") != "active":
                why = "отозвано" if c.get("status") == "revoked" else f"заменено на {c.get('superseded_by', '?')}"
                urgent.append(f"{label}: основание {dep} {why}")
                continue
            if c.get("type") != "fact":
                unproven.append(dep)
            ages = []
            for ref in c.get("sources") or []:
                got = sources_by_id.get(ref.get("id"), {}).get("retrieved")
                try:
                    ages.append((today - datetime.strptime(got, "%Y-%m-%d").date()).days)
                except (TypeError, ValueError):
                    pass
            if ages and min(ages) > days:
                aging.append(f"{label}: данные для {dep} получены {min(ages)} дн. назад — стоит перепроверить")
        if unproven:
            shaky.append(f"{label}: опирается на непроверенные {', '.join(unproven)} — подробности: show <проект> <номер>")
        missing = [name for key, name in (("owner", "ответственный"), ("metric", "показатель"),
                                          ("review_if", "условие пересмотра")) if not d.get(key)]
        if missing:
            incomplete.append(f"{label}: не указано — {', '.join(missing)}")
        if d.get("review_if"):
            watch.append(f"{label}: пересмотреть, если {d['review_if']} "
                         f"(показатель: {d.get('metric') or '—'}, отвечает: {d.get('owner') or '—'})")
    return [("Решать сейчас — основание изменилось", urgent),
            ("Стоит на гипотезах — нужна проверка", shaky),
            ("Данные стареют", aging),
            ("Решение записано не полностью", incomplete),
            ("Условия пересмотра — сверить с текущими показателями", watch)]


def cmd_review(args):
    pdir = project_dir(args.project)
    sections = review(pdir, args.days)
    if not any(items for _, items in sections):
        print("Активных решений нет или по ним нет замечаний.")
        return
    for title, items in sections:
        if items:
            print(title + ":")
            for item in items:
                print(f"- {item}")


def cmd_log(args):
    pdir = project_dir(args.project)
    rows, _ = read_jsonl(pdir / "journal.jsonl")
    if args.key:
        for r in rows:
            if r.get("key") == args.key and r.get("result") == "ok":
                print(f"Уже выполнено {r.get('ts', '')[:16]}: {r.get('action')}. Повторять не нужно.")
                return
    step = args.step or load_state(pdir)["step"]
    row = journal(pdir, step=step, action=args.action, tool=args.tool, model=args.model,
                  minutes=args.minutes, cost_rub=args.cost, cost_basis=args.basis,
                  result=args.result, human_help=args.human_help, key=args.key)
    print(f"Записано: {row['step']} · {row['action']} · {row['result']}")


def cmd_step(args):
    pdir = project_dir(args.project)
    st = load_state(pdir)
    for done in args.done or []:
        report = check(pdir, finishing=done)
        if report["errors"]:
            print_report(report)
            raise Fail(f"Шаг «{STEP_NAMES[done]}» не закрыт: сначала исправьте ошибки проверки.")
        if done not in st["done"]:
            st["done"].append(done)
        if args.waiting is None:
            st["waiting_for_user"] = None  # ожидание относилось к закрытому шагу
        idx = STEPS.index(done)
        if st["step"] == done and idx + 1 < len(STEPS):
            st["step"] = STEPS[idx + 1]
            if args.next is None:
                st["next_action"] = f"начать шаг «{STEP_NAMES[st['step']]}» по навыку skills/{st['step']}"
    if args.mode:
        st["mode"] = args.mode
    if args.set:
        st["step"] = args.set
    if args.next is not None:
        st["next_action"] = args.next
    if args.waiting is not None:
        st["waiting_for_user"] = args.waiting or None
    for q in args.question or []:
        if q not in st["open_questions"]:
            st["open_questions"].append(q)
    for q in args.answered or []:
        st["open_questions"] = [x for x in st["open_questions"] if x != q]
    save_state(pdir, st)
    print(f"Состояние сохранено: шаг «{STEP_NAMES[st['step']]}», дальше — {st.get('next_action') or '—'}")


def meaningful(path):
    """Файл результата начат, если в нём есть что-то кроме заголовков."""
    if not path.exists():
        return False
    return any(l.strip() and not l.lstrip().startswith("#") for l in path.read_text(encoding="utf-8").splitlines())


def check(pdir, finishing=None):
    errors, warnings = [], []
    sources, e1 = read_jsonl(pdir / "sources.jsonl")
    claims, e2 = read_jsonl(pdir / "evidence.jsonl")
    decisions, e3 = read_jsonl(pdir / "decisions.jsonl")
    errors += e1 + e2 + e3
    sources_by_id = {s.get("id"): s for s in sources}
    claims_by_id = {c.get("id"): c for c in claims}
    if len(sources_by_id) != len(sources):
        errors.append("sources.jsonl: повторяющиеся номера источников")
    if len(claims_by_id) != len(claims):
        errors.append("evidence.jsonl: повторяющиеся номера утверждений")
    for s in sources:
        if not (s.get("ref") or "").strip():
            errors.append(f"{s.get('id')}: у источника нет ссылки или пути (ref)")
        if s.get("local") and not (pdir / s["local"]).exists():
            warnings.append(f"{s.get('id')}: локальная копия {s['local']} не найдена")
    strict = finishing in ("options", "strategy")
    critical = gr.critical_ids(pdir, claims_by_id, decisions)
    for c in claims:
        if c.get("status") == "active" and c.get("type") == "fact":
            errs, warns, _ = gr.ground(pdir, c, sources_by_id)
            errors += errs
            warnings += warns
            verdict = (c.get("vet") or {}).get("verdict")
            if verdict == "no":
                errors.append(f"{c['id']}: смысловая сверка — источник не подтверждает факт; отзовите или замените")
            elif verdict == "partial":
                warnings.append(f"{c['id']}: источник подтверждает факт частично — "
                                f"{(c.get('vet') or {}).get('note') or 'проверьте формулировку'}")
            if c["id"] in critical:
                bucket = errors if strict else warnings
                if gr.needs_quote(c, sources_by_id) and not c.get("quote") and not c.get("calc"):
                    bucket.append(f"{c['id']}: критичный факт без дословной цитаты и расчёта")
                if not verdict and gr.needs_quote(c, sources_by_id):
                    bucket.append(f"{c['id']}: критичный факт не прошёл смысловую сверку — vet {pdir.name}")
    for c in claims:
        if c.get("status") == "active":
            errors += validate_claim(c, sources_by_id, claims_by_id)
            for dep in c.get("based_on") or []:
                if claims_by_id.get(dep, {}).get("status") == "revoked":
                    errors.append(f"{c['id']}: опирается на отозванное {dep} — пересмотрите или отзовите")
                elif claims_by_id.get(dep, {}).get("status") == "superseded":
                    warnings.append(f"{c['id']}: опирается на {dep}, которое заменено на "
                                    f"{claims_by_id[dep].get('superseded_by', '?')} — проверьте, остаётся ли в силе")

    for name in RESULT_FILES:
        path = pdir / name
        if not path.exists():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            where = f"{name}:{n}"
            ids = [i for m in REF_RE.finditer(line) for i in split_ids(m.group(1))]
            low = line.lower()
            cited = []
            for cid in ids:
                c = claims_by_id.get(cid)
                if not c:
                    errors.append(f"{where}: ссылка на несуществующее {cid}")
                elif c.get("status") == "revoked":
                    errors.append(f"{where}: ссылка на отозванное {cid}")
                elif c.get("status") == "superseded":
                    errors.append(f"{where}: {cid} заменено на {c.get('superseded_by', '?')} — обновите ссылку и текст")
                else:
                    cited.append(c)
            if cited:
                if any(c["type"] == "synthetic" for c in cited) and not any(m in low for m in SYNTH_MARKS):
                    errors.append(f"{where}: ответ модельного респондента не назван синтетическим")
                # Заголовок называет допущение, а не утверждает его: правило слов-маркеров к нему не применяется.
                if (all(c["type"] != "fact" for c in cited) and not line.lstrip().startswith("#")
                        and not any(m in low for m in HEDGES + SYNTH_MARKS)):
                    errors.append(f"{where}: гипотеза или прогноз поданы как факт — "
                                  "назовите это предположением или найдите источник")
            elif (name != "verification.md"
                  and re.search(r"\d", re.sub(r"^\s*(\d+[.)]|[-*])\s+", "", line)) and len(line.strip()) > 40
                  and "(вывод)" not in low
                  and not line.lstrip().startswith(("#", "|", ">"))):
                warnings.append(f"{where}: цифра без ссылки на реестр")

    findings = pdir / "findings.md"
    if meaningful(findings) and "чего мы не знаем" not in findings.read_text(encoding="utf-8").lower():
        errors.append("findings.md: нет раздела «Чего мы не знаем»")
    options = pdir / "options.md"
    if meaningful(options):
        text = options.read_text(encoding="utf-8").lower()
        count = len(re.findall(r"^##\s+вариант", text, flags=re.M))
        if count < 3:
            errors.append(f"options.md: вариантов {count}, нужно не меньше трёх (заголовки «## Вариант …»)")
        if "оставить как есть" not in text:
            errors.append("options.md: нет варианта «оставить как есть»")
        if "закрыть направление" not in text:
            warnings.append("options.md: нет варианта «закрыть направление»")
        if "возражен" not in text:
            errors.append("options.md: у вариантов нет возражений")

    required = {"frame": ["brief.md"], "research": ["plan.md", "findings.md"], "options": ["options.md"],
                "strategy": ["strategy-product.md", "strategy-comms.md", "verification.md", "summary.md"]}
    for name in required.get(finishing, []):
        if not meaningful(pdir / name):
            errors.append(f"{name}: не заполнен, а шаг «{STEP_NAMES[finishing]}» закрывается")
    if finishing == "collect" and not sources:
        errors.append("sources.jsonl: ни одного источника, а шаг «Материалы» закрывается")

    for d in decisions:
        if d.get("status") != "active":
            continue
        for dep in d.get("based_on") or []:
            st = claims_by_id.get(dep, {}).get("status")
            if st is None:
                errors.append(f"{d.get('id')}: основание {dep} не найдено в реестре")
            elif st != "active":
                warnings.append(f"{d.get('id')}: основание {dep} устарело — решение «{d.get('text')}» пора пересмотреть")
    return {"errors": errors, "warnings": warnings, "claims": len(claims), "sources": len(sources)}


def print_report(report, out=None):
    out = out or sys.stdout
    for e in report["errors"]:
        print(f"ОШИБКА  {e}", file=out)
    for w in report["warnings"]:
        print(f"внимание  {w}", file=out)
    if not report["errors"]:
        print(f"Проверка пройдена: источников {report['sources']}, утверждений {report['claims']}, "
              f"замечаний {len(report['warnings'])}.", file=out)
    else:
        print(f"Проверка не пройдена: ошибок {len(report['errors'])}.", file=out)


def cmd_check(args):
    report = check(project_dir(args.project))
    print_report(report)
    return 1 if report["errors"] else 0


def cmd_cost(args):
    pdir = project_dir(args.project)
    rows, _ = read_jsonl(pdir / "journal.jsonl")
    minutes, _ = cost_summary(rows)
    print(f"Проект {args.project}: {len(rows)} действий")
    print(f"Время по отметкам журнала: {clock_minutes(rows)} мин "
          f"(от записи до записи, перерывы дольше {PAUSE_MIN} мин не считаются)")
    if minutes:
        print(f"Время по оценке агента: {minutes:g} мин — это оценка труда, а не замер")
    print(f"Расходы: {money_line(rows)}")
    for step in STEPS:
        part = [r for r in rows if r.get("step") == step]
        if part:
            print(f"- {STEP_NAMES[step]}: {len(part)} действий; {money_line(part)}")
    estimated = sum(float(r.get("cost_rub") or 0) for r in rows if r.get("cost_basis") != "точно")
    print(f"Из расходов по оценке, а не по счёту: {estimated:g} ₽")
    if money_line(rows) == "расходы не измерены":
        print("Чтобы узнать расходы, возьмите цифру из своей среды (например, счётчик расхода в Claude Code) "
              "и запишите: log <проект> --action \"расход за сеанс\" --tool среда --cost <рубли> --basis точно")
    print(f"Ошибок инструментов: {sum(1 for r in rows if r.get('result') == 'error')}")
    print(f"Вмешательств человека: {sum(1 for r in rows if r.get('human_help'))}")


def cmd_extract(args):
    import extract as ex
    pdir = project_dir(args.project)
    src = Path(args.file)
    if not src.is_absolute():
        src = pdir / src
    if not src.is_file():
        raise Fail(f"Файл не найден: {src}")
    out_dir = pdir / "materials" / "_text"
    done = sorted(out_dir.glob(src.name + ".*")) if out_dir.exists() else []
    if done and not args.force and all(p.stat().st_mtime >= src.stat().st_mtime for p in done):
        print("Уже разобран, повторять не нужно:")
        for p in done:
            print(f"- {p.relative_to(pdir)}")
        return
    try:
        parts = ex.extract(src)
    except ex.ExtractError as exc:
        raise Fail(str(exc))
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Разобран {src.name}:")
    for suffix, text, note in parts:
        out = out_dir / (src.name + suffix)
        write_atomic(out, text)
        print(f"- {out.relative_to(pdir)} — {len(text.splitlines())} строк, {len(text)} знаков; {note}")
    if not any(text.strip() for _, text, _ in parts):
        print("Внимание: текста в файле не найдено (возможно, это скан или картинки).")


def stems(words):
    out = []
    for w in re.findall(r"[0-9a-zа-яё]+", " ".join(words).lower()):
        out.append(w[:3] if len(w) <= 4 else w[:len(w) - 2])
    return out


def cmd_find(args):
    pdir = project_dir(args.project)
    keys = stems(args.words)
    if not keys:
        raise Fail("Укажите слова для поиска.")
    claims, _ = read_jsonl(pdir / "evidence.jsonl")
    sources, _ = read_jsonl(pdir / "sources.jsonl")
    decisions, _ = read_jsonl(pdir / "decisions.jsonl")
    hits = []

    def consider(label, text):
        low = (text or "").lower()
        score = sum(1 for k in keys if k in low)
        if score:
            hits.append((score, label))

    for c in claims:
        status = "" if c.get("status") == "active" else f", {c.get('status')}"
        consider(f"{c['id']} ({c.get('type')}{status}): {c.get('text')}", c.get("text"))
    for s in sources:
        consider(f"{s['id']} ({s.get('kind')}): {s.get('title')} — {s.get('ref')}",
                 " ".join(filter(None, [s.get("title"), s.get("note"), s.get("ref")])))
    for d in decisions:
        consider(f"{d['id']} (решение, {d.get('status')}): {d.get('text')}", d.get("text"))
    if args.files:
        paths = [pdir / n for n in RESULT_FILES + ["brief.md", "plan.md"]]
        paths += sorted((pdir / "materials" / "_text").glob("*")) if (pdir / "materials" / "_text").exists() else []
        for path in paths:
            if not path.is_file():
                continue
            for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                consider(f"{path.relative_to(pdir)}:{n}: {line.strip()[:160]}", line)
    full = [h for h in hits if h[0] == len(keys)]
    shown = full or sorted(hits, key=lambda h: -h[0])
    if not shown:
        print("Ничего не найдено. Попробуйте другие слова или добавьте --files для поиска по материалам.")
        return
    if not full:
        print("Точных совпадений по всем словам нет; частичные:")
    for _, label in shown[:args.limit]:
        print(f"- {label}")
    if len(shown) > args.limit:
        print(f"… ещё {len(shown) - args.limit}. Уточните запрос или увеличьте --limit.")


def cmd_show(args):
    pdir = project_dir(args.project)
    claims, _ = read_jsonl(pdir / "evidence.jsonl")
    sources, _ = read_jsonl(pdir / "sources.jsonl")
    decisions, _ = read_jsonl(pdir / "decisions.jsonl")
    sources_by_id = {s["id"]: s for s in sources}
    claims_by_id = {c["id"]: c for c in claims}
    rid = args.id
    if rid in claims_by_id:
        c = claims_by_id[rid]
        print(f"{rid} · {c.get('type')} · уверенность {c.get('confidence')} · {c.get('status')} · добавлено {c.get('added')}")
        print(c.get("text"))
        if c.get("status") == "superseded":
            print(f"Заменено на {c.get('superseded_by')}")
        if c.get("status") == "revoked":
            print(f"Отозвано: {c.get('revoked_reason')}")
        for ref in c.get("sources") or []:
            s = sources_by_id.get(ref.get("id"), {})
            print(f"Источник {ref.get('id')}: {s.get('title')} — {s.get('ref')} · место: {ref.get('where') or '—'}")
        if c.get("quote"):
            mark = {True: "найдена в источнике", False: "НЕ найдена в источнике", None: "не с чем сверить"}[c.get("quote_checked")]
            print(f"Цитата ({mark}): «{c['quote']}»")
        if c.get("calc"):
            print(f"Расчёт: {c['calc']}")
        if c.get("vet"):
            v = c["vet"]
            print(f"Смысловая сверка: {gr.VERDICTS[v['verdict']]} ({v.get('by')}, {v.get('date')}) {v.get('note') or ''}".rstrip())
        for dep in c.get("based_on") or []:
            print(f"Опирается на {dep}: {claims_by_id.get(dep, {}).get('text')}")
        print("Что опирается на него:")
        print_impact(pdir, rid)
    elif rid in sources_by_id:
        s = sources_by_id[rid]
        print(f"{rid} · {s.get('kind')} · получен {s.get('retrieved')}")
        print(f"{s.get('title')} — {s.get('ref')}" + (f" · копия: {s['local']}" if s.get("local") else ""))
        used = [c for c in claims if any(r.get("id") == rid for r in c.get("sources") or [])]
        print(f"Утверждений из этого источника: {len(used)}")
        for c in used:
            print(f"- {c['id']} ({c.get('type')}, {c.get('status')}): {c.get('text')}")
    else:
        d = next((d for d in decisions if d.get("id") == rid), None)
        if not d:
            raise Fail(f"{rid} не найдено ни в реестре, ни в источниках, ни в решениях.")
        print(f"{rid} · {d.get('status')} · {d.get('date')}")
        print(d.get("text"))
        print(f"Ответственный: {d.get('owner') or '—'} · показатель: {d.get('metric') or '—'}")
        print(f"Пересмотреть, если: {d.get('review_if') or '—'}")
        for dep in d.get("based_on") or []:
            c = claims_by_id.get(dep, {})
            print(f"Основание {dep} ({c.get('type')}, {c.get('status')}): {c.get('text')}")


def cmd_hook_edit(args):
    """Хук после правки файла: если это результат проекта, проверяет его сразу."""
    try:
        data = json.load(sys.stdin)
        path = Path(data.get("tool_input", {}).get("file_path", "")).resolve()
    except (ValueError, OSError):
        return 0
    root = projects_root().resolve()
    if root not in path.parents or path.name not in RESULT_FILES:
        return 0
    pdir = root / path.relative_to(root).parts[0]
    if not (pdir / "state.json").exists():
        return 0
    report = check(pdir)
    mine = [e for e in report["errors"] if e.startswith(path.name)]
    if not mine:
        return 0
    print(f"Проверка {path.name} нашла нарушения правил доказательности:", file=sys.stderr)
    for e in mine:
        print(f"- {e}", file=sys.stderr)
    return 2


def build_parser():
    p = argparse.ArgumentParser(prog="strateg.py", description="Инструменты агента «Стратег»")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="создать проект")
    s.add_argument("project")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("status", help="проекты или состояние проекта")
    s.add_argument("project", nargs="?")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("source", help="добавить источник")
    s.add_argument("project")
    s.add_argument("--kind", required=True, choices=SOURCE_KINDS)
    s.add_argument("--title", required=True)
    s.add_argument("--ref", required=True, help="ссылка или путь к материалу")
    s.add_argument("--local", help="путь к копии внутри папки проекта")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_source)

    s = sub.add_parser("claim", help="добавить утверждение в реестр")
    s.add_argument("project")
    s.add_argument("--type", required=True, choices=CLAIM_TYPES)
    s.add_argument("--text", required=True)
    s.add_argument("--source", action="append", metavar="S-001:место", help="можно несколько раз")
    s.add_argument("--based-on", help="E-001,E-002")
    s.add_argument("--confidence", default="medium", choices=["high", "medium", "low"])
    s.add_argument("--supersedes", help="номер утверждения, которое заменяется")
    s.add_argument("--quote", help="дословный фрагмент источника, на котором стоит факт")
    s.add_argument("--calc", help="файл с выводом расчёта внутри проекта, если факт посчитан")
    s.set_defaults(fn=cmd_claim)

    s = sub.add_parser("vet", help="смысловая сверка факта с источником")
    s.add_argument("project")
    s.add_argument("id", nargs="?", help="без номера — список критичных фактов без сверки")
    s.add_argument("--verdict", choices=sorted(gr.VERDICTS), help="supports — подтверждает, partial — частично, no — не подтверждает")
    s.add_argument("--by", default="self", choices=["self", "helper", "human"], help="кто сверял: сам агент, отдельный помощник, человек")
    s.add_argument("--note", help="что не так (обязательно для partial и no)")
    s.set_defaults(fn=cmd_vet)

    s = sub.add_parser("revoke", help="отозвать утверждение")
    s.add_argument("project")
    s.add_argument("id")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_revoke)

    s = sub.add_parser("impact", help="что опирается на утверждение")
    s.add_argument("project")
    s.add_argument("id")
    s.set_defaults(fn=cmd_impact)

    s = sub.add_parser("decide", help="записать решение")
    s.add_argument("project")
    s.add_argument("--text", required=True)
    s.add_argument("--based-on", required=True)
    s.add_argument("--owner")
    s.add_argument("--metric")
    s.add_argument("--review-if")
    s.set_defaults(fn=cmd_decide)

    s = sub.add_parser("decision", help="изменить статус решения")
    s.add_argument("project")
    s.add_argument("id")
    s.add_argument("--status", required=True, choices=["confirmed", "revised", "cancelled"])
    s.add_argument("--note")
    s.set_defaults(fn=cmd_decision)

    s = sub.add_parser("review", help="что решать сейчас и какие основания устарели")
    s.add_argument("project")
    s.add_argument("--days", type=int, default=30, help="через сколько дней данные считаются старыми")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("log", help="запись в журнал")
    s.add_argument("project")
    s.add_argument("--action", required=True)
    s.add_argument("--tool", required=True)
    s.add_argument("--step", choices=STEPS)
    s.add_argument("--model")
    s.add_argument("--minutes", type=float, default=0)
    s.add_argument("--cost", type=float, default=None, help="рубли; не указывайте, если расход не измерен")
    s.add_argument("--basis", default="оценка", choices=["точно", "оценка"])
    s.add_argument("--result", default="ok", choices=["ok", "error", "skipped"])
    s.add_argument("--human-help", action="store_true")
    s.add_argument("--key", help="метка действия: повтор с той же меткой не выполняется")
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("step", help="обновить состояние")
    s.add_argument("project")
    s.add_argument("--done", action="append", choices=STEPS, help="закрыть шаг (с проверкой)")
    s.add_argument("--set", choices=STEPS, help="перейти на шаг без закрытия")
    s.add_argument("--mode", choices=sorted(MODES), help="режим работы: fast — быстрый, full — полный")
    s.add_argument("--next", help="следующее действие")
    s.add_argument("--waiting", help="чего ждём от пользователя; пустая строка — сбросить")
    s.add_argument("--question", action="append", help="добавить открытый вопрос")
    s.add_argument("--answered", action="append", help="снять открытый вопрос")
    s.set_defaults(fn=cmd_step)

    s = sub.add_parser("check", help="проверка реестра и ссылок")
    s.add_argument("project")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("cost", help="время и расходы")
    s.add_argument("project")
    s.set_defaults(fn=cmd_cost)

    s = sub.add_parser("extract", help="перевести материал в текст с метками места")
    s.add_argument("project")
    s.add_argument("file", help="путь внутри папки проекта, например materials/отчёт.docx")
    s.add_argument("--force", action="store_true", help="разобрать заново")
    s.set_defaults(fn=cmd_extract)

    s = sub.add_parser("find", help="поиск по реестру, источникам и решениям")
    s.add_argument("project")
    s.add_argument("words", nargs="+")
    s.add_argument("--files", action="store_true", help="искать также в результатах и разобранных материалах")
    s.add_argument("--limit", type=int, default=15)
    s.set_defaults(fn=cmd_find)

    s = sub.add_parser("show", help="карточка утверждения, источника или решения со связями")
    s.add_argument("project")
    s.add_argument("id")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("hook-edit", help="для хуков среды: проверка после правки файла")
    s.set_defaults(fn=cmd_hook_edit)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args) or 0
    except Fail as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    # CLI outputs Unicode (including ₽) even when Windows pipes default to cp1251.
    # Do not change a host application's streams when imported as a module.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
