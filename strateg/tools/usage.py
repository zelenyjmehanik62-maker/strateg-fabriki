"""Расход прогона по журналу Claude Code: токены по моделям и стоимость по прайс-листу.

Claude Code пишет журнал каждого сеанса в JSONL; у каждого ответа модели там есть `usage`:
обычный ввод, запись в кэш, чтение из кэша, вывод, поисковые запросы. Здесь они суммируются
и умножаются на публичные цены API из prices.json.

Время делится на две части: работа модели и ожидание человека — промежутки, которые
заканчиваются его сообщением (пока он читает и отвечает). Паузы дольше PAUSE_MIN минут —
перерыв, их нет ни в одной части.

Поиск и загрузка страниц инструментами среды (WebSearch, WebFetch в Claude Code) идут отдельными
запросами, которых нет в `usage` ответа модели. Их считаем по вызовам инструментов: поиски — по
`searchCount` в результате (нет его — один поиск на вызов) и по цене поиска из прайс-листа; токены
обработки страниц в журнал не попадают и называются неизмеренными.

Это стоимость **по прайс-листу**: столько стоил бы прогон, если бы шёл через API по публичным
ценам. На подписке пользователь платит не за токены, на договорных ценах — иначе.
"""
import json
from datetime import datetime
from pathlib import Path

PRICES = Path(__file__).resolve().parent / "prices.json"
PAUSE_MIN = 20


def load_prices():
    return json.loads(PRICES.read_text(encoding="utf-8"))


def price_for(model, prices):
    for key, p in prices["models"].items():
        if model and model.startswith(key):
            return key, p
    return None, None


def parse(paths):
    """Сводит ответы модели из одного или нескольких журналов. Один ответ может быть записан
    несколькими строками (по блокам содержимого) — берём последнюю запись на каждый id."""
    responses, stamps = {}, []
    tools = {"search_calls": 0, "searches": 0, "fetches": 0}
    pending = {}
    human_gaps = []
    for path in paths:
        prev = None
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ts = rec.get("timestamp")
            now = None
            if ts:
                try:
                    now = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    stamps.append(now)
                except ValueError:
                    pass
            msg = rec.get("message")
            if now and prev and is_human(rec):
                human_gaps.append((now - prev).total_seconds() / 60)
            if now and rec.get("type") == "assistant":
                prev = now  # ожидание человека считается от последнего ответа модели
            if not isinstance(msg, dict):
                continue
            content = msg.get("content") if isinstance(msg.get("content"), list) else []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use" and block.get("name") in ("WebSearch", "WebFetch") \
                        and block.get("id") not in pending:
                    pending[block.get("id")] = block["name"]
                    if block["name"] == "WebSearch":
                        tools["search_calls"] += 1
                        tools["searches"] += 1
                    else:
                        tools["fetches"] += 1
                elif block.get("type") == "tool_result" and pending.get(block.get("tool_use_id")) == "WebSearch":
                    result = rec.get("toolUseResult")
                    count = result.get("searchCount") if isinstance(result, dict) else None
                    if isinstance(count, int) and count != 1:
                        tools["searches"] += count - 1
                    pending[block.get("tool_use_id")] = "WebSearch:done"
            if rec.get("type") == "assistant" and msg.get("usage"):
                responses[msg.get("id") or f"{path}:{len(responses)}"] = msg
    return list(responses.values()), sorted(stamps), tools, human_gaps


SERVICE_PREFIXES = ("<system-reminder>", "<local-command", "<command-", "Caveat:", "[Request interrupted")


def is_human(rec):
    """Сообщение человека: запись пользователя без результатов инструментов и не служебная вставка среды."""
    if rec.get("type") != "user":
        return False
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return False
        text = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    else:
        text = content or ""
    text = text.strip()
    return bool(text) and not text.startswith(SERVICE_PREFIXES)


def active_minutes(stamps):
    total = 0.0
    for a, b in zip(stamps, stamps[1:]):
        gap = (b - a).total_seconds() / 60
        if gap <= PAUSE_MIN:
            total += gap
    return total


