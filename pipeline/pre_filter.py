import re
import logging

from pipeline.keyword_filter import build_matcher, lot_text

logger = logging.getLogger(__name__)

_REJECT_WORDS = ["годовик"]
_REJECT_KOPEK = ["копеек", "копейка", "копейки"]
_MIN_BUY_NOW_PRICE = 500
_MULTILOT_MIN_COINS = 4
_MULTILOT_RE = re.compile(r"\bлот\w*\s+из\s+(\d+)")
_PILE_RE = re.compile(r"\bрос{1,2}ыпь")


def _reject_reason(lot: dict, is_always, is_price_exempt) -> str | None:
    title = (lot.get("title") or "").lower()

    m = _MULTILOT_RE.search(title)
    if (m and int(m.group(1)) >= _MULTILOT_MIN_COINS) or _PILE_RE.search(title):
        return "россыпь (лот из нескольких монет)"

    text = lot_text(lot)

    # The fixed-price floor also applies to otherwise unconditional keywords.
    if lot.get("sale_type") == "buy_now" and not is_price_exempt(text):
        price_val = _parse_price(lot.get("price", ""))
        if price_val is not None and price_val < _MIN_BUY_NOW_PRICE:
            return f"цена до {_MIN_BUY_NOW_PRICE} ₽ (купить сейчас)"

    if is_always(text):
        return None

    if any(w in title for w in _REJECT_WORDS):
        return "годовик"

    if any(k in title for k in _REJECT_KOPEK):
        return "копейки"

    return None


def pre_filter(lots: list[dict], keywords_direct: list[str],
               keywords_always: list[str] = (), rejected: list | None = None,
               price_exempt_keywords: list[str] = ()) -> list[dict]:
    """Drop lots that match rejection rules before the keyword pipeline.

    Rejected lots are appended to `rejected` as (lot, reason) when it is given.
    """
    is_always = build_matcher(keywords_always)
    is_price_exempt = build_matcher(price_exempt_keywords)
    result = []

    for lot in lots:
        reason = _reject_reason(lot, is_always, is_price_exempt)
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
    # Use only the first amount, so text like "350 ₽ за 1 шт" stays 350.
    amount = re.search(r"\d[\d\s\u00a0\u202f]*", price_str)
    digits = re.sub(r"\D", "", amount.group()) if amount else ""
    if digits:
        try:
            return int(digits)
        except ValueError:
            pass
    return None
