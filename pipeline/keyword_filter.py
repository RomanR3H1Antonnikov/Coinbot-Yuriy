import re

_WORD_CHARS = "а-яёa-z0-9"


def _pattern(k: str):
    k = k.strip().lower()
    if not k:
        return None
    if len(k) >= 6 and k[-1] in "ьйаяое":
        k = k[:-1]
    stem = r"\s+".join(re.escape(part) for part in k.split())
    max_suffix = 1 if len(k) <= 3 else 4
    return re.compile(rf"(?<![{_WORD_CHARS}]){stem}[а-яё]{{0,{max_suffix}}}(?![{_WORD_CHARS}])")


def matched_keywords(lot: dict, keywords) -> list[str]:
    """Keywords that fired for a lot; one found only in the description is marked "(в описании)"."""
    title = (lot.get("title") or "").lower()
    text = lot_text(lot)
    found = []
    for k in dict.fromkeys(k.strip() for k in keywords if k.strip()):
        p = _pattern(k)
        if p is None:
            continue
        if p.search(title):
            found.append(k)
        elif p.search(text):
            found.append(f"{k} (в описании)")
    return found


def build_matcher(keywords):
    """Return matches(text) -> bool for lowercase text.

    A keyword matches as a word start with an optional short inflection ending
    (браком, соосности), so "мул" does not match "мультипликация".
    """
    patterns = [p for p in (_pattern(k) for k in keywords) if p is not None]

    def matches(text: str) -> bool:
        return any(p.search(text) for p in patterns)

    return matches


def lot_text(lot: dict) -> str:
    return ((lot.get("title") or "") + " " + (lot.get("description") or "")).lower()


def keyword_filter(lots: list[dict], keywords: list[str]) -> list[dict]:
    matches = build_matcher(keywords)
    return [lot for lot in lots if matches(lot_text(lot))]
