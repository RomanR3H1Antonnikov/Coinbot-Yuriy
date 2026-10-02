def keyword_filter(lots: list[dict], keywords: list[str]) -> list[dict]:
    kw_lower = [k.lower() for k in keywords]
    result = []
    for lot in lots:
        text = (
            (lot.get("title") or "") + " " + (lot.get("description") or "")
        ).lower()
        if any(kw in text for kw in kw_lower):
            result.append(lot)
    return result
