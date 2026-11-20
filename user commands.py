"""Команды для всех.

Чтобы добавить команду: напиши функцию и добавь строку в COMMANDS.
(имя, функция, подпись в меню Telegram, строка для /start)
"""
import html

import admin_commands
import coins
import portfolio as pf
import prices
from config import EPS
from helpers import q, rub, usd_fmt
from telegram.constants import ParseMode


async def start(update, ctx):
    lines = ["Для всех:"]
    lines += [u for *_, u in COMMANDS]
    lines += ["", "Только для владельца:"]
    lines += [u for *_, u in admin_commands.COMMANDS]
    await update.message.reply_text("\n".join(lines))


async def course(update, ctx):
    try:
        p = await prices.get_prices()
    except Exception:
        await update.message.reply_text("Не удалось получить курс, попробуй позже.")
        return
    lines = ["💱 Курс сейчас:"]
    for t in coins.all_coins():
        if t in p:
            v, ch = p[t]
            lines.append(f"{t}: {usd_fmt(v)}  ({ch:+.1f}% за 24ч)")
        else:
            lines.append(f"{t}: нет цены")
    await update.message.reply_text("\n".join(lines))


async def stats(update, ctx):
    people = pf.load()["people"]
    if not people:
        await update.message.reply_text("Пока нет данных. Админ добавляет: /dep Я 10000 125")
        return
    try:
        pr = await prices.get_prices()
        usd_rub = await prices.get_usd_rub()
    except Exception:
        await update.message.reply_text("Не удалось получить курс монет, попробуй позже.")
        return

    no_price = set()
    rows = {}
    for name, p in people.items():
        usd = {}
        for c, v in p["coins"].items():
            if v <= EPS:
                continue
            price = prices.usd_price(pr, c)
            if price is None:
                no_price.add(c)
                price = 0.0
            usd[c] = v * price
        rows[name] = {"p": p, "rate": pf.avg_rate(p), "usd": usd, "usd_total": sum(usd.values())}

    pool_usd = sum(x["usd_total"] for x in rows.values())
    sum_in = sum(p["rub_in"] for p in people.values())
    sum_bought = sum(p["usdt_bought"] for p in people.values())
    all_rate = sum_in / sum_bought if sum_bought > EPS else 0
    all_value = all_profit = 0.0

    lines = [f"📊 Статистика (в рублях по текущему курсу $: {usd_rub:.2f} ₽)"]
    for name, x in rows.items():
        p, r = x["p"], x["rate"]
        value = x["usd_total"] * usd_rub
        usd_out = p.get("usd_out", 0.0)
        # итог = (долларов в портфеле + долларов выведено − долларов внесено) * курс $ к ₽
        profit = (x["usd_total"] + usd_out - p["usdt_bought"]) * usd_rub
        all_value += value
        all_profit += profit
        share = f" · доля {x['usd_total'] / pool_usd * 100:.1f}%" if pool_usd > EPS else ""
        lines.append(f"\n<b><u>{html.escape(name)}</u></b>{share}")
        lines.append(f"Внесено {rub(p['rub_in'])} (${p['usdt_bought']:,.2f})")
        lines.append(f"Выведено {rub(p['rub_out'])} (${usd_out:,.2f})")
        lines.append(f"Ср. курс покупки $: {r:.2f} ₽")
        lines.append(f"<b><u>Портфель: ${x['usd_total']:,.2f} ≈ {rub(value)}</u></b>")
        lines.append(f"Итог: {rub(profit, sign=True)}")
        for c, u in x["usd"].items():
            lines.append(f"  • {c}: {q(p['coins'][c])} " +
                         ("— нет цены" if c in no_price else f"≈ {rub(u * usd_rub)}"))
    lines.append(f"\nВместе: портфель {rub(all_value)}, итог {rub(all_profit, sign=True)}")
    if all_rate:
        lines.append(f"Общий ср. курс покупки $: {all_rate:.2f} ₽")
    if no_price:
        lines.append(f"⚠️ Нет цены для: {', '.join(sorted(no_price))} — в сумму не вошли")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


COMMANDS = [
    ("start", start, "Список команд", "/start — список команд"),
    ("course", course, "Курс монет", "/course — курс всех монет бота"),
    ("stats", stats, "Доли и итог в рублях", "/stats — доли и итог в рублях"),
]
