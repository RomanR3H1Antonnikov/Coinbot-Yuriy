import time
import logging
import os

from openai import OpenAI, RateLimitError, APIError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """Ты — фильтр нумизматических объявлений. Ответь ТОЛЬКО "YES" или "NO".
Тебе дают заголовок и (если есть) описание лота от продавца.

YES — если продавец заявляет, что у монеты есть производственный брак, дефект, ошибка чеканки или разновидность.
Достаточно, чтобы это было сказано в заголовке ИЛИ в описании, даже если вид брака не уточнён:
- общее заявление: «брак», «заводской брак», «производственный брак», «дефект», «ошибка чеканки»;
- конкретный брак: раскол штемпеля, смещение (в т.ч. вставки), мул, выкус, двойной удар, соударение,
  несоосность, непрочекан, инкуз, поворот, вне кольца, без гуртовой надписи, без краски, перечекан,
  чечевица, лунка, щель, заготовка, перепутка, гибрид, выкрошка, засор штемпеля, двоение, отсутствует плакировка;
- разновидность: задокументированная разновидность по штемпелю/гурту.

NO — если дефект не заявлен:
- только состояние (UNC, MS, Proof, слаб/slab, блеск) или оценка слаба (MS63, MS65 и т.п.);
- «нечастый», «редкий», «годовик» без заявления о браке или дефекте;
- ключевое слово употреблено в другом смысле (не про дефект монеты);
- явно сказано, что брака нет.

Примеры:
«Монета 10 рублей Брак!» → YES
«Менделеев выкрошка/засор редкий брак! 1 Рубль 1984» → YES
«10 рублей Пензенская область» + описание «вставка смещена вниз» → YES
«5 рублей 2012 UNC слаб MS65 редкая» → NO
«1 рубль 1965 UNC блеск отличное состояние, брака нет» → NO"""

_llm_calls = 0
_llm_tokens = 0


def llm_check(lot: dict) -> bool | None:
    global _llm_calls, _llm_tokens

    title = lot.get("title", "")
    description = (lot.get("description") or "")[:400]
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
            _llm_calls += 1
            usage = response.usage
            if usage:
                _llm_tokens += usage.total_tokens

            answer = response.choices[0].message.content.strip().upper()
            logger.debug("LLM [%s]: %s → %s", lot.get("lot_id"), title[:60], answer)
            return answer.startswith("YES")

        except RateLimitError:
            wait = 2 ** attempt * 5
            logger.warning("LLM RateLimitError, retry in %ds", wait)
            time.sleep(wait)
        except APIError as e:
            logger.error("LLM APIError: %s", e)
            time.sleep(2 ** attempt)

    logger.error("LLM failed after 3 attempts for lot %s", lot.get("lot_id"))
    return None  # unknown, not a "NO": the caller must not remember it as rejected


def get_llm_stats() -> dict:
    return {"calls": _llm_calls, "tokens": _llm_tokens}
