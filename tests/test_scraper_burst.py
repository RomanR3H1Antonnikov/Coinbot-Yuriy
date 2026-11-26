import unittest
from unittest.mock import patch

import scraper_run


class ScraperBurstTests(unittest.TestCase):
    def test_large_batch_drains_over_two_runs_without_advancing_cursor_early(self):
        source = {"id": "meshok_yub_tir", "label": "Мешок", "url": "https://meshok.net/listing?good=14723"}
        lots = [
            {"lot_id": str(i), "source": source["id"], "source_label": source["label"],
             "url": f"https://meshok.net/item/{i}", "title": f"Брак монеты {i}",
             "description": "", "price": "700 ₽", "sale_type": "auction",
             "photo_url": None, "published_at": "2026-11-26T08:00:00+00:00"}
            for i in range(12)
        ]
        seen = set()

        def dedup(batch):
            seen.update(lot["lot_id"] for lot in batch)
            return batch

        with patch.object(scraper_run, "get_last_run_at", return_value="2026-11-26T07:00:00+00:00"), \
             patch.object(scraper_run, "note_viewed"), \
             patch.object(scraper_run, "is_seen", side_effect=lambda lot_id, _: lot_id in seen), \
             patch.object(scraper_run, "title_already_found", return_value=False), \
             patch.object(scraper_run, "save_rejected"), \
             patch.object(scraper_run, "dedup", side_effect=dedup), \
             patch.object(scraper_run, "send_alert", return_value=True) as send, \
             patch.object(scraper_run, "save_found_lot"), \
             patch.object(scraper_run, "set_last_run_at") as set_cursor, \
             patch.object(scraper_run.run_journal, "write"):
            scraper = type("Scraper", (), {"fetch_new_lots": lambda self, since: lots})()
            cfg = {"keywords": ["брак"], "keywords_direct": [], "keywords_always": []}
            scraper_run._run_source(source, scraper, cfg)
            self.assertEqual(send.call_count, 10)
            self.assertEqual(len(seen), 10)
            set_cursor.assert_not_called()

            scraper_run._run_source(source, scraper, cfg)
            self.assertEqual(send.call_count, 12)
            self.assertEqual(len(seen), 12)
            set_cursor.assert_called_once()


if __name__ == "__main__":
    unittest.main()
