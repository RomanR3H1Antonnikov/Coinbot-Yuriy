import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scraper_run
from db import database
from utils import alert_queue


def lot(number: int) -> dict:
    return {
        "lot_id": str(number), "source": "meshok_yub_tir", "source_label": "Мешок",
        "url": f"https://meshok.net/item/{number}", "title": f"Брак монеты {number}",
        "description": "", "price": "700 ₽", "sale_type": "auction",
        "photo_url": None, "published_at": "2026-11-28T00:00:00+00:00",
    }


class ScraperBurstTests(unittest.TestCase):
    def test_large_batch_drains_over_two_runs_without_advancing_cursor_early(self):
        lots = [lot(i) for i in range(12)]
        source = {"id": "meshok_yub_tir", "label": "Мешок", "url": "https://meshok.net/listing?good=14723"}
        scraper = type("Scraper", (), {"fetch_new_lots": lambda self, since: lots})()
        cfg = {"keywords": ["брак"], "keywords_direct": [], "keywords_always": []}

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(database, "DB_PATH", str(Path(directory) / "test.db")), \
             patch.object(alert_queue, "_get_chat_ids", return_value=["user1", "user2"]), \
             patch.object(scraper_run, "send_alert", return_value=True) as send, \
             patch.object(scraper_run.run_journal, "write"):
            database.init_db()
            scraper_run._run_source(source, scraper, cfg)
            self.assertEqual(send.call_count, 20)
            with database.db_conn() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM found_lots").fetchone()[0], 10)
                self.assertEqual(conn.execute("SELECT count(*) FROM migration_alert_queue").fetchone()[0], 0)
                self.assertIsNone(conn.execute("SELECT last_run_at FROM run_state WHERE source=?", (source["id"],)).fetchone())

            scraper_run._run_source(source, scraper, cfg)
            self.assertEqual(send.call_count, 24)
            with database.db_conn() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM found_lots").fetchone()[0], 12)
                self.assertEqual(conn.execute("SELECT count(*) FROM migration_alert_queue").fetchone()[0], 0)
                self.assertIsNotNone(conn.execute("SELECT last_run_at FROM run_state WHERE source=?", (source["id"],)).fetchone())

    def test_failed_recipient_is_retried_without_duplicate_to_first_recipient(self):
        one_lot = lot(90)
        calls = []

        def sender(item, chat_id):
            calls.append(chat_id)
            return chat_id == "user1" or calls.count("user2") > 1

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(database, "DB_PATH", str(Path(directory) / "test.db")), \
             patch.object(alert_queue, "_get_chat_ids", return_value=["user1", "user2"]):
            database.init_db()
            alert_queue.enqueue([one_lot])
            self.assertEqual(alert_queue.drain(one_lot["source"], sender), [])
            with database.db_conn() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM found_lots").fetchone()[0], 0)

            completed = alert_queue.drain(one_lot["source"], sender)
            self.assertEqual([item["lot_id"] for item in completed], ["90"])
            self.assertEqual(calls, ["user1", "user2", "user2"])
            with database.db_conn() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM found_lots").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT count(*) FROM migration_alert_queue").fetchone()[0], 0)

    def test_avito_completed_delivery_is_synced_to_vps(self):
        item = {**lot(91), "source": "avito_test", "url": "https://www.avito.ru/item/91",
                "sale_type": "buy_now"}
        source = {"id": "avito_test", "label": "Авито", "url": "https://www.avito.ru"}
        scraper = type("Scraper", (), {"fetch_new_lots": lambda self, since: [item]})()

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(database, "DB_PATH", str(Path(directory) / "test.db")), \
             patch.object(alert_queue, "_get_chat_ids", return_value=["user1", "user2"]), \
             patch.object(scraper_run, "send_alert", return_value=True), \
             patch.object(scraper_run, "sync_to_vps") as sync, \
             patch.object(scraper_run.run_journal, "write"):
            database.init_db()
            scraper_run._run_source(source, scraper, {"keywords": ["брак"]})
            self.assertEqual(sync.call_count, 1)
            self.assertEqual([lot["lot_id"] for lot in sync.call_args.args[0]], ["91"])
            with database.db_conn() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM found_lots").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
