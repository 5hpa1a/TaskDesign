import os
from datetime import datetime, timezone, timedelta

BOT_TOKEN = os.getenv("BOT_TOKEN", "8986044239:AAHTzbb06EP4PYZIzxpIQwGKR2jTEa7T7yE")
MAIN_CHAT_ID = int(os.getenv("MAIN_CHAT_ID", "-1003789825003"))

ADMINS_FILE = "admins.txt"
DB_NAME = "bot.db"

# Строгий часовой пояс UTC+3 (Москва)
MSK_TZ = timezone(timedelta(hours=3))


def now_msk() -> datetime:
    """Возвращает текущее время строго по UTC+3 (naive datetime для совместимости с БД)."""
    return datetime.now(MSK_TZ).replace(tzinfo=None)


# Настройки для Mini App (Web App)
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://vpdesign.duckdns.org")
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8080"))


def load_ids_from_file(filename: str) -> set[int]:
    ids = set()
    if not os.path.exists(filename):
        open(filename, "w").close()
        return ids

    with open(filename, "r", encoding="utf-8") as file:
        for line in file:
            clean_line = line.strip()
            if clean_line.isdigit() or (clean_line.startswith("-") and clean_line[1:].isdigit()):
                ids.add(int(clean_line))
    return ids


def is_admin(user_id: int) -> bool:
    return user_id in load_ids_from_file(ADMINS_FILE)