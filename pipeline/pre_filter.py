import re
import logging

logger = logging.getLogger(__name__)

_REJECT_WORDS = ["годовик"]
_REJECT_KOPEK = ["копеек", "копейка", "копейки"]
_CUTOFF_YEAR = 1965
_MIN_BUY_NOW_PRICE = 500


def pre_filter(lots: list[dict], keywords_direct: list[str]) -> list[dict]:
    """Drop lots that match rejection rules before keyword/LLM pipeline."""
    direct_set = {k.lower() for k in keywords_direct}
    result = []
    dropped = 0

    for lot in lots:
        title = (lot.get("title") or "").lower()

        # Reject lots with "годовик"
        if any(w in title for w in _REJECT_WORDS):
            dropped += 1
            continue

        # Reject kopek-denomination coins
        if any(k in title for k in _REJECT_KOPEK):
            dropped += 1
            continue

        # Reject coins minted before 1965
        # Look in first 60 chars where denomination+year usually appears
        early_text = title[:60]
        years = [int(y) for y in re.findall(r"\b(1[89]\d{2}|20[0-2]\d)\b", early_text)]
        if years and min(years) < _CUTOFF_YEAR:
            dropped += 1
            continue

        # Price filter: reject cheap "buy now" lots that aren't direct-keyword matches
        text = title + " " + (lot.get("description") or "").lower()
        is_direct_match = any(k in text for k in direct_set)

        if not is_direct_match and lot.get("sale_type") == "buy_now":
            price_val = _parse_price(lot.get("price", ""))
            if price_val is not None and 0 < price_val < _MIN_BUY_NOW_PRICE:
                dropped += 1
                continue

        result.append(lot)

    if dropped:
        logger.debug("pre_filter: dropped %d lots", dropped)
    return result


def _parse_price(price_str: str) -> int | None:
    if not price_str:
        return None
    digits = re.sub(r"[^\d]", "", price_str)
    if digits:
        try:
            return int(digits)
        except ValueError:
            pass
    return None
