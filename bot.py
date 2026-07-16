"""
🚨 BalistAlert Bot з дзвінками через Telethon MTProto
"""

import asyncio
import logging
import os
import struct
import hashlib
from datetime import datetime

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.phone import RequestCallRequest, DiscardCallRequest
from telethon.tl.types import PhoneCallProtocol, InputPhoneCall
from supabase import create_client
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

import config
from subscribers import add_subscriber, remove_subscriber, get_subscribers, log_alert
from groq_classifier import is_threat_groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def load_session() -> StringSession:
    try:
        sb  = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        res = sb.table("session").select("data").eq("id", 1).execute()
        if res.data:
            log.info("✅ Сесія завантажена з Supabase")
            return StringSession(res.data[0]["data"])
    except Exception as e:
        log.error(f"❌ Помилка завантаження сесії: {e}")
    return StringSession()


userbot = TelegramClient(load_session(), config.API_ID, config.API_HASH)
bot     = Bot(token=config.BOT_TOKEN)
dp      = Dispatcher()


# ─── Клавиатуры ─────────────────────────────────────────────

def kb_main(is_subscribed: bool = False) -> InlineKeyboardMarkup:
    sub_btn = InlineKeyboardButton(
        text="🔕 Відписатись" if is_subscribed else "🔔 Підписатись на сповіщення",
        callback_data="unsubscribe" if is_subscribed else "subscribe"
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [sub_btn],
        [InlineKeyboardButton(text="ℹ️ Про бота", callback_data="about")],
    ])

def kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])


# ─── Алерт ──────────────────────────────────────────────────

def build_alert(channel_name: str, original_text: str) -> str:
    now     = datetime.now().strftime("%H:%M:%S")
    preview = original_text.strip()[:300]
    if len(original_text) > 300:
        preview += "..."
    return (
        "🚨 *БАЛІСТИЧНА ЗАГРОЗА* 🚨\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"🕐 Час: `{now}`\n"
        f"📡 Джерело: `{channel_name}`\n\n"
        f"📝 Повідомлення:\n_{preview}_\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "⚠️ *НЕГАЙНО ЗАЙДІТЬ У УКРИТТЯ*"
    )


# ─── Звонок через Telethon MTProto ──────────────────────────

async def call_user(user_id: int):
    try:
        log.info(f"📞 Дзвоним {user_id}...")
        user = await userbot.get_entity(user_id)

        # Генеруємо g_a для протоколу
        g_a_hash = hashlib.sha256(os.urandom(256)).digest()

        protocol = PhoneCallProtocol(
            min_layer=65,
            max_layer=92,
            udp_p2p=True,
            udp_reflector=True,
            library_versions=["3.0.0"],
        )

        result = await userbot(RequestCallRequest(
            user_id=user,
            random_id=int.from_bytes(os.urandom(4), 'big'),
            g_a_hash=g_a_hash,
            protocol=protocol,
        ))

        log.info(f"✅ Дзвінок ініційовано → {user_id}, id={result.phone_call.id}")

        # Тримаємо дзвінок 20 секунд
        await asyncio.sleep(20)

        # Завершуємо дзвінок
        try:
            await userbot(DiscardCallRequest(
                peer=InputPhoneCall(
                    id=result.phone_call.id,
                    access_hash=result.phone_call.access_hash,
                ),
                duration=20,
                reason=None,
                connection_id=0,
            ))
        except Exception:
            pass

        log.info(f"✅ Дзвінок завершено → {user_id}")

    except Exception as e:
        log.error(f"❌ Помилка дзвінка {user_id}: {e}")


# ─── Оповещение всех ────────────────────────────────────────

async def alert_all(channel_name: str, text: str):
    subscribers = get_subscribers()
    if not subscribers:
        log.warning("Немає підписників!")
        return
    log_alert(channel_name, text, len(subscribers))
    message = build_alert(channel_name, text)
    for user_id in subscribers:
        try:
            await bot.send_message(user_id, message, parse_mode="Markdown")
            log.info(f"✅ Повідомлення → {user_id}")
        except Exception as e:
            log.error(f"❌ {user_id}: {e}")

    await asyncio.sleep(config.CALL_DELAY)

    for uid in subscribers:
        await call_user(uid)
        await asyncio.sleep(2)


# ─── Мониторинг каналов ─────────────────────────────────────

@userbot.on(events.NewMessage(chats=config.WATCH_CHANNELS))
async def on_channel_message(event):
    text = event.raw_text
    if not text:
        return
    is_threat = await is_threat_groq(text)
    if not is_threat:
        return
    chat         = await event.get_chat()
    channel_name = getattr(chat, "title", str(chat.id))
    log.warning(f"🚨 [{channel_name}]: {text[:80]}...")
    await alert_all(channel_name, text)


