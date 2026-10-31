import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from pipeline.pre_filter import pre_filter
from scrapers.auction import AuctionScraper
from scrapers.avito import AvitoScraper
from scrapers.meshok import MeshokScraper


class PriceFilterTests(unittest.TestCase):
    def test_fixed_price_floor_and_variety_exception(self):
        def lot(title, price, sale_type):
            return {"title": title, "description": title, "price": price,
                    "sale_type": sale_type}

        cheap_fixed = lot("Брак смещение", "350 ₽", "buy_now")
        cheap_direct = lot("Перепутка монета", "10 ₽", "buy_now")
        cheap_always = lot("Гибрид монета", "90 ₽", "buy_now")
        variety = lot("Редкая разновидность", "250 ₽", "buy_now")
        auction = lot("Брак смещение", "1 ₽", "auction")
        hybrid_auction = lot("Брак смещение", "1 ₽", "auction")
        threshold = lot("Брак смещение", "500 ₽", "buy_now")
        absent = lot("Брак смещение", "", "buy_now")
        with_unit = lot("Брак смещение", "350 ₽ за 1 шт", "buy_now")
        free = lot("Брак смещение", "0 ₽", "buy_now")
        rejected = []
        kept = pre_filter([cheap_fixed, cheap_direct, cheap_always, variety, auction,
                           hybrid_auction, threshold, absent, with_unit, free],
                          ["перепутка", "разновидность"], ["гибрид"], rejected,
                          price_exempt_keywords=["разновидность"])
        self.assertEqual(kept, [variety, auction, hybrid_auction, threshold, absent])
        self.assertEqual(len(rejected), 5)
        self.assertTrue(all("500" in reason for _, reason in rejected))

    def test_meshok_api_sale_types(self):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return {"result": {"lots": [
                    {"id": 1, "beginDate": "2026-10-31T10:00:00Z",
                     "type": "fixedPrice", "price": 30, "title": "Брак"},
                    {"id": 2, "beginDate": "2026-10-31T10:00:00Z",
                     "type": "auction", "price": 1, "title": "Брак"},
                ]}}

        class Session:
            def post(self, *args, **kwargs):
                return Response()

        scraper = MeshokScraper("meshok_test", "Test", "https://meshok.net/listing?good=15190")
        scraper.max_pages = 1
        with patch.object(scraper, "_get_session", return_value=Session()), patch("scrapers.meshok.time.sleep"):
            lots = scraper._fetch_api(None)
        self.assertEqual([lot["sale_type"] for lot in lots], ["buy_now", "auction"])

    def test_auction_sale_types(self):
        cards = "".join(
            f'<div class="offers__item" data-id="{i}" data-saletype="{sale_type}">'
            f'<a class="offer_snippet__link" href="/offer/test-i{i}.html" aria-label="Брак"></a>'
            f'<div class="offer_snippet_body_price--value">1 a</div></div>'
            for i, sale_type in enumerate(("buynow", "auction", "auctionwithbuynow"), 100000000)
        )
        scraper = AuctionScraper("auction_test", "Test", "https://auction.ru/")
        lots = scraper._parse_page(BeautifulSoup(cards, "lxml"))
        self.assertEqual([lot["sale_type"] for lot in lots], ["buy_now", "auction", "auction"])

    def test_avito_cards_are_fixed_price(self):
        html = ('<div data-marker="item"><a data-marker="item-title" '
                'href="/moskva/kollektsionirovanie/brak_123456789">Брак</a>'
                '<span data-marker="item-price">350 ₽</span></div>')
        scraper = AvitoScraper("avito_test", "Test", "https://www.avito.ru/")
        lots = scraper._parse_page(BeautifulSoup(html, "lxml"))
        self.assertEqual(lots[0]["sale_type"], "buy_now")
        self.assertEqual(lots[0]["price"], "350 ₽")


if __name__ == "__main__":
    unittest.main()
