from abc import ABC, abstractmethod


class BaseScraper(ABC):
    def __init__(self, source_id: str, label: str, url: str):
        self.source_id = source_id
        self.label = label
        self.url = url

    @abstractmethod
    def fetch_new_lots(self, since: str | None = None) -> list[dict]:
        """
        Fetch lots newer than `since` (ISO datetime string or None for all).
        Returns list of dicts with keys:
          lot_id, source, source_label, url, title, price, photo_url, description, published_at
        """
        ...