# ─── /start ─────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user   = message.from_user
    is_sub = user.id in get_subscribers()
    caption = (
        f"👋 Привіт, *{user.first_name}*\\!\n\n"
        "Я *BalistAlert* — бот раннього оповіщення про балістичні загрози\\.\n\n"
        "🛡 Моніторю канали 24/7 та одразу сповіщу тебе при загрозі\\.\n\n"
        "Натисни кнопку нижче щоб підписатись 👇"
    )
    try:
        photo = FSInputFile("welcome.jpg")
        await message.answer_photo(photo=photo, caption=caption,
                                   parse_mode="MarkdownV2", reply_markup=kb_main(is_sub))
    except Exception:
        await message.answer(caption, parse_mode="MarkdownV2", reply_markup=kb_main(is_sub))


# ─── Callbacks ──────────────────────────────────────────────

@dp.callback_query(F.data == "subscribe")
async def cb_subscribe(call: types.CallbackQuery):
    user = call.from_user
    add_subscriber(user.id, user.username or "", user.first_name or "")
    await call.message.edit_reply_markup(reply_markup=kb_main(is_subscribed=True))
    await call.answer("✅ Підписано!", show_alert=False)
    await call.message.answer(
        "✅ *Підписку оформлено\\!*\n\n"
        "При балістичній загрозі я одразу надішлю повідомлення і *зателефоную* тобі 🚨\n\n"
        "_Не вимикай сповіщення від бота\\!_",
        parse_mode="MarkdownV2"
    )

@dp.callback_query(F.data == "unsubscribe")
async def cb_unsubscribe(call: types.CallbackQuery):
    remove_subscriber(call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=kb_main(is_subscribed=False))
    await call.answer("❌ Відписано", show_alert=False)
    await call.message.answer(
        "❌ *Ти відписаний від сповіщень\\.*\n\n"
        "Натисни 🔔 щоб підписатись знову\\.",
        parse_mode="MarkdownV2"
    )

@dp.callback_query(F.data == "about")
async def cb_about(call: types.CallbackQuery):
    await call.message.answer(
        "🛡 *BalistAlert*\n\n"
        "Цей бот створений для твоєї безпеки\\.\n\n"
        "⚡️ Я слідкую за ситуацією в небі 24 години на добу\\.\n\n"
        "🚨 При загрозі отримаєш повідомлення і дзвінок в Telegram\\.\n\n"
        "🤖 Аналіз через штучний інтелект\\.\n\n"
        "_Підпишись і будь в безпеці\\._",
        parse_mode="MarkdownV2",
        reply_markup=kb_back()
    )

@dp.callback_query(F.data == "back")
async def cb_back(call: types.CallbackQuery):
    await call.message.delete()


# ─── Админ команды ───────────────────────────────────────────

@dp.message(Command("test"))
async def cmd_test(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    await alert_all("🧪 Тест", "Балістика на Київ!! Термінова загроза! Всім в укриття!")
    await message.answer("✅ Тестовий алерт надіслано.")

@dp.message(Command("calltest"))
async def cmd_calltest(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    await message.answer("📞 Дзвоню тобі...")
    await call_user(message.from_user.id)

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    subs = get_subscribers()
    await message.answer(
        f"📊 *Статистика*\n\n"
        f"👥 Підписників: *{len(subs)}*\n"
        f"🤖 Groq ключів: *{len(config.GROQ_KEYS)}*\n"
        f"📡 Каналів: *{len(config.WATCH_CHANNELS)}*",
        parse_mode="Markdown"
    )

@dp.message(Command("subs"))
async def cmd_subs(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    subs = get_subscribers()
    if not subs:
        await message.answer("📭 Підписників немає.")
        return
    text = "👥 *Список підписників:*\n\n"
    for i, uid in enumerate(subs, 1):
        text += f"{i}. `{uid}`\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("Використання: `/broadcast текст`", parse_mode="Markdown")
        return
    subs  = get_subscribers()
    count = 0
    for uid in subs:
        try:
            await bot.send_message(uid, text)
            count += 1
        except Exception as e:
            log.error(f"Broadcast {uid}: {e}")
    await message.answer(f"✅ Надіслано {count}/{len(subs)} підписникам.")


# ─── Запуск ─────────────────────────────────────────────────

async def main():
    log.info("🚀 Запуск BalistAlert...")
    await userbot.start()
    me = await userbot.get_me()
    log.info(f"👤 Userbot: {me.first_name} (@{me.username})")
    log.info(f"🤖 Groq ключів: {len(config.GROQ_KEYS)}")
    log.info("✅ Бот запущений!")
    await asyncio.gather(
        dp.start_polling(bot),
        userbot.run_until_disconnected(),
    )

if __name__ == "__main__":
    asyncio.run(main())
