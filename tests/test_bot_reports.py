import asyncio
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bot import reporting
from db import database


class ReportDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(database, "DB_PATH", str(Path(self.tmp.name) / "test.db"))
        self.base_patch = patch.object(reporting, "BASE_DIR", self.tmp.name)
        self.db_patch.start()
        self.base_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.base_patch.stop)
        database.init_db()

    def test_stats_and_important_lots_use_last_24_hours(self):
        cfg = {"keywords_direct": ["перепутка", "разновидность"],
               "keywords_always": ["гибрид"]}
        with database.db_conn() as conn:
            conn.execute("INSERT INTO found_lots (lot_id, source, url, title, price) "
                         "VALUES ('1', 'meshok_braki', 'https://example.test/1', 'Гибрид 10 рублей', '1000 ₽')")
            conn.execute("INSERT INTO found_lots (lot_id, source, url, title, price) "
                         "VALUES ('2', 'auction_5rub', 'https://example.test/2', 'Перепутка 5 рублей', '2000 ₽')")
            conn.execute("INSERT INTO found_lots (lot_id, source, url, title, price) "
                         "VALUES ('3', 'avito_brak', 'https://example.test/3', 'Брак рубля', '600 ₽')")
            conn.execute("INSERT INTO found_lots (lot_id, source, url, title, price, found_at) "
                         "VALUES ('old', 'meshok_braki', 'https://example.test/old', 'Гибрид старый', '1000 ₽', "
                         "datetime('now', '-2 days'))")
            conn.execute("INSERT INTO rejected_lots (lot_id, source, stage) VALUES ('4', 'meshok_braki', 'rules')")
            conn.execute("INSERT INTO run_state (source, last_run_at) VALUES "
                         "('meshok_braki', '2026-11-26T10:00:00+00:00')")
        database.note_viewed("meshok", ["1", "4"])
        path = Path(self.tmp.name) / "logs"
        path.mkdir()
        (path / "avito_stats.json").write_text(json.dumps({"viewed": 8, "ts": "2026-11-26T10:00:00+00:00"}),
                                                encoding="utf-8")

        important = reporting.important_found(cfg)
        self.assertEqual([lot["lot_id"] for lot in important], ["1", "2"])
        self.assertEqual(important[0]["important_keywords"], ["гибрид"])
        text = reporting.stats_text(cfg)
        self.assertIn("Мешок</b>: просмотрено новых 2, отправлено 1, отсеяно 1, важных 1", text)
        self.assertIn("Аукцион</b>: просмотрено новых 0, отправлено 1, отсеяно 0, важных 1", text)
        self.assertIn("Авито</b>: просмотрено новых 8, отправлено 1, отсеяно 0, важных 0", text)


class ReportCommandTests(unittest.TestCase):
    @unittest.skipIf(importlib.util.find_spec("aiogram") is None, "aiogram is installed on the VPS")
    def test_report_command_sends_generated_audit(self):
        from bot.handlers import cmd_report

        class Message:
            chat = SimpleNamespace(id=1049170524)
            replies = []

            async def answer(self, text, **kwargs):
                self.replies.append(text)

        message = Message()
        with patch("bot.handlers._get_chat_ids", return_value=["1049170524"]), \
             patch("bot.handlers.load_config", return_value={}), \
             patch("audit_run.audit", return_value=("📊 <b>Сверка за 24 ч</b>\nМешок: 2", 0)):
            asyncio.run(cmd_report(message))
        self.assertTrue(any("Сверка за 24 ч" in text for text in message.replies))


if __name__ == "__main__":
    unittest.main()
