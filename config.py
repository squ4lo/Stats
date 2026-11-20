"""Настройки: переменные из .env, пути к файлам, общие константы."""
import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])  # только он меняет данные

DATA_DIR = os.getenv("DATA_DIR", "data")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")  # кто сколько внёс и чем владеет
COINS_FILE = os.path.join(DATA_DIR, "coins.json")          # список монет бота
LEGACY_FILE = os.path.join(DATA_DIR, "data.json")          # старый файл, переносится сам

NAMES = {"я": "Я", "polina": "Полина", "полина": "Полина"}  # как понимать имена в командах
BASE_COIN = "USDT"  # монета, в которую идут депозиты; удалить нельзя
EPS = 1e-9
