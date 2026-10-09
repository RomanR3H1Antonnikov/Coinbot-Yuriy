import logging
import os
import time

from openai import OpenAI, RateLimitError, APIError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """Ты определяешь тип российской/советской монеты по заголовку объявления.
Ответь ОДНИМ словом: JUB, CIRC или UNSURE.

JUB — юбилейная/памятная монета (выпущена ограниченным тиражом по теме):
- есть тема, событие, юбилей, личность, город, регион (область, республика, край, округ), спорт (Олимпиада, Универсиада, ЧМ),
  животные (Красная книга), серии (Города воинской славы, Красная книга, Сочи-2014, Крым, 70 лет Победы и т.п.);
- любые монеты из драгметаллов (серебро, золото, платина, палладий), «proof/пруф» наборы;
- СССР 1 рубль 1965–1991 гг. — юбилейные, даже если тема не названа в заголовке (Ленин, Циолковский, Маяковский,
  Бородино, Олимпиада-80 и др.), кроме лотов со словом «годовик»;
- 3, 25, 50, 100, 150 рублей и т.п. с темой;
- 10 рублей 2000–2016 гг. БИМЕТАЛЛ (кольцо и вставка разного цвета) — это всегда памятные серии, даже если тема не названа.

CIRC — тиражная (обиходная) монета, которой расплачиваются:
- стандартные 1, 2, 5, 10 рублей и 1, 5, 10, 50 копеек РФ без темы (только номинал, год, монетный двор ММД/СПМД/ЛМД/М/СП);
- стандартные 10 рублей 2009–2012 «Банк России», 5 рублей 1997–1998, 1992–1993 гг. номиналов 1–100 рублей без темы;
- СССР 1961 «годовик» и обиходные копейки/рубли без темы.

UNSURE — только если в заголовке нет ни темы, ни хотя бы номинала/года.

ГЛАВНОЕ ПРАВИЛО: если в заголовке есть название области/республики/края/округа/города, личность, событие, юбилей или серия —
это JUB, даже если номинал обычный (10 рублей) и даже если сказано «брак».
Признаки брака (смещение, поворот, раскол, выкус и т.п.) НЕ определяют тип. Определяй тип по теме/номиналу/металлу.

Примеры:
«10 рублей 2016 Амурская область UNC БРАК» → JUB
«10 рублей 2014 Тюменская область брак выкус» → JUB
«10 рублей 2015 70 лет Победы смещение» → JUB
«1 рубль 1987 Циолковский брак» → JUB
«10 рублей 2015 двоение брак биметалл» → JUB
«2 рубля 2012 Платов нарушение соосности» → JUB
«5 рублей 2011 ММД поворот 30 градусов» → CIRC
«5 рублей 1998 СПМД разновидность 2.4» → CIRC
«10 рублей 2011 ММД полный раскол реверса» → CIRC
«50 рублей 1993 ЛМД брак раскол» → CIRC
«1 рубль 2016 полный раскол штемпеля» → CIRC
«10 рублей непрочекан» → UNSURE"""

_calls = 0
_tokens = 0


def is_jubilee(lot: dict) -> bool:
    """True для JUB и UNSURE (юбилейку терять нельзя), False для CIRC."""
    global _calls, _tokens

    title = lot.get("title", "")
    description = (lot.get("description") or "")[:300]
    user_msg = f"Заголовок: {title}\nОписание: {description}"

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=5,
                temperature=0,
            )
            _calls += 1
            if response.usage:
                _tokens += response.usage.total_tokens
            answer = response.choices[0].message.content.strip().upper()
            logger.info("Jubilee [%s] %s → %s", lot.get("lot_id"), title[:60], answer)
            return not answer.startswith("CIRC")

        except RateLimitError:
            time.sleep(2 ** attempt * 5)
        except APIError as e:
            logger.error("Jubilee APIError: %s", e)
            time.sleep(2 ** attempt)

    logger.error("Jubilee check failed for lot %s — passing through", lot.get("lot_id"))
    return True


def get_jubilee_stats() -> dict:
    return {"calls": _calls, "tokens": _tokens}
