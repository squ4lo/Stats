"""Точка входа: только собирает бота из модулей и запускает.

Структура:
  config.py          настройки (.env, пути, имена людей)
  storage.py         чтение/запись json
  coins.py           список монет (data/coins.json), поиск на CoinGecko
  prices.py          цены монет и курс доллара
  portfolio.py       вложения людей (data/portfolio.json)
  helpers.py         форматирование, разбор аргументов, @admin_only
  user_commands.py   команды для всех
  admin_commands.py  команды владельца

Убрать команду — удалить строку из COMMANDS в нужном модуле.
Новый модуль с командами — добавить его в MODULES ниже.
"""
from telegram import BotCommand
from telegram.ext import Application, CommandHandler

import admin_commands
import user_commands
from config import TOKEN

MODULES = [user_commands, admin_commands]


async def post_init(app):
    # список команд, который Telegram показывает при вводе "/"
    await app.bot.set_my_commands(
        [BotCommand(name, desc) for m in MODULES for name, _, desc, _ in m.COMMANDS])


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    for m in MODULES:
        for name, fn, _, _ in m.COMMANDS:
            app.add_handler(CommandHandler(name, fn))
        for h in getattr(m, "HANDLERS", []):
            app.add_handler(h)
    app.run_polling()


if __name__ == "__main__":
    main()
