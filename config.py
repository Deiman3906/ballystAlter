import os
from dotenv import load_dotenv

load_dotenv()

# Telegram userbot
API_ID       = int(os.getenv("TG_API_ID", "0"))
API_HASH     = os.getenv("TG_API_HASH", "")
SESSION_NAME = "ballistic_alert"

# Telegram bot
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Админ
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Groq ключи (ротация)
GROQ_KEYS = [
    os.getenv("GROQ_KEY_1", ""),
    os.getenv("GROQ_KEY_2", ""),
    os.getenv("GROQ_KEY_3", ""),
    os.getenv("GROQ_KEY_4", ""),
]
GROQ_KEYS = [k for k in GROQ_KEYS if k]

# Каналы для мониторинга
WATCH_CHANNELS = [
    "kyivnebomonitoring",
    "KyivPolitic",
    "insiderUKR",
    "kievreal1",
]

# Ключевые слова (фолбэк если Groq недоступен)
KEYWORDS = [
    "балістика", "балістичн",
    "балістика на київ", "балістика на ",
    "балістична загроза", "балістичний удар",
    "крилата ракета", "крилаті ракети",
    "іскандер", "кинджал", "гіперзвукова",
    "пуск балістичн", "запуск ракет",
    "ракетна загроза", "ракетний удар", "ракетна атака",
    "баллистика", "баллистика на киев", "баллистика на ",
    "баллистическая угроза", "баллистический удар",
    "крылатая ракета", "крылатые ракеты",
    "iskander", "kinzhal",
    "ракетный удар", "ракетная атака", "ракетная угроза",
]

CALL_DELAY = 3
SIREN_FILE = "siren.mp3"