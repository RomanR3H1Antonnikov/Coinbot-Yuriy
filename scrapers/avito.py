from scrapers.base import BaseScraper


class AvitoScraper(BaseScraper):
    def fetch_new_lots(self, since: str | None = None) -> list[dict]:
        raise NotImplementedError("Avito scraper — этап 3")
