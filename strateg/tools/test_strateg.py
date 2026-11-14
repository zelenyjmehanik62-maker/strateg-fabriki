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
        self.assertIn("10 мин, 15.5 ₽", out)
        self.assertIn("по оценке, а не по счёту: 10 ₽", out)
        self.assertIn("Вмешательств человека: 1", out)


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
