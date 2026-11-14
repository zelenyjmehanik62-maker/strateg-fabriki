"""Тесты скрипта strateg.py. Запуск: python3 -m unittest discover -s strateg/tools -p "test_*.py" """
import contextlib
import io
import json
import os
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

    def fact(self, text="Тариф стоит 299 ₽", sid=None):
        sid = sid or self.source()
        return self.run_ok("claim", "demo", "--type", "fact", "--text", text,
                           "--source", f"{sid}:таблица тарифов").split()[0]

    def write(self, name, text):
        (self.p / name).write_text(text, encoding="utf-8")


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
                          "--source", f"{sid}:новая таблица", "--supersedes", old).split()[0]
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
                    "--source", f"{sid}:новая таблица", "--supersedes", e1)
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
