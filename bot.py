"""
🚨 BalistAlert Bot
"""

import asyncio
import logging
from datetime import datetime

from telethon import TelegramClient, events
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

import config
from subscribers import add_subscriber, remove_subscriber, get_subscribers, log_alert
from groq_classifier import is_threat_groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

userbot = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
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

async def alert_all(channel_name: str, text: str):
    subscribers = get_subscribers()
    if not subscribers:
        log.warning("Нет подписчиков!")
        return
    log_alert(channel_name, text, len(subscribers))
    message = build_alert(channel_name, text)
    for user_id in subscribers:
        try:
            await bot.send_message(user_id, message, parse_mode="Markdown")
            log.info(f"✅ → {user_id}")
        except Exception as e:
            log.error(f"❌ {user_id}: {e}")


# ─── Мониторинг каналов ─────────────────────────────────────

@userbot.on(events.NewMessage(chats=config.WATCH_CHANNELS))
async def on_channel_message(event):
    text = event.raw_text
    if not text:
        return

    # Groq классификация (с фолбэком на ключевые слова)
    is_threat = await is_threat_groq(text)
    if not is_threat:
        return

    chat         = await event.get_chat()
    channel_name = getattr(chat, "title", str(chat.id))
    log.warning(f"🚨 ЗАГРОЗА [{channel_name}]: {text[:80]}...")
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
        "При балістичній загрозі я одразу надішлю тобі повідомлення 🚨\n\n"
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

@dp.callback_query(F.data == "status")
async def cb_status(call: types.CallbackQuery):
    count = len(get_subscribers())
    await call.answer(f"👥 Активних підписників: {count}", show_alert=True)


# ─── Админ команды ───────────────────────────────────────────

def admin_only(func):
    """Декоратор — только для админа."""
    async def wrapper(message: types.Message, *args, **kwargs):
        if message.from_user.id != config.ADMIN_ID:
            await message.answer("⛔️ Немає доступу.")
            return
        await func(message, *args, **kwargs)
    return wrapper


@dp.message(Command("stats"))
@admin_only
async def cmd_stats(message: types.Message):
    subs = get_subscribers()
    await message.answer(
        f"📊 *Статистика BalistAlert*\n\n"
        f"👥 Підписників: *{len(subs)}*\n"
        f"🤖 Groq ключів: *{len(config.GROQ_KEYS)}*\n"
        f"📡 Каналів: *{len(config.WATCH_CHANNELS)}*",
        parse_mode="Markdown"
    )


@dp.message(Command("subs"))
@admin_only
async def cmd_subs(message: types.Message):
    subs = get_subscribers()
    if not subs:
        await message.answer("📭 Підписників немає.")
        return
    text = "👥 *Список підписників:*\n\n"
    for i, uid in enumerate(subs, 1):
        text += f"{i}. `{uid}`\n"
    await message.answer(text, parse_mode="Markdown")


@dp.message(Command("test"))
@admin_only
async def cmd_test(message: types.Message):
    await alert_all("🧪 Тест", "Балістика на Київ!! Термінова загроза! Всім в укриття!")
    await message.answer("✅ Тестовий алерт надіслано всім підписникам.")


@dp.message(Command("broadcast"))
@admin_only
async def cmd_broadcast(message: types.Message):
    """Ручна розсилка: /broadcast текст повідомлення"""
    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("Використання: `/broadcast текст повідомлення`", parse_mode="Markdown")
        return
    subs  = get_subscribers()
    count = 0
    for uid in subs:
        try:
            await bot.send_message(uid, text)
            count += 1
        except Exception as e:
            log.error(f"Broadcast error {uid}: {e}")
    await message.answer(f"✅ Надіслано {count}/{len(subs)} підписникам.")

@dp.callback_query(F.data == "about")
async def cb_about(call: types.CallbackQuery):
    await call.message.answer(
        "🛡 *BalistAlert*\n\n"
        "Цей бот створений для твоєї безпеки\\.\n\n"
        "⚡️ Я слідкую за ситуацією в небі 24 години на добу, "
        "7 днів на тиждень — навіть поки ти спиш\\.\n\n"
        "🚨 При виявленні балістичної загрози ти миттєво "
        "отримаєш сповіщення з деталями\\.\n\n"
        "🤖 Для аналізу повідомлень використовую штучний "
        "інтелект — це мінімізує хибні спрацювання\\.\n\n"
        "_Підпишись і будь в безпеці\\._",
        parse_mode="MarkdownV2",
        reply_markup=kb_back()
    )

@dp.callback_query(F.data == "back")
async def cb_back(call: types.CallbackQuery):
    await call.message.delete()


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