def summarize(paths, prices=None):
    prices = prices or load_prices()
    responses, stamps, tools, human_gaps = parse(paths)
    by_model, unknown = {}, set()
    for msg in responses:
        u = msg["usage"]
        key, p = price_for(msg.get("model"), prices)
        if not p:
            unknown.add(msg.get("model"))
            key = msg.get("model") or "?"
        row = by_model.setdefault(key, {"responses": 0, "input": 0, "cache_write_5m": 0, "cache_write_1h": 0,
                                        "cache_read": 0, "output": 0, "web_search": 0, "cost": 0.0})
        cc = u.get("cache_creation") or {}
        w1h = cc.get("ephemeral_1h_input_tokens", 0) or 0
        w5m = cc.get("ephemeral_5m_input_tokens", (u.get("cache_creation_input_tokens") or 0) - w1h) or 0
        inp, read, out = u.get("input_tokens", 0) or 0, u.get("cache_read_input_tokens", 0) or 0, u.get("output_tokens", 0) or 0
        searches = ((u.get("server_tool_use") or {}).get("web_search_requests", 0)) or 0
        row["responses"] += 1
        row["input"] += inp
        row["cache_write_5m"] += w5m
        row["cache_write_1h"] += w1h
        row["cache_read"] += read
        row["output"] += out
        row["web_search"] += searches
        if p:
            # Цена ввода зависит от длины запроса у моделей с порогом (Haiku 5.5: до 100 тыс. токенов)
            prompt = inp + read + w5m + w1h
            tier = p["long"] if p.get("long") and prompt > p["long"]["above"] else p
            base_in, base_out = tier["input"], tier["output"]
            read_price = tier.get("cache_read", base_in * 0.1) if tier is not p else p["cache_read"]
            cost = (inp * base_in + w5m * base_in * prices["cache_write_5m"] + w1h * base_in * prices["cache_write_1h"]
                    + read * read_price + out * base_out) / 1_000_000
            cost += searches * prices["web_search_per_1000"] / 1000
            row["cost"] += cost
    tool_search_cost = tools["searches"] * prices["web_search_per_1000"] / 1000
    total = sum(r["cost"] for r in by_model.values()) + tool_search_cost
    wall = (stamps[-1] - stamps[0]).total_seconds() / 60 if len(stamps) > 1 else 0.0
    return {"by_model": by_model, "total_usd": total, "unknown_models": sorted(m for m in unknown if m),
            "wall_minutes": wall, "active_minutes": active_minutes(stamps), "responses": len(responses),
            "human_minutes": sum(g for g in human_gaps if g <= PAUSE_MIN),
            "human_replies": sum(1 for g in human_gaps if g <= PAUSE_MIN),
            "prices_date": prices.get("date"), "usd_rub": prices.get("usd_rub"),
            "tools": tools, "tool_search_usd": tool_search_cost}


def report(s):
    human = s.get("human_minutes", 0.0)
    lines = [f"Ответов модели: {s['responses']}; время по журналу среды: работа модели {s['active_minutes'] - human:.1f} мин, "
             f"ожидание ответов человека {human:.1f} мин ({s.get('human_replies', 0)} сообщ.); "
             f"всего {s['wall_minutes']:.1f} мин, паузы дольше {PAUSE_MIN} мин — перерыв и не считаются"]
    for model, r in sorted(s["by_model"].items()):
        searches = f"поисков через API {r['web_search']}; " if r["web_search"] else ""
        lines.append((f"- {model}: ответов {r['responses']}; ввод {r['input']:,}, запись в кэш {r['cache_write_5m'] + r['cache_write_1h']:,}, "
                      f"чтение из кэша {r['cache_read']:,}, вывод {r['output']:,} токенов; {searches}"
                      f"≈ ${r['cost']:.2f}").replace(",", " "))
    t = s.get("tools") or {}
    if t.get("search_calls") or t.get("fetches"):
        lines.append(f"- поиск и страницы инструментами среды: поисков {t['searches']} (≈ ${s['tool_search_usd']:.2f} по цене поиска), "
                     f"загрузок страниц {t['fetches']}; токены, которые среда тратит на обработку результатов поиска и страниц, "
                     "в журнал не попадают — не измерены: итог ниже включает цену поисков, но не эти токены")
    rub = f" ≈ {s['total_usd'] * s['usd_rub']:.0f} ₽" if s.get("usd_rub") else ""
    lines.append(f"Итого по прайс-листу на {s['prices_date']}: ${s['total_usd']:.2f}{rub}. "
                 "Это цена прогона через API по публичным ценам, а не счёт подписки.")
    if s["unknown_models"]:
        lines.append("Нет цены для моделей: " + ", ".join(s["unknown_models"]) + " — их расход в итог не вошёл; добавьте цену в tools/prices.json.")
    return "\n".join(lines)


