"""
🚨 BalistAlert Bot з дзвінками через Telethon MTProto
"""

import asyncio
import logging
import os
import struct
import hashlib
from datetime import datetime
from subscribers import add_subscriber, remove_subscriber, get_subscribers, get_subscribers_full, log_alert

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.phone import RequestCallRequest, DiscardCallRequest
from telethon.tl.types import PhoneCallProtocol, InputPhoneCall, InputUser
from supabase import create_client
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

import config
from subscribers import add_subscriber, remove_subscriber, get_subscribers, log_alert
from groq_classifier import classify

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── Состояние тревоги ───────────────────────────────────────
# True  = тревога активна, звонки уже были — игнорируем новые THREAT
# False = спокойно, реагируем на первый THREAT
_alert_active = False
_alert_lock   = asyncio.Lock()


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

async def call_user(user_id: int, access_hash: int = None, username: str = None):
    try:
        log.info(f"📞 Дзвоним {user_id}...")
        
        from telethon.tl.types import InputUser
        input_user = None

        # 1. Пробуем по access_hash
        if access_hash:
            input_user = InputUser(user_id=user_id, access_hash=access_hash)
            log.info(f"✅ Використовуємо access_hash для {user_id}")

        # 2. Пробуем по username
        if input_user is None and username:
            try:
                entity = await userbot.get_entity(f"@{username}")
                input_user = InputUser(user_id=entity.id, access_hash=entity.access_hash)
                log.info(f"✅ Знайшли по @{username}")
            except Exception as e:
                log.warning(f"Не знайшли по username @{username}: {e}")

        # 3. Пробуем напрямую по user_id
        if input_user is None:
            try:
                entity = await userbot.get_entity(user_id)
                input_user = InputUser(user_id=entity.id, access_hash=entity.access_hash)
                log.info(f"✅ Знайшли по user_id {user_id}")
            except Exception as e:
                log.error(f"❌ Не вдалось знайти юзера {user_id}: {e}")
                return

        g_a_hash = hashlib.sha256(os.urandom(256)).digest()
        protocol = PhoneCallProtocol(
            min_layer=65,
            max_layer=92,
            udp_p2p=True,
            udp_reflector=True,
            library_versions=["3.0.0"],
        )
        result = await userbot(RequestCallRequest(
            user_id=input_user,
            random_id=int.from_bytes(os.urandom(4), "big") % 2147483647,
            g_a_hash=g_a_hash,
            protocol=protocol,
        ))

        log.info(f"✅ Дзвінок ініційовано → {user_id}")
        await asyncio.sleep(20)

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
    subscribers = get_subscribers_full()
    if not subscribers:
        log.warning("Немає підписників!")
        return
    log_alert(channel_name, text, len(subscribers))
    message = build_alert(channel_name, text)
    
    for row in subscribers:
        try:
            await bot.send_message(row["user_id"], message, parse_mode="Markdown")
            log.info(f"✅ Повідомлення → {row['user_id']}")
        except Exception as e:
            log.error(f"❌ {row['user_id']}: {e}")

    await asyncio.sleep(config.CALL_DELAY)

    # Звоним всем одновременно!
    call_tasks = [
        call_user(row["user_id"], row.get("access_hash"), row.get("username"))
        for row in subscribers
        if row["user_id"] != config.ADMIN_ID
    ]
    await asyncio.gather(*call_tasks)


# ─── Мониторинг каналов ─────────────────────────────────────

@userbot.on(events.NewMessage(chats=config.WATCH_CHANNELS))
async def on_channel_message(event):
    global _alert_active

    text = event.raw_text
    if not text:
        return

    chat         = await event.get_chat()
    channel_name = getattr(chat, "title", str(chat.id))

    status = await classify(text)

    if status == "THREAT":
        async with _alert_lock:
            if _alert_active:
                log.info(f"⚠️ [{channel_name}] THREAT но тревога уже активна — пропускаем")
                return
            _alert_active = True  # фиксируем ДО рассылки

        log.warning(f"🚨 [{channel_name}]: {text[:80]}...")
        await alert_all(channel_name, text)

    elif status == "ALL_CLEAR":
        async with _alert_lock:
            if not _alert_active:
                log.info(f"✅ [{channel_name}] ALL_CLEAR но тревога уже снята — пропускаем")
                return
            _alert_active = False

        log.info(f"✅ [{channel_name}] ВІДБІЙ — тривога знята")
        # Уведомляем подписчиков об отбое
        subs = get_subscribers_full()
        for row in subs:
            try:
                await bot.send_message(
                    row["user_id"],
                    "✅ *ВІДБІЙ* — балістична загроза минула\\.\n\n_Можна виходити з укриття\\._",
                    parse_mode="MarkdownV2"
                )
            except Exception as e:
                log.error(f"Відбій → {row['user_id']}: {e}")

    else:
        # SAFE — игнорируем
        pass


# ─── /start ─────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user   = message.from_user
    is_sub = user.id in get_subscribers()
    caption = (
        f"👋 Привіт, *{user.first_name}*\\!\n\n"
        "Я *BalistAlert* — бот раннього оповіщення про балістичні загрози\\.\n\n"
        "🛡 Моніторю канали 24/7 та одразу сповіщу тебе при загрозі\\.\n\n"
        "📞 При загрозі надішлю повідомлення та *зателефоную* тобі\\!\n\n"
        "⚠️ Для дзвінків у *Telegram*: *Налаштування → Конфіденційність → Дзвінки → Всі*\n\n"
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
    
    access_hash = None
    try:
        await userbot.send_message(user.id, 
            "👋 Привіт! Я буду дзвонити тобі при балістичній загрозі. "
            "Не блокуй мене щоб дзвінки працювали! 🚨")
        log.info(f"✅ Userbot написав {user.id}")
        await asyncio.sleep(1)
        entity = await userbot.get_entity(user.id)
        access_hash = entity.access_hash
        log.info(f"✅ access_hash для {user.id}: {access_hash}")
    except Exception as e:
        log.warning(f"Не вдалось отримати access_hash: {e}")
    
    add_subscriber(user.id, user.username or "", user.first_name or "", access_hash)
    
    await call.message.edit_reply_markup(reply_markup=kb_main(is_subscribed=True))
    await call.answer("✅ Підписано!", show_alert=False)
    await call.message.answer(
        "✅ *Підписку оформлено\\!*\n\n"
        "При балістичній загрозі я одразу надішлю повідомлення і *зателефоную* тобі 🚨\n\n"
        "⚠️ *Важливо для дзвінків\\!*\n"
        "Щоб отримувати дзвінки\\-оповіщення:\n\n"
        "📱 *Налаштування → Конфіденційність → Дзвінки → Всі*\n\n"
        "_Без цього дзвінок може не пройти\\!_\n\n"
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
    await call_user(
        message.from_user.id,
        username=message.from_user.username
    )

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

@dp.message(Command("alertstatus"))
async def cmd_alertstatus(message: types.Message):
    if message.from_user.id != config.ADMIN_ID:
        return
    status = "🚨 АКТИВНА" if _alert_active else "✅ Спокійно"
    await message.answer(f"📊 Статус тривоги: *{status}*", parse_mode="Markdown")

@dp.message(Command("resetalert"))
async def cmd_resetalert(message: types.Message):
    global _alert_active
    if message.from_user.id != config.ADMIN_ID:
        return
    _alert_active = False
    await message.answer("✅ Тривогу знято вручну.")

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
