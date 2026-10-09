import re

_WORD_CHARS = "а-яёa-z0-9"


def build_matcher(keywords):
    """Return matches(text) -> bool for lowercase text.

    A keyword matches as a word start with an optional short inflection ending
    (браком, соосности), so "мул" does not match "мультипликация".
    """
    patterns = []
    for k in keywords:
        k = k.strip().lower()
        if not k:
            continue
        if len(k) >= 6 and k[-1] in "ьйаяое":
            k = k[:-1]
        stem = r"\s+".join(re.escape(part) for part in k.split())
        max_suffix = 1 if len(k) <= 3 else 4
        patterns.append(re.compile(
            rf"(?<![{_WORD_CHARS}]){stem}[а-яё]{{0,{max_suffix}}}(?![{_WORD_CHARS}])"
        ))

    def matches(text: str) -> bool:
        return any(p.search(text) for p in patterns)

    return matches


def lot_text(lot: dict) -> str:
    return ((lot.get("title") or "") + " " + (lot.get("description") or "")).lower()


def keyword_filter(lots: list[dict], keywords: list[str]) -> list[dict]:
    matches = build_matcher(keywords)
    return [lot for lot in lots if matches(lot_text(lot))]
