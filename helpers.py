"""Форматирование чисел, разбор аргументов команд, проверка админа."""
import functools
import re

from config import ADMIN_ID, NAMES


def rub(x, sign=False):
    if round(x) == 0:
        x = 0
    s = f"{x:+,.0f}" if sign else f"{x:,.0f}"
    return s.replace(",", " ") + " ₽"


def q(x):
    """Количество монет без лишних нулей."""
    return f"{x:.8f}".rstrip("0").rstrip(".") or "0"


def usd_fmt(x):
    """Цена в $: для дешёвых монет больше знаков."""
    return f"${x:,.2f}" if x >= 1 else "$" + f"{x:.6f}".rstrip("0").rstrip(".")


def num(x):
    v = float(re.sub(r"[^\d.,]", "", x).replace(",", "."))
    if v <= 0:
        raise ValueError
    return v


def norm_name(x):
    return NAMES.get(x.lower(), x.capitalize())


def admin_only(fn):
    """Декоратор: команда доступна только владельцу."""
    @functools.wraps(fn)
    async def wrapper(update, ctx):
        if update.effective_user and update.effective_user.id == ADMIN_ID:
            return await fn(update, ctx)
        await update.message.reply_text("⛔ Эта команда доступна только владельцу бота.")
    return wrapper
