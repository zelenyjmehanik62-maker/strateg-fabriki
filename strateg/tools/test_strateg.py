"""Тесты скрипта strateg.py. Запуск: python3 -m unittest discover -s strateg/tools -p "test_*.py" """
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import strateg  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["STRATEG_PROJECTS"] = self.tmp.name
        self.p = Path(self.tmp.name) / "demo"
        self.run_ok("new", "demo")

    def tearDown(self):
        os.environ.pop("STRATEG_PROJECTS", None)
        self.tmp.cleanup()

    def run_cmd(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = strateg.main(list(argv))
        finally:
            sys.stdin = old_stdin
        return code, out.getvalue(), err.getvalue()

    def run_ok(self, *argv):
        code, out, err = self.run_cmd(*argv)
        self.assertEqual(code, 0, err + out)
        return out

    def source(self, kind="site", ref="https://example.ru/a"):
        return self.run_ok("source", "demo", "--kind", kind, "--title", "Источник", "--ref", ref).split()[0]

    def fact(self, text="Тариф стоит 299 ₽", sid=None, quote=None):
        sid = sid or self.source()
        return self.run_ok("claim", "demo", "--type", "fact", "--text", text,
                           "--source", f"{sid}:таблица тарифов", "--quote", quote or text).split()[0]

    def write(self, name, text):
        (self.p / name).write_text(text, encoding="utf-8")


class CliEncodingTests(Base):
    def cli(self, *argv):
        env = os.environ.copy()
        env.update(PYTHONUTF8="0", PYTHONIOENCODING="cp1251:strict")
        return subprocess.run(
            [sys.executable, "-X", "utf8=0", str(Path(strateg.__file__)), *argv],
            env=env, capture_output=True,
        )

    def test_cost_and_show_emit_utf8_under_cp1251(self):
        eid = self.fact(text="Тариф стоит 299 ₽; значок книги 📚")
        for argv, expected in [
            (("cost", "demo"), "₽"),
            (("show", "demo", eid), "Тариф стоит 299 ₽; значок книги 📚"),
        ]:
            with self.subTest(command=argv[0]):
                result = self.cli(*argv)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                self.assertIn(expected, result.stdout.decode("utf-8"))

    def test_error_output_is_utf8_under_cp1251(self):
        result = self.cli("status", "проект-₽-📚")
        self.assertEqual(result.returncode, 1)
        self.assertIn("проект-₽-📚", result.stderr.decode("utf-8"))
        self.assertNotIn(b"UnicodeEncodeError", result.stderr)

    def test_import_does_not_reconfigure_host_stream(self):
        env = os.environ.copy()
        env.update(PYTHONUTF8="0", PYTHONIOENCODING="cp1251:strict")
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(Path(strateg.__file__).parent)!r}); "
            "import strateg; print(sys.stdout.encoding)"
        )
        result = subprocess.run(
            [sys.executable, "-X", "utf8=0", "-c", code],
            env=env, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), b"cp1251")