# --- Журналы Codex (~/.codex/sessions/…/rollout-*.jsonl) ---------------------------------
# Формат описан по известному устройству журналов Codex CLI и проверен на искусственном примере;
# на настоящем журнале — сверить (T39). Записи: {"timestamp", "type", "payload"}; модель — в
# "turn_context", токены — накопительно в event_msg "token_count", сообщения человека — event_msg
# "user_message".

def is_codex(path):
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[:20]:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and "payload" in rec and rec.get("type") in (
                "session_meta", "turn_context", "response_item", "event_msg"):
            return True
    return False


def summarize_codex(paths, prices=None):
    prices = prices or load_prices()
    models, stamps, human_gaps = set(), [], []
    tokens = {"input": 0, "cached": 0, "output": 0, "reasoning": 0}
    replies = 0
    for path in paths:
        best, prev = {}, None
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            p = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
            now = None
            if rec.get("timestamp"):
                try:
                    now = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
                    stamps.append(now)
                except ValueError:
                    pass
            kind = (rec.get("type"), p.get("type"))
            if rec.get("type") == "turn_context" and p.get("model"):
                models.add(p["model"])
            if kind == ("event_msg", "token_count"):
                total = ((p.get("info") or {}).get("total_token_usage")) or {}
                if total.get("total_tokens", 0) >= best.get("total_tokens", 0):
                    best = total
            if kind == ("event_msg", "user_message"):
                if now and prev:
                    human_gaps.append((now - prev).total_seconds() / 60)
                continue
            if kind == ("response_item", "message") and p.get("role") == "assistant":
                replies += 1
            if now and rec.get("type") in ("response_item", "event_msg") and kind != ("event_msg", "user_message"):
                if not (kind == ("response_item", "message") and p.get("role") == "user"):
                    prev = now
        tokens["input"] += best.get("input_tokens", 0) or 0
        tokens["cached"] += best.get("cached_input_tokens", 0) or 0
        tokens["output"] += best.get("output_tokens", 0) or 0
        tokens["reasoning"] += best.get("reasoning_output_tokens", 0) or 0
    stamps.sort()
    priced = [prices["models"][m] for m in models if m in prices["models"]]
    cost = None
    if len(models) == 1 and priced:
        pr = priced[0]
        cost = ((tokens["input"] - tokens["cached"]) * pr["input"] + tokens["cached"] * pr.get("cache_read", pr["input"])
                + tokens["output"] * pr["output"]) / 1_000_000
    human = sum(g for g in human_gaps if g <= PAUSE_MIN)
    return {"env": "codex", "models": sorted(models), "tokens": tokens, "replies": replies,
            "active_minutes": active_minutes(stamps), "human_minutes": human,
            "human_replies": sum(1 for g in human_gaps if g <= PAUSE_MIN),
            "wall_minutes": (stamps[-1] - stamps[0]).total_seconds() / 60 if len(stamps) > 1 else 0.0,
            "total_usd": cost, "prices_date": prices.get("date"), "usd_rub": prices.get("usd_rub")}


def report_codex(s):
    t = s["tokens"]
    lines = [f"Журнал Codex. Ответов модели: {s['replies']}; время по журналу среды: работа модели "
             f"{s['active_minutes'] - s['human_minutes']:.1f} мин, ожидание ответов человека {s['human_minutes']:.1f} мин "
             f"({s['human_replies']} сообщ.); всего {s['wall_minutes']:.1f} мин, паузы дольше {PAUSE_MIN} мин — перерыв и не считаются",
             (f"- {', '.join(s['models']) or 'модель не указана'}: ввод {t['input'] - t['cached']:,}, чтение из кэша {t['cached']:,}, "
              f"вывод {t['output']:,} токенов (из них рассуждения {t['reasoning']:,})").replace(",", " ")]
    if s["total_usd"] is None:
        lines.append("Цены для этой модели в tools/prices.json нет — расход в деньгах не посчитан; токены выше — точные "
                     "по журналу. Добавьте цену модели с датой и источником, чтобы получить сумму.")
    else:
        lines.append(f"Итого по прайс-листу на {s['prices_date']}: ${s['total_usd']:.2f}. Это цена через API по публичным "
                     "ценам, а не счёт подписки.")
    return "\n".join(lines)
