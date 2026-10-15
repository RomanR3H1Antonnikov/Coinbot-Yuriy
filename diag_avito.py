"""Avito diagnostics: run in the SAME terminal that runs the scraper. Writes logs/avito_diag.txt"""
import os, re, sys, time
from curl_cffi import requests as r

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "avito_diag.txt")
URL = "https://www.avito.ru/rossiya/kollektsionirovanie/monety-ASgBAgICAkSSA8YQ?q=%D0%B1%D1%80%D0%B0%D0%BA&s=104"
lines = []

def log(*a):
    s = " ".join(str(x) for x in a)
    print(s); lines.append(s)

def body_reason(text):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:300]

for u in ("https://api.ipify.org", "https://ipinfo.io/json"):
    try:
        log("ip-check", u, r.get(u, timeout=15).text[:300].replace("\n", " "))
    except Exception as e:
        log("ip-check fail", u, e)

for imp in ("chrome124", "chrome131", "firefox133", "safari17_0"):
    try:
        s = r.Session(impersonate=imp)
        h = s.get("https://www.avito.ru/", timeout=20)
        time.sleep(2)
        t = s.get(URL, timeout=20)
        log(f"[{imp}] home={h.status_code} listing={t.status_code} len={len(t.text)} "
            f"items={t.text.count('data-marker=\"item\"')} server={t.headers.get('server')} "
            f"retry-after={t.headers.get('retry-after')}")
        log("   reason:", body_reason(t.text))
    except Exception as e:
        log(f"[{imp}] ERROR {e}")
    time.sleep(3)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8").write("\n".join(lines))
log("saved:", OUT)
