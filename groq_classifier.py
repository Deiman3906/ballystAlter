"""
Groq классификатор угроз с ротацией ключей
"""

import asyncio
import logging
import itertools
from groq import AsyncGroq

import config

log = logging.getLogger(__name__)

# Бесконечная ротация ключей по кругу
_key_cycle = itertools.cycle(config.GROQ_KEYS)

SYSTEM_PROMPT = """Ти — система раннього оповіщення про балістичні загрози в Україні.

Твоя задача: визначити чи містить повідомлення інформацію про РЕАЛЬНУ балістичну загрозу прямо зараз.

Відповідай ТІЛЬКИ одним словом:
- THREAT — якщо є реальна загроза (балістика летить, ракетний удар, пуск ракет зараз)
- SAFE — якщо це новини, аналітика, минулі події, або не пов'язано з загрозою

Приклади THREAT:
- "Балістика на Київ!!"
- "Балістична загроза! Всім в укриття!"
- "Пуск балістичної ракети зафіксовано"
- "Повітряна тривога! Балістика!"

Приклади SAFE:
- "Оператор Трампа заробив $100 тисяч" 
- "Аналіз балістичних ракет Росії"
- "Вчора був ракетний удар по Харкову"
- "США передадуть ракети Україні"
"""


async def is_threat_groq(text: str) -> bool:
    """
    Классифицирует текст через Groq.
    Автоматически ротирует ключи при ошибке лимита.
    """
    if not config.GROQ_KEYS:
        log.warning("Groq ключи не настроены, используем ключевые слова")
        return _fallback_keywords(text)

    # Пробуем каждый ключ по кругу (максимум количество ключей попыток)
    for _ in range(len(config.GROQ_KEYS)):
        api_key = next(_key_cycle)
        try:
            client = AsyncGroq(api_key=api_key)
            response = await client.chat.completions.create(
                model="llama-3.1-8b-instant",  # быстрая и бесплатная
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": text[:500]},
                ],
                max_tokens=5,
                temperature=0,
            )
            result = response.choices[0].message.content.strip().upper()
            is_threat = result == "THREAT"
            log.info(f"Groq: {result} | {text[:60]}...")
            return is_threat

        except Exception as e:
            err = str(e).lower()
            if "rate_limit" in err or "quota" in err or "429" in err:
                log.warning(f"Ключ {api_key[:20]}... исчерпан, ротируем")
                continue  # пробуем следующий ключ
            else:
                log.error(f"Groq ошибка: {e}")
                break

    # Все ключи исчерпаны — фолбэк на ключевые слова
    log.warning("Все Groq ключи исчерпаны, используем ключевые слова")
    return _fallback_keywords(text)


def _fallback_keywords(text: str) -> bool:
    """Резервный фильтр по ключевым словам если Groq недоступен."""
    return any(kw in text.lower() for kw in config.KEYWORDS)