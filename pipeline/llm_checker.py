import time
import logging
import os

from openai import OpenAI, RateLimitError, APIError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """Ты — фильтр нумизматических объявлений.
Ответь ТОЛЬКО "YES" или "NO".
Объявление РЕЛЕВАНТНО, если оно касается монеты СССР или России с браком чеканки,
разновидностью, перепуткой, смещением или другим нумизматическим дефектом/особенностью."""

_llm_calls = 0
_llm_tokens = 0


def llm_check(lot: dict) -> bool:
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
    return False


def get_llm_stats() -> dict:
    return {"calls": _llm_calls, "tokens": _llm_tokens}
