import re
import logging

from pipeline.keyword_filter import build_matcher, lot_text

logger = logging.getLogger(__name__)

# Since 10.10 the client wants every keyword hit except cheap lots and repeats
# (no year / kopeck / multi-lot rules, no AI): extra circulation coins are better than lost ones.
_MIN_BUY_NOW_PRICE = 500


def _reject_reason(lot: dict, is_direct) -> str | None:
    if lot.get("sale_type") == "buy_now" and not is_direct(lot_text(lot)):
        price_val = _parse_price(lot.get("price", ""))
        if price_val is not None and 0 < price_val < _MIN_BUY_NOW_PRICE:
            return f"цена до {_MIN_BUY_NOW_PRICE} ₽ (купить сейчас)"
    return None


def pre_filter(lots: list[dict], keywords_direct: list[str],
               keywords_always: list[str] = (), rejected: list | None = None) -> list[dict]:
    """Drop cheap buy-now lots (unless a direct keyword is present).

    Rejected lots are appended to `rejected` as (lot, reason) when it is given.
    """
    is_direct = build_matcher(list(keywords_direct) + list(keywords_always))
    result = []

    for lot in lots:
        reason = _reject_reason(lot, is_direct)
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