class RegistryTests(Base):
    def test_new_creates_layout_and_refuses_duplicate(self):
        for name in ("brief.md", "state.json", "sources.jsonl", "evidence.jsonl", "journal.jsonl", "materials"):
            self.assertTrue((self.p / name).exists(), name)
        code, _, err = self.run_cmd("new", "demo")
        self.assertEqual(code, 1)
        self.assertIn("уже есть", err)

    def test_bad_project_name(self):
        code, _, _ = self.run_cmd("new", "Мой проект")
        self.assertEqual(code, 1)

    def test_source_is_not_added_twice(self):
        self.assertEqual(self.source(), "S-001")
        self.assertEqual(self.source(), "S-001")
        self.assertEqual(self.source(ref="https://example.ru/b"), "S-002")

    def test_fact_requires_source_and_place(self):
        code, _, err = self.run_cmd("claim", "demo", "--type", "fact", "--text", "Рынок растёт")
        self.assertEqual(code, 1)
        self.assertIn("факт без источника", err)
        sid = self.source()
        code, _, err = self.run_cmd("claim", "demo", "--type", "fact", "--text", "Рынок растёт", "--source", sid)
        self.assertEqual(code, 1)
        self.assertIn("место в источнике", err)
        self.assertEqual((self.p / "evidence.jsonl").read_text(encoding="utf-8"), "")

    def test_synthetic_source_cannot_support_fact(self):
        sid = self.source(kind="synthetic", ref="беседа с модельным респондентом 1")
        code, _, err = self.run_cmd("claim", "demo", "--type", "fact", "--text", "Людям это нужно",
                                    "--source", f"{sid}:ответ 3")
        self.assertEqual(code, 1)
        self.assertIn("синтетический источник", err)

    def test_unknown_source_rejected(self):
        code, _, err = self.run_cmd("claim", "demo", "--type", "fact", "--text", "x", "--source", "S-099:стр. 1")
        self.assertEqual(code, 1)
        self.assertIn("не найден", err)

    def test_supersede_marks_old_claim(self):
        sid = self.source()
        old = self.fact(sid=sid)
        new = self.run_ok("claim", "demo", "--type", "fact", "--text", "Тариф стоит 349 ₽",
                          "--source", f"{sid}:новая таблица", "--quote", "Тариф стоит 349 ₽",
                          "--supersedes", old).split()[0]
        rows = [json.loads(l) for l in (self.p / "evidence.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["status"], "superseded")
        self.assertEqual(rows[0]["superseded_by"], new)


class CheckTests(Base):
    def test_clean_project_passes(self):
        e = self.fact()
        self.write("findings.md", f"# Картина\n\nТариф конкурента — 299 ₽ [{e}].\n\n## Чего мы не знаем\n\nДолю рынка.\n")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 0, out)
        self.assertIn("Проверка пройдена", out)

    def test_reference_to_missing_and_revoked(self):
        e = self.fact()
        self.write("findings.md", f"Тариф 299 ₽ [{e}]. Доля 40% [E-777].\n\n## Чего мы не знаем\n\n—\n")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 1)
        self.assertIn("несуществующее E-777", out)
        self.run_ok("revoke", "demo", e, "--reason", "источник устарел")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertIn(f"отозванное {e}", out)

    def test_hypothesis_stated_as_fact(self):
        h = self.run_ok("claim", "demo", "--type", "hypothesis", "--text", "Пользователи уходят из-за цены").split()[0]
        self.write("findings.md", f"Пользователи уходят из-за цены [{h}].\n\n## Чего мы не знаем\n\n—\n")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 1)
        self.assertIn("поданы как факт", out)
        self.write("findings.md", f"Гипотеза: пользователи уходят из-за цены [{h}].\n\n## Чего мы не знаем\n\n—\n")
        self.assertEqual(self.run_cmd("check", "demo")[0], 0)

    def test_synthetic_must_be_named(self):
        sid = self.source(kind="synthetic", ref="беседа 1")
        s = self.run_ok("claim", "demo", "--type", "synthetic", "--text", "Не понимаю, за что плачу",
                        "--source", f"{sid}:ответ 2").split()[0]
        self.write("findings.md", f"Гипотеза: клиенты не понимают ценность [{s}].\n\n## Чего мы не знаем\n\n—\n")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 1)
        self.assertIn("не назван синтетическим", out)

    def test_findings_need_gaps_section(self):
        e = self.fact()
        self.write("findings.md", f"Тариф 299 ₽ [{e}].\n")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 1)
        self.assertIn("Чего мы не знаем", out)

    def test_options_rules(self):
        e = self.fact()
        self.write("options.md", f"## Вариант A. Снизить цену\n\nТариф 299 ₽ [{e}].\n\n## Вариант B. Новый тариф\n")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 1)
        self.assertIn("не меньше трёх", out)
        self.assertIn("оставить как есть", out)
        self.write("options.md", "## Вариант A. Оставить как есть\n\nВозражение: отток продолжится (вывод).\n\n"
                                 "## Вариант B. Новый тариф\n\n## Вариант C. Закрыть направление\n")
        self.assertEqual(self.run_cmd("check", "demo")[0], 0)

    def test_heading_may_name_hypothesis_and_list_numbers_are_not_figures(self):
        h = self.run_ok("claim", "demo", "--type", "hypothesis", "--text", "Цена — причина оттока").split()[0]
        self.write("verification.md", f"# План проверки\n\n## 1. Цена — причина оттока [{h}]\n\n"
                                      "1. Доход на клиента упадёт сильнее, чем вырастет база.\n")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 0, out)
        self.assertNotIn("цифра без ссылки", out)

    def test_done_without_next_sets_default_action(self):
        self.write("brief.md", "# Постановка\n\nПочему падает удержание?\n")
        self.run_ok("step", "demo", "--done", "frame")
        st = json.loads((self.p / "state.json").read_text(encoding="utf-8"))
        self.assertIn("skills/collect", st["next_action"])

    def test_number_without_reference_is_warning_only(self):
        self.write("strategy-product.md", "Мы ожидаем, что аудитория сервиса составит около 120 тысяч человек.\n")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 0)
        self.assertIn("цифра без ссылки", out)


