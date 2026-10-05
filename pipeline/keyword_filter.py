import re


def keyword_filter(lots: list[dict], keywords: list[str]) -> list[dict]:
    # Compile word-boundary patterns to avoid substring false matches
    # e.g. "мул" won't match "мультипликация"
    patterns = [re.compile(r"\b" + re.escape(k.lower()) + r"\b") for k in keywords]
    result = []
    for lot in lots:
        text = (
            (lot.get("title") or "") + " " + (lot.get("description") or "")
        ).lower()
        if any(p.search(text) for p in patterns):
            result.append(lot)
    return result
