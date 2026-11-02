import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8986044239:AAHTzbb06EP4PYZIzxpIQwGKR2jTEa7T7yE")
MAIN_CHAT_ID = int(os.getenv("MAIN_CHAT_ID", "-1003789825003"))

ADMINS_FILE = "admins.txt"
DB_NAME = "bot.db"

# Настройки для Mini App (Web App)
# ВАЖНО: Telegram требует только HTTPS URL!
# Для тестов на локальной машине используйте ngrok: ngrok http 8080
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://whinny-routing-headfirst.ngrok-free.dev")
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