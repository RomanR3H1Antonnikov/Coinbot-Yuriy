import re
import logging

from pipeline.keyword_filter import build_matcher, lot_text

logger = logging.getLogger(__name__)

_REJECT_WORDS = ["годовик"]
_REJECT_KOPEK = ["копеек", "копейка", "копейки"]
_CUTOFF_YEAR = 1965
_MIN_BUY_NOW_PRICE = 500
_MULTILOT_MIN_COINS = 4
_MULTILOT_RE = re.compile(r"\bлот\w*\s+из\s+(\d+)")
_PILE_RE = re.compile(r"\bрос{1,2}ыпь")


def _reject_reason(lot: dict, is_direct, is_always) -> str | None:
    title = (lot.get("title") or "").lower()

    m = _MULTILOT_RE.search(title)
    if (m and int(m.group(1)) >= _MULTILOT_MIN_COINS) or _PILE_RE.search(title):
        return "россыпь (лот из нескольких монет)"

    if is_always(lot_text(lot)):
        return None

    if any(w in title for w in _REJECT_WORDS):
        return "годовик"

    if any(k in title for k in _REJECT_KOPEK):
        return "копейки"

    # Denomination and year are usually in the first 60 chars of the title
    years = [int(y) for y in re.findall(r"\b(1[89]\d{2}|20[0-2]\d)\b", title[:60])]
    if years and min(years) < _CUTOFF_YEAR:
        return f"монета до {_CUTOFF_YEAR} г."

    if lot.get("sale_type") == "buy_now" and not is_direct(lot_text(lot)):
        price_val = _parse_price(lot.get("price", ""))
        if price_val is not None and 0 < price_val < _MIN_BUY_NOW_PRICE:
            return f"цена до {_MIN_BUY_NOW_PRICE} ₽ (купить сейчас)"

    return None


def pre_filter(lots: list[dict], keywords_direct: list[str],
               keywords_always: list[str] = (), rejected: list | None = None) -> list[dict]:
    """Drop lots that match rejection rules before keyword/LLM pipeline.

    Rejected lots are appended to `rejected` as (lot, reason) when it is given.
    """
    is_direct = build_matcher(keywords_direct)
    is_always = build_matcher(keywords_always)
    result = []

    for lot in lots:
        reason = _reject_reason(lot, is_direct, is_always)
        if reason is None:
            result.append(lot)
        elif rejected is not None:
            rejected.append((lot, reason))

    dropped = len(lots) - len(result)
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
