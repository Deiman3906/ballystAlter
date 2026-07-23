"""
Groq классификатор угроз с ротацией ключей.
Возвращает: "THREAT" | "ALL_CLEAR" | "SAFE"
"""

import asyncio
import logging
import itertools
from groq import AsyncGroq

import config

log = logging.getLogger(__name__)

_key_cycle = itertools.cycle(config.GROQ_KEYS)

SYSTEM_PROMPT = """Ти — система раннього оповіщення про балістичні загрози в Україні.

Твоя задача: визначити статус повідомлення. Відповідай ТІЛЬКИ одним словом: THREAT, ALL_CLEAR або SAFE.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THREAT — реальна загроза ПРЯМО ЗАРАЗ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ознаки: теперішній час, терміновість, заклик ховатись.
Сигнальні слова: "летить", "зафіксовано пуск", "увага!", "всім в укриття", "термінова загроза", "прямо зараз".

Приклади THREAT:
- "Балістика на Київ!!"
- "Балістична загроза! Всім в укриття!"
- "Пуск балістичної ракети зафіксовано"
- "Увага! Балістика!"
- "Термінова загроза! Балістика летить"
- "⚠️ Балістика! Негайно в укриття!"
- "Зафіксовано пуск балістичної ракети в напрямку Києва"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ALL_CLEAR — загроза минула, відбій
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Приклади ALL_CLEAR:
- "Відбій!"
- "Відбій балістики"
- "Відбій тривоги"
- "Відбій балістичної загрози"
- "Відбій тривоги по Київу"
- "Оголошено відбій"
- "Відбій по всій території"
- "Тривога скасована"
- "Небо чисте, відбій"
- "Загроза минула"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SAFE — все інше (НЕ реальна загроза зараз)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Сюди відносяться: новини, аналітика, минулі події, згадки про зброю без загрози, політика, обговорення.
Ознаки SAFE: минулий час ("вчора", "раніше", "під час"), аналітика ("аналіз", "характеристики", "дальність"), політика.

Приклади SAFE:
- "Аналіз балістичних ракет Росії"
- "Вчора був ракетний удар по Харкову"
- "США передадуть ракети Україні"
- "Росія застосувала балістику у вересні"
- "Іскандер: технічні характеристики"
- "Обговорення нічної атаки"
- "Скільки ракет збила ППО за місяць"
- "Байден заявив про підтримку України"
- "Новини з фронту: ситуація на Херсонщині"

ВАЖЛИВО: Якщо є сумніви — вибирай SAFE. Краще пропустити новину ніж дати хибну тривогу.
"""


async def classify(text: str) -> str:
    """
    Классифицирует текст через Groq.
    Возвращает: "THREAT" | "ALL_CLEAR" | "SAFE"
    """
    if not config.GROQ_KEYS:
        log.warning("Groq ключи не настроены, используем ключевые слова")
        return _fallback_keywords(text)

    for _ in range(len(config.GROQ_KEYS)):
        api_key = next(_key_cycle)
        try:
            client = AsyncGroq(api_key=api_key)
            response = await client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": text[:500]},
                ],
                max_tokens=5,
                temperature=0,
            )
            result = response.choices[0].message.content.strip().upper()
            # Нормализуем на случай если модель вернула что-то лишнее
            if "ALL_CLEAR" in result:
                result = "ALL_CLEAR"
            elif "THREAT" in result:
                result = "THREAT"
            else:
                result = "SAFE"
            log.info(f"Groq: {result} | {text[:60]}...")
            return result

        except Exception as e:
            err = str(e).lower()
            if "rate_limit" in err or "quota" in err or "429" in err:
                log.warning(f"Ключ {api_key[:20]}... исчерпан, ротируем")
                continue
            else:
                log.error(f"Groq ошибка: {e}")
                break

    log.warning("Все Groq ключи исчерпаны, используем ключевые слова")
    return _fallback_keywords(text)


# Обратная совместимость — старый вызов is_threat_groq(text) -> bool
async def is_threat_groq(text: str) -> bool:
    return await classify(text) == "THREAT"


def _fallback_keywords(text: str) -> str:
    t = text.lower()
    all_clear_kw = [
        "відбій", "відбій тривоги", "відбій балістик", "відбій балістики",
        "тривога скасована", "оголошено відбій",
        "отбой", "отбой тревоги", "небо чисте", "загроза минула",
    ]
    threat_kw = config.KEYWORDS
    if any(kw in t for kw in all_clear_kw):
        return "ALL_CLEAR"
    if any(kw in t for kw in threat_kw):
        return "THREAT"
    return "SAFE"
