"""
Крипто-бот: курс + учёт вложений на двоих.
Хранение: data.json. Токен: .env. Диаграммы рисует QuickChart (без matplotlib).
"""
import json
import os
import time
from datetime import datetime
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from telegram import InputMediaPhoto, Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
TOKEN = os.environ["BOT_TOKEN"]
DATA_FILE = os.getenv("DATA_FILE", "data/data.json")
# Только этот Telegram ID может вносить/выводить/удалять записи
ADMIN_ID = int(os.environ["ADMIN_ID"])
HISTORY_LIMIT = 100

COINS = {"USDT": "tether", "XAUT": "tether-gold", "BTC": "bitcoin", "TON": "the-open-network"}
ALIASES = {"GRAM": "TON"}
NAMES = {"я": "Я", "polina": "Полина", "полина": "Полина"}

_cache = {"ts": 0, "data": None}


# ---------- хранилище ----------
def load():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"balances": {}, "history": []}


def save(d):
    os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA_FILE)  # атомарно: файл не повредится при сбое


def apply(d, person, coin, usd, qty):
    b = d["balances"].setdefault(person, {}).setdefault(coin, {"usd": 0.0, "qty": 0.0})
    b["usd"] += usd
    b["qty"] += qty


# ---------- курс ----------
async def get_prices():
    if _cache["data"] and time.time() - _cache["ts"] < 60:
        return _cache["data"]
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ",".join(COINS.values()), "vs_currencies": "usd",
                    "include_24hr_change": "true"},
        )
    r.raise_for_status()
    j = r.json()
    data = {t: (j[i]["usd"], j[i].get("usd_24h_change") or 0) for t, i in COINS.items()}
    _cache.update(ts=time.time(), data=data)
    return data


async def is_admin(update: Update) -> bool:
    if update.effective_user and update.effective_user.id == ADMIN_ID:
        return True
    await update.message.reply_text("⛔ Эта команда доступна только владельцу бота.")
    return False


# ---------- команды ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/course — курс USDT, XAUT, BTC, TON\n"
        "/dep Я TON 100$ — внести\n"
        "/wd Полина BTC 50$ — вывести\n"
        "/stats — доли и диаграммы\n"
        "/history — последние операции\n"
        "/undo — удалить последнюю запись"
    )


