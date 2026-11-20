"""Команды владельца (проверка ID — декоратор @admin_only).

Чтобы добавить команду: напиши функцию с @admin_only и добавь строку в COMMANDS.
(имя, функция, подпись в меню Telegram, строка для /start)
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler

import coins
import portfolio as pf
import prices
from config import ADMIN_ID, BASE_COIN, EPS
from helpers import admin_only, norm_name, num, q, rub, usd_fmt


# ---------- деньги ----------
@admin_only
async def dep(update, ctx):
    """/dep Я 10000 125 — внёс 10000 ₽, купил 125 USDT"""
    try:
        if len(ctx.args) != 3:
            raise ValueError
        name, rub_amt, usdt = norm_name(ctx.args[0]), num(ctx.args[1]), num(ctx.args[2])
    except ValueError:
        await update.message.reply_text("Формат: /dep Я 10000 125\n(рубли, потом сколько USDT получилось)")
        return
    d = pf.load()
    pf.snapshot(d)
    p = pf.person_of(d, name)
    p["rub_in"] += rub_amt
    p["usdt_bought"] += usdt
    p["coins"][BASE_COIN] = p["coins"].get(BASE_COIN, 0.0) + usdt
    pf.save(d)
    await update.message.reply_text(
        f"✅ Депозит: {name} +{rub(rub_amt)} → {q(usdt)} {BASE_COIN}\n"
        f"Курс этой покупки: {rub_amt / usdt:.2f} ₽/$\n"
        f"Средний курс {name}: {pf.avg_rate(p):.2f} ₽/$")


@admin_only
async def change(update, ctx):
    """/change Я USDT TON 100 [25] — обмен монеты на монету"""
    a = ctx.args
    try:
        if len(a) not in (4, 5):
            raise ValueError
        name, src, dst = norm_name(a[0]), coins.norm_coin(a[1]), coins.norm_coin(a[2])
        amt = num(a[3])
        got = num(a[4]) if len(a) == 5 else None
        if src == dst:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Формат: /change Я USDT TON 100\nили с точным результатом: /change Я USDT TON 100 25\n"
            "Монеты: " + ", ".join(coins.all_coins()))
        return
    d = pf.load()
    have = pf.balance(d, name, src)
    if amt > have * (1 + EPS) + EPS:
        await update.message.reply_text(f"У {name} только {q(have)} {src}.")
        return
    amt = min(amt, have)
    auto = got is None
    if auto:
        try:
            pr = await prices.get_prices()
        except Exception:
            pr = {}
        ps, pd = prices.usd_price(pr, src), prices.usd_price(pr, dst)
        if not ps or not pd:
            await update.message.reply_text(
                "Рыночный курс недоступен — укажи сколько получил: /change Я USDT TON 100 25")
            return
        got = amt * ps / pd
    pf.snapshot(d)
    c = pf.person_of(d, name)["coins"]
    c[src] = max(c.get(src, 0.0) - amt, 0.0)
    if c[src] < EPS:
        c[src] = 0.0
    c[dst] = c.get(dst, 0.0) + got
    pf.save(d)
    await update.message.reply_text(
        f"🔄 {name}: {q(amt)} {src} → {q(got)} {dst}\n"
        f"1 {dst} = {q(round(amt / got, 6))} {src}" + (" (по рынку)" if auto else ""))


@admin_only
async def wd(update, ctx):
    """/wd Я TON 25 3000 — продал 25 TON за 3000 ₽"""
    try:
        if len(ctx.args) != 4:
            raise ValueError
        name, coin = norm_name(ctx.args[0]), coins.norm_coin(ctx.args[1])
        amt, rub_amt = num(ctx.args[2]), num(ctx.args[3])
    except ValueError:
        await update.message.reply_text("Формат: /wd Я TON 25 3000\n(монета, сколько продал, сколько рублей получил)")
        return
    d = pf.load()
    have = pf.balance(d, name, coin)
    if amt > have * (1 + EPS) + EPS:
        await update.message.reply_text(f"У {name} только {q(have)} {coin}.")
        return
    amt = min(amt, have)
    try:
        usd_rub = await prices.get_usd_rub()  # чтобы записать, сколько долларов вывели
    except Exception:
        await update.message.reply_text("Не удалось получить курс доллара, попробуй ещё раз.")
        return
    pf.snapshot(d)
    p = pf.person_of(d, name)
    p["coins"][coin] = max(have - amt, 0.0)
    if p["coins"][coin] < EPS:
        p["coins"][coin] = 0.0
    p["rub_out"] += rub_amt
    p["usd_out"] = p.get("usd_out", 0.0) + rub_amt / usd_rub
    pf.save(d)
    await update.message.reply_text(
        f"💸 Вывод: {name} продал {q(amt)} {coin} за {rub(rub_amt)}\n"
        f"Это {rub_amt / amt:.2f} ₽ за 1 {coin}\n"
        f"≈ ${rub_amt / usd_rub:,.2f} по текущему курсу $ ({usd_rub:.2f} ₽)")


@admin_only
async def undo(update, ctx):
    d = pf.load()
    if d["prev"] is None:
        await update.message.reply_text("Нечего отменять.")
        return
    d["people"], d["prev"] = d["prev"], None
    pf.save(d)
    await update.message.reply_text("↩️ Последняя операция отменена.")


# ---------- управление монетами ----------
def _cancel_row():
    return [InlineKeyboardButton("❌ Отмена", callback_data="ac:no")]


async def _confirm_view(r):
    """Текст и кнопки подтверждения для найденной монеты r."""
    try:
        price = await coins.fetch_price(r["id"])
    except Exception:
        price = None
    ticker = "".join(ch for ch in r["symbol"].upper() if ch.isalnum())
    if price is None:
        return (f"У монеты {r['name']} ({ticker}) нет цены на CoinGecko — "
                "добавить её нельзя.", None)
    text = (f"Добавить эту монету?\n\n{r['name']} ({ticker})\n"
            f"CoinGecko id: {r['id']}\nЦена сейчас: {usd_fmt(price)}\n"
            f"В командах писать: {ticker}")
    return text, InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Да, добавить", callback_data="ac:yes"),
        InlineKeyboardButton("❌ Нет", callback_data="ac:no")]])


@admin_only
async def addcoin(update, ctx):
    """/addcoin tston — найти монету, выбрать вариант, подтвердить"""
    query = " ".join(ctx.args).strip()
    if not query:
        await update.message.reply_text("Формат: /addcoin название или тикер\nНапример: /addcoin tonstakers")
        return
    try:
        found = await coins.search(query)
    except Exception:
        await update.message.reply_text("Поиск недоступен, попробуй позже.")
        return
    if not found:
        await update.message.reply_text("Ничего не нашёл. Попробуй другое название.")
        return
    ctx.user_data["found"] = found
    ctx.user_data["picked"] = None
    if len(found) == 1:  # даже один вариант нужно подтвердить
        ctx.user_data["picked"] = 0
        text, markup = await _confirm_view(found[0])
        await update.message.reply_text(text, reply_markup=markup)
        return
    rows = []
    for i, r in enumerate(found):
        label = f"{r['name']} ({r['symbol'].upper()})" + (f" · #{r['rank']}" if r["rank"] else "")
        rows.append([InlineKeyboardButton(label, callback_data=f"ac:pick:{i}")])
    rows.append(_cancel_row())
    await update.message.reply_text("Нашёл несколько вариантов, выбери нужный:",
                                    reply_markup=InlineKeyboardMarkup(rows))


@admin_only
async def delcoin(update, ctx):
    """/delcoin TON — убрать монету из бота (если ни у кого её нет)"""
    if len(ctx.args) != 1:
        await update.message.reply_text("Формат: /delcoin ТИКЕР\nМонеты: " + ", ".join(coins.all_coins()))
        return
    try:
        ticker = coins.norm_coin(ctx.args[0])
    except ValueError:
        await update.message.reply_text("Такой монеты нет. Монеты: " + ", ".join(coins.all_coins()))
        return
    err = _delete_error(ticker)
    if err:
        await update.message.reply_text(err)
        return
    await update.message.reply_text(
        f"Убрать {ticker} из бота?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Да, убрать", callback_data=f"ac:del:{ticker}"),
            InlineKeyboardButton("❌ Нет", callback_data="ac:no")]]))


def _delete_error(ticker):
    if ticker == BASE_COIN:
        return f"{BASE_COIN} удалить нельзя — в неё идут депозиты."
    h = pf.holders(ticker)
    if h:
        return f"Нельзя: {ticker} есть у {', '.join(h)}. Сначала обменяй или выведи."
    return None


async def coin_callback(update, ctx):
    """Нажатия на кнопки addcoin / delcoin."""
    cb = update.callback_query
    if cb.from_user.id != ADMIN_ID:
        await cb.answer("Только для владельца", show_alert=True)
        return
    await cb.answer()
    parts = cb.data.split(":")  # ac:<действие>[:<аргумент>]
    act, arg = parts[1], (parts[2] if len(parts) > 2 else None)
    found = ctx.user_data.get("found") or []

    if act == "no":
        ctx.user_data.pop("found", None)
        await cb.edit_message_text("Отменено.")
    elif act == "pick":
        if not arg or not arg.isdigit() or int(arg) >= len(found):
            await cb.edit_message_text("Список устарел, повтори /addcoin.")
            return
        ctx.user_data["picked"] = int(arg)
        text, markup = await _confirm_view(found[int(arg)])
        await cb.edit_message_text(text, reply_markup=markup)
    elif act == "yes":
        i = ctx.user_data.get("picked")
        if i is None or i >= len(found):
            await cb.edit_message_text("Список устарел, повтори /addcoin.")
            return
        r = found[i]
        try:
            ticker = coins.add_coin(r["id"], r["symbol"], r["name"])
        except ValueError as e:
            await cb.edit_message_text(f"⚠️ {e}")
            return
        ctx.user_data.pop("found", None)
        prices.invalidate()
        await cb.edit_message_text(
            f"✅ Добавлено: {r['name']} ({ticker}).\n"
            f"Теперь можно: /change Я USDT {ticker} 100 — и курс виден в /course.")
    elif act == "del":
        err = _delete_error(arg or "")
        if not err:
            try:
                coins.remove_coin(arg)
            except ValueError as e:
                err = str(e)
        if err:
            await cb.edit_message_text(f"⚠️ {err}")
            return
        prices.invalidate()
        await cb.edit_message_text(f"🗑 {arg} убрана из бота.")


COMMANDS = [
    ("dep", dep, "Депозит: /dep Я 10000 125",
     "/dep Я 10000 125 — внёс 10000 ₽, получил 125 USDT"),
    ("change", change, "Обмен монет: /change Я USDT TON 100",
     "/change Я USDT TON 100 — обмен по рынку\n"
     "/change Я USDT TON 100 25 — обмен, получил ровно 25 TON"),
    ("wd", wd, "Вывод в рубли: /wd Я TON 25 3000",
     "/wd Я TON 25 3000 — продал 25 TON за 3000 ₽"),
    ("undo", undo, "Отменить последнюю операцию",
     "/undo — отменить последнюю операцию"),
    ("addcoin", addcoin, "Добавить монету: /addcoin tston",
     "/addcoin tston — найти и добавить новую монету"),
    ("delcoin", delcoin, "Убрать монету: /delcoin TSTON",
     "/delcoin TSTON — убрать монету"),
]

# Обработчики кнопок (не команды)
HANDLERS = [CallbackQueryHandler(coin_callback, pattern=r"^ac:")]