class StateTests(Base):
    def test_step_done_blocked_by_check(self):
        code, _, err = self.run_cmd("step", "demo", "--done", "collect")
        self.assertEqual(code, 1)
        self.assertIn("не закрыт", err)
        self.assertEqual(json.loads((self.p / "state.json").read_text(encoding="utf-8"))["done"], [])

    def test_step_done_advances(self):
        self.write("brief.md", "# Постановка\n\nПочему падает удержание?\n")
        self.run_ok("step", "demo", "--done", "frame", "--next", "собрать материалы")
        st = json.loads((self.p / "state.json").read_text(encoding="utf-8"))
        self.assertEqual((st["step"], st["done"], st["next_action"]), ("collect", ["frame"], "собрать материалы"))

    def test_mode_is_saved_and_shown(self):
        self.assertIn("Режим: не выбран", self.run_ok("status", "demo"))
        self.run_ok("step", "demo", "--mode", "fast")
        self.assertIn("Режим: быстрый", self.run_ok("status", "demo"))

    def test_strategy_step_needs_summary(self):
        for name in ("strategy-product.md", "strategy-comms.md", "verification.md"):
            self.write(name, "# Документ\n\nТекст без цифр (вывод).\n")
        code, _, err = self.run_cmd("step", "demo", "--done", "strategy")
        self.assertEqual(code, 1)
        self.write("summary.md", "# Сводка\n\nКороткий итог (вывод).\n")
        self.run_ok("step", "demo", "--done", "strategy")

    def test_examples_listed_apart(self):
        import json as _j
        self.run_ok("new", "own")
        st = _j.loads((self.p / "state.json").read_text(encoding="utf-8"))
        st["example"] = "учебный пример"
        (self.p / "state.json").write_text(_j.dumps(st, ensure_ascii=False), encoding="utf-8")
        out = self.run_ok("status")
        self.assertIn("Готовые примеры", out)
        self.assertIn("- demo: учебный пример", out)
        self.assertLess(out.index("- own:"), out.index("Готовые примеры"))

    def test_done_clears_stale_waiting(self):
        self.write("brief.md", "# Постановка\n\nПочему падает удержание?\n")
        self.run_ok("step", "demo", "--waiting", "подтверждение постановки")
        self.run_ok("step", "demo", "--done", "frame")
        st = json.loads((self.p / "state.json").read_text(encoding="utf-8"))
        self.assertIsNone(st["waiting_for_user"])

    def test_reopen_keeps_history_and_decisions(self):
        self.write("brief.md", "# Постановка\n\nПочему падает удержание?\n")
        self.run_ok("step", "demo", "--done", "frame")
        self.run_ok("step", "demo", "--set", "options")
        st = json.loads((self.p / "state.json").read_text(encoding="utf-8"))
        st["done"] = ["frame", "collect", "research", "options"]
        (self.p / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        e = self.fact()
        self.run_ok("decide", "demo", "--text", "Вариант B", "--based-on", e)
        code, _, err = self.run_cmd("step", "demo", "--reopen", "research")
        self.assertEqual(code, 1)
        self.assertIn("--reason", err)
        out = self.run_ok("step", "demo", "--reopen", "research", "--reason", "бюджет уменьшен до 1 млн")
        self.assertIn("Исследование, Варианты", out)
        self.assertIn("остаются в силе", out)
        st = json.loads((self.p / "state.json").read_text(encoding="utf-8"))
        self.assertEqual((st["step"], st["done"]), ("research", ["frame", "collect"]))
        self.assertEqual(st["history"][-1]["done_before"], ["frame", "collect", "research", "options"])
        self.assertIn("бюджет уменьшен", self.run_ok("status", "demo"))
        decisions = (self.p / "decisions.jsonl").read_text(encoding="utf-8")
        self.assertIn('"status": "active"', decisions)

    def test_resume_shows_next_action(self):
        self.run_ok("step", "demo", "--next", "сопоставить S-001 и S-002 по ценам", "--waiting", "доступ к таблице")
        out = self.run_ok("status", "demo")
        self.assertIn("сопоставить S-001 и S-002 по ценам", out)
        self.assertIn("доступ к таблице", out)
        self.assertIn("demo", self.run_ok("status"))

    def test_log_key_prevents_repeat(self):
        self.run_ok("log", "demo", "--action", "скачан сайт", "--tool", "web", "--key", "fetch:a", "--minutes", "2",
                    "--cost", "3.5")
        out = self.run_ok("log", "demo", "--action", "скачан сайт", "--tool", "web", "--key", "fetch:a")
        self.assertIn("Уже выполнено", out)
        rows = (self.p / "journal.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 2)  # создание проекта + одно действие

    def test_failed_action_can_be_retried(self):
        self.run_ok("log", "demo", "--action", "скачать сайт", "--tool", "web", "--key", "fetch:b", "--result", "error")
        out = self.run_ok("log", "demo", "--action", "скачать сайт", "--tool", "web", "--key", "fetch:b")
        self.assertIn("Записано", out)

    def test_cost_summary(self):
        self.run_ok("log", "demo", "--action", "поиск", "--tool", "web", "--minutes", "4", "--cost", "10")
        self.run_ok("log", "demo", "--action", "разбор", "--tool", "llm", "--minutes", "6", "--cost", "5.5",
                    "--basis", "точно", "--human-help")
        out = self.run_ok("cost", "demo")
        self.assertIn("Время по оценке агента: 10 мин", out)
        self.assertIn("Расходы: 15.5 ₽ (измерено у 2 действий из 3)", out)
        self.assertIn("по оценке, а не по счёту: 10 ₽", out)
        self.assertIn("Вмешательств человека: 1", out)


    def test_unmeasured_cost_is_not_zero_and_clock_skips_pauses(self):
        self.run_ok("log", "demo", "--action", "поиск", "--tool", "web")
        out = self.run_ok("cost", "demo")
        self.assertIn("Расходы: расходы не измерены", out)
        self.assertIn("расходы не измерены", self.run_ok("status", "demo"))
        rows = [{"ts": "2026-11-14T10:00:00+03:00"}, {"ts": "2026-11-14T10:07:00+03:00"},
                {"ts": "2026-11-14T13:00:00+03:00"}, {"ts": "2026-11-14T13:05:00+03:00"}]
        self.assertEqual(strateg.clock_minutes(rows), 12)
        # ноль «по оценке» — не замер
        self.assertEqual(strateg.money_line([{"cost_rub": 0, "cost_basis": "оценка"}]), "расходы не измерены")
        self.assertEqual(strateg.money_line([{"cost_rub": 0, "cost_basis": "точно"}]), "0 ₽")


class ImpactTests(Base):
    def test_impact_follows_chain_to_decisions_and_text(self):
        e1 = self.fact()
        h = self.run_ok("claim", "demo", "--type", "hypothesis", "--text", "Цена — главный барьер",
                        "--based-on", e1).split()[0]
        d = self.run_ok("decide", "demo", "--text", "Запускаем дешёвый тариф", "--based-on", h,
                        "--owner", "руководитель продукта", "--review-if", "конверсия ниже 2%").split()[0]
        self.write("strategy-product.md", f"Предположительно цена — главный барьер [{h}].\n")
        out = self.run_ok("impact", "demo", e1)
        self.assertIn(h, out)
        self.assertIn(d, out)
        self.assertIn("strategy-product.md:1", out)

    def test_revoked_basis_flags_decision_and_dependents(self):
        e1 = self.fact()
        h = self.run_ok("claim", "demo", "--type", "hypothesis", "--text", "Цена — барьер", "--based-on", e1).split()[0]
        self.run_ok("decide", "demo", "--text", "Дешёвый тариф", "--based-on", e1)
        self.run_ok("revoke", "demo", e1, "--reason", "цена изменилась")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 1)
        self.assertIn(f"{h}: опирается на отозванное {e1}", out)
        self.assertIn("пора пересмотреть", out)

    def test_decision_needs_known_basis(self):
        code, _, err = self.run_cmd("decide", "demo", "--text", "x", "--based-on", "E-404")
        self.assertEqual(code, 1)
        self.assertIn("E-404", err)


class ReviewTests(Base):
    def test_review_flags_changed_basis_hypothesis_and_gaps(self):
        sid = self.source()
        e1 = self.fact(sid=sid)
        h = self.run_ok("claim", "demo", "--type", "hypothesis", "--text", "Цена — барьер").split()[0]
        d = self.run_ok("decide", "demo", "--text", "Дешёвый тариф", "--based-on", f"{e1},{h}",
                        "--review-if", "конверсия ниже 2%").split()[0]
        out = self.run_ok("review", "demo")
        self.assertIn("Стоит на гипотезах", out)
        self.assertEqual(out.count("опирается на непроверенные"), 1)
        self.assertIn("не указано — ответственный, показатель", out)
        self.assertIn("конверсия ниже 2%", out)
        self.assertNotIn("Решать сейчас", out)
        self.run_ok("claim", "demo", "--type", "fact", "--text", "Тариф стоит 349 ₽",
                    "--source", f"{sid}:новая таблица", "--quote", "Тариф стоит 349 ₽", "--supersedes", e1)
        out = self.run_ok("review", "demo")
        self.assertIn("Решать сейчас", out)
        self.assertIn(f"основание {e1} заменено на E-003", out)
        self.run_ok("decision", "demo", d, "--status", "revised", "--note", "цена конкурента выросла")
        self.assertNotIn("Решать сейчас", self.run_ok("review", "demo"))

    def test_review_flags_old_data(self):
        e1 = self.fact()
        self.run_ok("decide", "demo", "--text", "Дешёвый тариф", "--based-on", e1, "--owner", "РП",
                    "--metric", "удержание", "--review-if", "удержание < 25%")
        path = self.p / "sources.jsonl"
        row = json.loads(path.read_text(encoding="utf-8"))
        row["retrieved"] = "2026-01-01"
        path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        self.assertIn("Данные стареют", self.run_ok("review", "demo"))


def make_zip(path, files):
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


WNS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
SNS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


class ExtractTests(Base):
    def mat(self, name):
        return self.p / "materials" / name

    def out(self, name):
        return (self.p / "materials" / "_text" / name).read_text(encoding="utf-8")

    def test_docx_paragraphs_and_table(self):
        make_zip(self.mat("отчёт.docx"), {"word/document.xml": (
            f'<w:document {WNS}><w:body>'
            '<w:p><w:r><w:t>Удержание упало </w:t></w:r><w:r><w:t>на 5 п.п.</w:t></w:r></w:p>'
            '<w:p></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Месяц</w:t></w:r></w:p></w:tc>'
            '<w:tc><w:p><w:r><w:t>Отток</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            '<w:p><w:r><w:t>Вывод</w:t></w:r></w:p></w:body></w:document>')})
        self.run_ok("extract", "demo", "materials/отчёт.docx")
        text = self.out("отчёт.docx.txt")
        self.assertIn("[абз. 1] Удержание упало на 5 п.п.", text)
        self.assertIn("[таблица 1, строка 1] Месяц | Отток", text)
        self.assertIn("[абз. 2] Вывод", text)

    def test_xlsx_sheets_keep_row_and_column_positions(self):
        make_zip(self.mat("данные.xlsx"), {
            "xl/workbook.xml": f'<workbook {SNS} {RNS}><sheets><sheet name="Отток" sheetId="1" r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                          '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
            "xl/sharedStrings.xml": f'<sst {SNS}><si><t>Месяц</t></si><si><r><t>От</t></r><r><t>ток</t></r></si></sst>',
            "xl/worksheets/sheet1.xml": f'<worksheet {SNS}><sheetData>'
                                        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                                        '<row r="3"><c r="A3" t="inlineStr"><is><t>март</t></is></c><c r="C3"><v>4.5</v></c></row>'
                                        '</sheetData></worksheet>'})
        out = self.run_ok("extract", "demo", "materials/данные.xlsx")
        self.assertIn("лист «Отток»", out)
        self.assertEqual(self.out("данные.xlsx.лист1.csv").splitlines(), ["Месяц,Отток", "", "март,,4.5"])

    def test_html_drops_scripts(self):
        self.mat("сайт.html").write_text(
            "<html><head><title>Тарифы</title><script>var x='секрет';</script></head>"
            "<body><h1>Базовый</h1><p>299 &#8381; в месяц</p><table><tr><td>A</td><td>B</td></tr></table></body></html>",
            encoding="utf-8")
        self.run_ok("extract", "demo", "materials/сайт.html")
        text = self.out("сайт.html.txt")
        self.assertIn("299 ₽ в месяц", text)
        self.assertIn("A | B", text)
        self.assertNotIn("секрет", text)

    def test_csv_cp1251_semicolons(self):
        self.mat("выгрузка.csv").write_bytes("месяц;отток\nянварь;4,5\n".encode("cp1251"))
        self.run_ok("extract", "demo", "materials/выгрузка.csv")
        self.assertEqual(self.out("выгрузка.csv.csv").splitlines(), ["месяц,отток", 'январь,"4,5"'])

    def test_repeat_is_skipped_and_bad_files_reported(self):
        self.mat("a.txt").write_text("текст", encoding="utf-8")
        self.run_ok("extract", "demo", "materials/a.txt")
        self.assertIn("Уже разобран", self.run_ok("extract", "demo", "materials/a.txt"))
        self.mat("битый.docx").write_text("это не архив", encoding="utf-8")
        code, _, err = self.run_cmd("extract", "demo", "materials/битый.docx")
        self.assertEqual(code, 1)
        self.assertIn("повреждён", err)
        self.mat("фото.png").write_bytes(b"\x89PNG")
        code, _, err = self.run_cmd("extract", "demo", "materials/фото.png")
        self.assertEqual(code, 1)
        self.assertIn("не поддерживается", err)


def make_pdf(pages, encrypt=False):
    """Минимальный PDF: страница 1 — латиница простым шрифтом без сжатия,
    остальные — кириллица двухбайтовым шрифтом с ToUnicode, сжатие Flate."""
    import zlib
    objs = {}
    cyr = sorted({ch for t in pages[1:] for ch in t})
    code = {ch: i + 1 for i, ch in enumerate(cyr)}
    cmap = ("/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
            f"{len(cyr)} beginbfchar\n" + "".join(f"<{code[c]:04X}> <{ord(c):04X}>\n" for c in cyr)
            + "endbfchar\nendcmap end end").encode()
    objs[5] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objs[6] = b"<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H /ToUnicode 7 0 R >>"
    objs[7] = b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"\nendstream"
    kids = []
    for i, text in enumerate(pages):
        if i == 0:
            body = b"BT /F1 12 Tf 72 700 Td (" + text.encode("latin-1") + b") Tj ET"
            stream = b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream"
        else:
            lines = text.split("\n")
            parts = [b"BT /F2 12 Tf 1 0 0 1 72 700 Tm"]
            for j, line in enumerate(lines):
                if j:
                    parts.append(b"0 -14 Td")
                parts.append(b"<" + "".join(f"{code[c]:04X}" for c in line).encode() + b"> Tj")
            parts.append(b"ET")
            comp = zlib.compress(b"\n".join(parts))
            stream = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(comp) + comp + b"\nendstream"
        cn, pn = 10 + 2 * i, 11 + 2 * i
        objs[cn] = stream
        objs[pn] = b"<< /Type /Page /Parent 2 0 R /Contents %d 0 R >>" % cn
        kids.append(b"%d 0 R" % pn)
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = (b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count %d /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>"
               % len(kids))
    out = b"%PDF-1.4\n" + b"".join(b"%d 0 obj\n" % n + body + b"\nendobj\n" for n, body in sorted(objs.items()))
    out += b"trailer\n<< /Root 1 0 R" + (b" /Encrypt 99 0 R" if encrypt else b"") + b" >>\n%%EOF\n"
    return out


class PdfTests(Base):
    def test_pdf_pages_cyrillic_and_quote(self):
        (self.p / "materials" / "отчёт.pdf").write_bytes(make_pdf(["Market report 2026", "Отток 4,5% в марте\nДоля оплативших 22%"]))
        out = self.run_ok("extract", "demo", "materials/отчёт.pdf")
        self.assertIn("страниц 2", out)
        text = (self.p / "materials" / "_text" / "отчёт.pdf.txt").read_text(encoding="utf-8")
        self.assertIn("[стр. 1]\nMarket report 2026", text)
        self.assertIn("[стр. 2]\nОтток 4,5% в марте\nДоля оплативших 22%", text)
        sid = self.run_ok("source", "demo", "--kind", "doc", "--title", "Отчёт", "--ref", "materials/отчёт.pdf",
                          "--local", "materials/отчёт.pdf").split()[0]
        self.run_ok("claim", "demo", "--type", "fact", "--text", "Доля оплативших 22%",
                    "--source", f"{sid}:стр. 2", "--quote", "Доля оплативших 22%")

    def test_pdf_without_text_and_encrypted(self):
        (self.p / "materials" / "скан.pdf").write_bytes(make_pdf([""]))
        out = self.run_ok("extract", "demo", "materials/скан.pdf")
        self.assertIn("похоже на скан", out)
        (self.p / "materials" / "закрытый.pdf").write_bytes(make_pdf(["Secret"], encrypt=True))
        code, _, err = self.run_cmd("extract", "demo", "materials/закрытый.pdf")
        self.assertEqual(code, 1)
        self.assertIn("зашифрован", err)


class FindTests(Base):
    def test_find_matches_word_forms_and_show_links(self):
        e1 = self.fact(text="Удержание 30-го дня упало до 22%")
        h = self.run_ok("claim", "demo", "--type", "hypothesis", "--text", "Причина оттока — цена",
                        "--based-on", e1).split()[0]
        out = self.run_ok("find", "demo", "удержания")
        self.assertIn(e1, out)
        self.assertNotIn(h, out)
        self.assertIn("Ничего не найдено", self.run_ok("find", "demo", "логистика"))
        out = self.run_ok("show", "demo", e1)
        self.assertIn("место: таблица тарифов", out)
        self.assertIn(h, out)
        self.assertIn(e1, self.run_ok("show", "demo", "S-001"))
        code, _, _ = self.run_cmd("show", "demo", "E-404")
        self.assertEqual(code, 1)

    def test_find_in_files(self):
        self.write("findings.md", "Конкуренты снижают цены (вывод).\n\n## Чего мы не знаем\n\n—\n")
        self.assertIn("findings.md:1", self.run_ok("find", "demo", "конкурент", "--files"))
        self.assertIn("Ничего не найдено", self.run_ok("find", "demo", "конкурент"))


class GroundingTests(Base):
    """T24: факт должен опираться на дословную цитату, а критичный — пройти смысловую сверку."""

    def doc_source(self, text, name="source.md"):
        (self.p / "materials" / name).write_text(text, encoding="utf-8")
        return self.run_ok("source", "demo", "--kind", "doc", "--title", "Документ", "--ref",
                           f"materials/{name}", "--local", f"materials/{name}").split()[0]

    def test_fact_without_quote_is_rejected(self):
        sid = self.doc_source("Отток составил 4,5% в месяц в марте 2026 года.\n")
        code, _, err = self.run_cmd("claim", "demo", "--type", "fact", "--text", "Отток 4,5% в месяц",
                                    "--source", f"{sid}:строка 1")
        self.assertEqual(code, 1)
        self.assertIn("дословной цитатой", err)

    def test_quote_must_be_found_in_source(self):
        sid = self.doc_source("Отток составил 4,5% в месяц в марте 2026 года.\n")
        code, _, err = self.run_cmd("claim", "demo", "--type", "fact", "--text", "Отток 6% в месяц",
                                    "--source", f"{sid}:строка 1", "--quote", "Отток составил 6% в месяц")
        self.assertEqual(code, 1)
        self.assertIn("не найдена в тексте источника", err)
        # пробелы, регистр, кавычки и ё не мешают найти настоящий фрагмент
        out = self.run_ok("claim", "demo", "--type", "fact", "--text", "Отток в марте 2026 — 4,5% в месяц",
                          "--source", f"{sid}:строка 1", "--quote", "отток  составил 4,5 % в месяц в МАРТЕ 2026")
        self.assertTrue(out.startswith("E-"))

    def test_number_absent_from_quote_is_rejected(self):
        sid = self.doc_source("Выручка выросла, но точных цифр в отчёте нет. Подписчиков около 31 тысячи.\n")
        code, _, err = self.run_cmd("claim", "demo", "--type", "fact", "--text", "Подписчиков 45 тысяч",
                                    "--source", f"{sid}:абз. 1", "--quote", "Подписчиков около 31 тысячи")
        self.assertEqual(code, 1)
        self.assertIn("числа 45", err)

    def test_quote_found_in_extracted_table(self):
        (self.p / "materials" / "data.csv").write_text("канал;пробные;оплатили\nкупоны;7300;803\n", encoding="utf-8")
        self.run_ok("extract", "demo", "materials/data.csv")
        sid = self.run_ok("source", "demo", "--kind", "table", "--title", "Каналы", "--ref", "materials/data.csv",
                          "--local", "materials/data.csv").split()[0]
        out = self.run_ok("claim", "demo", "--type", "fact", "--text", "Купоны: 7300 пробных, 803 оплатили",
                          "--source", f"{sid}:строка 2", "--quote", "купоны 7300 803")
        self.assertTrue(out.startswith("E-"))

    def test_calc_supports_computed_number(self):
        sid = self.doc_source("купоны: 7300 пробных, 803 оплатили\n")
        (self.p / "calc").mkdir()
        (self.p / "calc" / "out.txt").write_text("доля оплативших у купонов: 11.0%\n", encoding="utf-8")
        code, _, err = self.run_cmd("claim", "demo", "--type", "fact", "--text", "У купонов платят 11% пробных",
                                    "--source", f"{sid}:строка 1", "--calc", "calc/missing.txt")
        self.assertEqual(code, 1)
        self.assertIn("не найден", err)
        self.run_ok("claim", "demo", "--type", "fact", "--text", "У купонов платят 11% пробных",
                    "--source", f"{sid}:строка 1", "--calc", "calc/out.txt")

    def test_user_words_need_no_quote(self):
        sid = self.run_ok("source", "demo", "--kind", "user", "--title", "Слова руководителя",
                          "--ref", "беседа").split()[0]
        self.run_ok("claim", "demo", "--type", "fact", "--text", "Бюджет — 3 млн ₽", "--source", f"{sid}:ответ 2")
        e = "E-001"
        self.write("options.md", f"## Вариант A. Оставить как есть\n\nБюджет 3 млн [{e}].\n\nВозражение: мало (вывод).\n\n"
                                 "## Вариант B. Рост\n\n## Вариант C. Закрыть направление\n")
        self.assertIn("Все критичные факты сверены", self.run_ok("vet", "demo"))

    def test_nika_probe_true_quote_false_meaning(self):
        """Опыт Ники (docs/review/check_snapshot.py): источник прямо говорит, что данных нет."""
        sid = self.doc_source("Учебный источник. Размер рынка неизвестен. Данных о 900 млрд рублей здесь нет.\n")
        # выдумать цитату нельзя
        code, _, err = self.run_cmd("claim", "demo", "--type", "fact", "--text", "Размер рынка составляет 900 млрд рублей",
                                    "--source", f"{sid}:строка 1", "--quote", "Размер рынка составляет 900 млрд рублей")
        self.assertEqual(code, 1)
        # настоящая цитата с тем же числом механически проходит — смысл противоположный
        e = self.run_ok("claim", "demo", "--type", "fact", "--text", "Размер рынка составляет 900 млрд рублей",
                        "--source", f"{sid}:строка 1", "--quote", "Данных о 900 млрд рублей здесь нет").split()[0]
        self.write("options.md", f"## Вариант A. Оставить как есть\n\nРынок 900 млрд рублей [{e}].\n\nВозражение: нет (вывод).\n\n"
                                 "## Вариант B. Рост\n\n## Вариант C. Закрыть направление\n")
        # пока факт критичный и не сверен, шаг «Варианты» не закрывается
        self.run_ok("step", "demo", "--set", "options")
        code, out, err = self.run_cmd("step", "demo", "--done", "options")
        self.assertEqual(code, 1)
        self.assertIn("не прошёл смысловую сверку", out)
        self.assertIn(e, self.run_ok("vet", "demo"))
        # сверка находит противоречие — и проверка не пропустит факт, пока его не отзовут
        code, _, err = self.run_cmd("vet", "demo", e, "--verdict", "no")
        self.assertEqual(code, 1)
        self.assertIn("--note", err)
        self.run_ok("vet", "demo", e, "--verdict", "no", "--by", "helper", "--note", "источник говорит, что данных нет")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 1)
        self.assertIn("не подтверждает факт", out)
        self.run_ok("revoke", "demo", e, "--reason", "источник не подтверждает")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertIn(f"ссылка на отозванное {e}", out)

    def test_vetted_critical_fact_lets_step_close(self):
        sid = self.doc_source("Отток составил 4,5% в месяц в марте 2026 года.\n")
        e = self.run_ok("claim", "demo", "--type", "fact", "--text", "Отток 4,5% в месяц, март 2026",
                        "--source", f"{sid}:строка 1", "--quote", "Отток составил 4,5% в месяц в марте 2026").split()[0]
        self.write("options.md", f"## Вариант A. Оставить как есть\n\nОтток 4,5% [{e}].\n\nВозражение: растёт (вывод).\n\n"
                                 "## Вариант B. Рост\n\n## Вариант C. Закрыть направление\n")
        self.run_ok("step", "demo", "--set", "options")
        self.run_ok("vet", "demo", e, "--verdict", "supports", "--by", "helper")
        self.run_ok("step", "demo", "--done", "options")
        self.assertIn("Смысловая сверка: подтверждает", self.run_ok("show", "demo", e))
        self.assertIn("Все критичные факты сверены", self.run_ok("vet", "demo"))

    def test_changed_source_breaks_quote(self):
        sid = self.doc_source("Отток составил 4,5% в месяц.\n")
        self.run_ok("claim", "demo", "--type", "fact", "--text", "Отток 4,5% в месяц",
                    "--source", f"{sid}:строка 1", "--quote", "Отток составил 4,5% в месяц")
        self.assertEqual(self.run_cmd("check", "demo")[0], 0)
        (self.p / "materials" / "source.md").write_text("Отток составил 6% в месяц.\n", encoding="utf-8")
        code, out, _ = self.run_cmd("check", "demo")
        self.assertEqual(code, 1)
        self.assertIn("цитата не найдена", out)


class UsageTests(Base):
    """T27: расход по журналу Claude Code считается по прайс-листу и не путается с нулём."""

    def transcript(self, rows):
        path = self.p / "session.jsonl"
        lines = []
        for i, (model, usage, ts) in enumerate(rows):
            lines.append(json.dumps({"type": "assistant", "timestamp": ts,
                                     "message": {"id": f"m{i // 2 if model == 'dup' else i}", "model": model, "usage": usage}}))
        path.write_text("\n".join(lines) + "\nне json\n", encoding="utf-8")
        return path

    def test_usage_prices_cache_search_and_dedup(self):
        u = {"input_tokens": 1000, "cache_creation_input_tokens": 10000,
             "cache_creation": {"ephemeral_5m_input_tokens": 10000, "ephemeral_1h_input_tokens": 0},
             "cache_read_input_tokens": 100000, "output_tokens": 2000, "server_tool_use": {"web_search_requests": 3}}
        path = self.transcript([("claude-opus-5-5", u, "2026-11-16T10:00:00Z"),
                                ("claude-opus-5-5", u, "2026-11-16T10:05:00Z")])
        import usage as us
        s = us.summarize([path])
        # (1000*4 + 10000*4*1.25 + 100000*0.2 + 2000*20)/1e6 + 3*10/1000 = 0.004+0.05+0.02+0.04+0.03 = 0.144 за ответ
        self.assertAlmostEqual(s["total_usd"], 0.288, places=6)
        self.assertEqual(s["responses"], 2)
        self.assertAlmostEqual(s["active_minutes"], 5.0)

    def test_usage_same_response_counted_once_and_haiku_long_prompt(self):
        small = {"input_tokens": 50000, "cache_read_input_tokens": 0, "output_tokens": 1000}
        big = {"input_tokens": 150000, "cache_read_input_tokens": 0, "output_tokens": 1000}
        path = self.transcript([("claude-haiku-5-5", small, "2026-11-16T10:00:00Z"),
                                ("claude-haiku-5-5", big, "2026-11-16T10:01:00Z")])
        import usage as us
        s = us.summarize([path])
        # 50000*0.10 + 1000*0.50 = 0.0055; длинный: 150000*0.50 + 1000*2.50 = 0.0775
        self.assertAlmostEqual(s["total_usd"], 0.083, places=6)

    def test_usage_unknown_model_and_project_log(self):
        u = {"input_tokens": 1000, "output_tokens": 1000}
        path = self.transcript([("claude-unknown-9", u, "2026-11-16T10:00:00Z"),
                                ("claude-sonnet-5-5", u, "2026-11-16T10:02:00Z")])
        out = self.run_ok("usage", str(path), "--project", "demo")
        self.assertIn("Нет цены для моделей: claude-unknown-9", out)
        self.assertIn("$0.01", out)
        self.assertIn("по прайс-листу $0.01", self.run_ok("cost", "demo"))
        self.assertEqual(self.run_cmd("usage", str(self.p / "нет.jsonl"))[0], 1)


class HookTests(Base):
    def payload(self, name):
        return json.dumps({"tool_input": {"file_path": str(self.p / name)}})

    def test_hook_blocks_bad_result_file(self):
        self.write("findings.md", "Доля рынка 40% [E-777].\n\n## Чего мы не знаем\n\n—\n")
        code, _, err = self.run_cmd("hook-edit", stdin=self.payload("findings.md"))
        self.assertEqual(code, 2)
        self.assertIn("E-777", err)

    def test_hook_ignores_other_files(self):
        self.assertEqual(self.run_cmd("hook-edit", stdin=self.payload("brief.md"))[0], 0)
        self.assertEqual(self.run_cmd("hook-edit", stdin="не json")[0], 0)


if __name__ == "__main__":
    unittest.main()