async def course(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        p = await get_prices()
    except Exception:
        await update.message.reply_text("Не удалось получить курс, попробуй позже.")
        return
    lines = ["💱 Курс сейчас:"]
    lines += [f"{t}: ${v:,.2f}  ({ch:+.1f}% за 24ч)" for t, (v, ch) in p.items()]
    await update.message.reply_text("\n".join(lines))


def parse(args):
    if len(args) != 3:
        raise ValueError
    person = NAMES.get(args[0].lower(), args[0].capitalize())
    coin = ALIASES.get(args[1].upper(), args[1].upper())
    if coin not in COINS:
        raise ValueError
    amount = float(args[2].replace("$", "").replace(",", "."))
    if amount <= 0:
        raise ValueError
    return person, coin, amount


async def _add(update, ctx, sign):
    if not await is_admin(update):
        return
    try:
        person, coin, amount = parse(ctx.args)
    except ValueError:
        await update.message.reply_text(
            "Формат: /dep Я TON 100$  или  /dep Полина XAUT 45$\nВывод — /wd")
        return
    try:
        price = (await get_prices())[coin][0]
    except Exception:
        await update.message.reply_text("Не получил курс, попробуй ещё раз.")
        return

    d = load()
    usd, qty = sign * amount, sign * amount / price
    if sign < 0:
        have = d["balances"].get(person, {}).get(coin, {}).get("qty", 0)
        if abs(qty) > have * 1.000001:
            await update.message.reply_text(
                f"У {person} в {coin} только {have:.6f} шт. (~${have * price:,.2f}).")
            return

    apply(d, person, coin, usd, qty)
    d["history"].append({"ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
                         "person": person, "coin": coin, "usd": usd, "qty": qty})
    d["history"] = d["history"][-HISTORY_LIMIT:]
    save(d)

    word = "Внесено" if sign > 0 else "Выведено"
    await update.message.reply_text(
        f"✅ {word}: {person} · {coin} · ${amount:,.2f}\n"
        f"Курс ${price:,.2f} → {abs(qty):.6f} {coin}")


async def dep(update, ctx):
    await _add(update, ctx, +1)


async def wd(update, ctx):
    await _add(update, ctx, -1)


async def undo(update, ctx):
    if not await is_admin(update):
        return
    d = load()
    if not d["history"]:
        await update.message.reply_text("Записей нет.")
        return
    t = d["history"].pop()
    apply(d, t["person"], t["coin"], -t["usd"], -t["qty"])
    save(d)
    await update.message.reply_text(f"↩️ Удалено: {t['person']} {t['coin']} ${t['usd']:,.2f}")


async def history(update, ctx):
    h = load()["history"][-20:][::-1]
    if not h:
        await update.message.reply_text("Пока пусто.")
        return
    text = "\n".join(
        f"{t['ts']} · {t['person']} · {t['coin']} · {t['usd']:+,.2f}$" for t in h)
    await update.message.reply_text("🧾 Последние операции:\n" + text)


def chart_url(person, coins):
    cfg = {
        "type": "pie",
        "data": {"labels": [f"{c} ${v:,.0f}" for c, v in coins.items()],
                 "datasets": [{"data": [round(v, 2) for v in coins.values()]}]},
        "options": {"plugins": {"title": {
            "display": True, "text": f"{person}: ${sum(coins.values()):,.0f}"}}},
    }
    return ("https://quickchart.io/chart?v=3&w=500&h=420&bkg=white&c="
            + quote(json.dumps(cfg, ensure_ascii=False)))


async def stats(update, ctx):
    bal = load()["balances"]
    people = {p: {c: v for c, v in cs.items() if v["usd"] > 0.005} for p, cs in bal.items()}
    people = {p: cs for p, cs in people.items() if cs}
    if not people:
        await update.message.reply_text("Пока нет вложений. Добавь: /dep Я TON 100$")
        return
    try:
        prices = await get_prices()
    except Exception:
        prices = None

    total = sum(v["usd"] for cs in people.values() for v in cs.values())
    lines = ["📊 Доли вложений:"]
    for p, cs in people.items():
        inv = sum(v["usd"] for v in cs.values())
        lines.append(f"\n{p}: ${inv:,.2f} ({inv / total * 100:.1f}%)")
        if prices:
            now = sum(v["qty"] * prices[c][0] for c, v in cs.items())
            lines.append(f"  сейчас ${now:,.2f} ({now - inv:+,.2f}$)")
        lines += [f"  • {c}: ${v['usd']:,.2f}" for c, v in cs.items()]
    lines.append(f"\nВсего вложено: ${total:,.2f}")
    await update.message.reply_text("\n".join(lines))

    # Telegram сам скачивает картинки по ссылке — бот памяти не тратит
    urls = [(p, chart_url(p, {c: v["usd"] for c, v in cs.items()}))
            for p, cs in people.items()]
    try:
        if len(urls) == 1:
            await update.message.reply_photo(urls[0][1])
        else:
            await update.message.reply_media_group(
                [InputMediaPhoto(u, caption=p) for p, u in urls[:10]])
    except Exception:
        await update.message.reply_text("Не удалось построить диаграммы (QuickChart недоступен).")


def main():
    app = Application.builder().token(TOKEN).build()
    for name, fn in [("start", start), ("course", course), ("dep", dep), ("wd", wd),
                     ("stats", stats), ("history", history), ("undo", undo)]:
        app.add_handler(CommandHandler(name, fn))
    app.run_polling()


if __name__ == "__main__":
    main()
