"""
Крипто-бот на двоих: депозит рублями -> USDT -> другие монеты.
Всё в рублях по СРЕДНЕМУ КУРСУ ПОКУПКИ доллара (курс ЦБ не используется).
Хранение: data/data.json. Токен и ID админа: .env
"""
import copy
import json
import os
import re
import time
from urllib.parse import quote

import httpx
from dotenv import load_dotenv
from telegram import InputMediaPhoto, Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()
TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])  # только он меняет данные
DATA_FILE = os.getenv("DATA_FILE", "data/data.json")

COINS = {"USDT": "tether", "XAUT": "tether-gold", "BTC": "bitcoin", "TON": "the-open-network"}
ALIASES = {"GRAM": "TON"}
NAMES = {"я": "Я", "polina": "Полина", "полина": "Полина"}
EPS = 1e-9

_cache = {"ts": 0, "data": None}


# ---------- хранилище ----------
def load():
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if "people" in d:
            return d
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {"people": {}, "prev": None}


def save(d):
    os.makedirs(os.path.dirname(DATA_FILE) or ".", exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA_FILE)  # атомарно


def person_of(d, name):
    return d["people"].setdefault(
        name, {"rub_in": 0.0, "usdt_bought": 0.0, "rub_out": 0.0, "coins": {}})


def balance(d, name, coin):
    return d["people"].get(name, {}).get("coins", {}).get(coin, 0.0)


def snapshot(d):
    d["prev"] = copy.deepcopy(d["people"])  # одна копия — для /undo


# ---------- вспомогательное ----------
def rub(x, sign=False):
    if round(x) == 0:
        x = 0
    s = f"{x:+,.0f}" if sign else f"{x:,.0f}"
    return s.replace(",", " ") + " ₽"


def q(x):
    return f"{x:.8f}".rstrip("0").rstrip(".") or "0"


def num(x):
    v = float(re.sub(r"[^\d.,]", "", x).replace(",", "."))
    if v <= 0:
        raise ValueError
    return v


def norm_name(x):
    return NAMES.get(x.lower(), x.capitalize())


def norm_coin(x):
    c = ALIASES.get(x.upper(), x.upper())
    if c not in COINS:
        raise ValueError
    return c


def avg_rate(p):
    return p["rub_in"] / p["usdt_bought"] if p["usdt_bought"] > EPS else 0.0


def usd_price(prices, coin):
    return 1.0 if coin == "USDT" else prices[coin][0]


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


# ---------- открытые команды ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/course — курс USDT, XAUT, BTC, TON\n"
        "/stats — доли, итог в рублях, диаграммы\n\n"
        "Только для владельца:\n"
        "/dep Я 10000 125 — внёс 10000 ₽, получил 125 USDT\n"
        "/change Я USDT TON 100 — обменять 100 USDT на TON (по рынку)\n"
        "/change Я USDT TON 100 25 — то же, получил ровно 25 TON\n"
        "/change Я TON USDT 25 — обратно в USDT\n"
        "/wd Я TON 25 3000 — продал 25 TON за 3000 ₽\n"
        "/undo — отменить последнюю операцию"
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


def chart_url(person, coins_rub):
    cfg = {
        "type": "pie",
        "data": {"labels": [f"{c} {rub(v)}" for c, v in coins_rub.items()],
                 "datasets": [{"data": [round(v) for v in coins_rub.values()]}]},
        "options": {"plugins": {"title": {
            "display": True, "text": f"{person}: {rub(sum(coins_rub.values()))}"}}},
    }
    return ("https://quickchart.io/chart?v=3&w=500&h=420&bkg=white&c="
            + quote(json.dumps(cfg, ensure_ascii=False)))


async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    people = load()["people"]
    if not people:
        await update.message.reply_text("Пока нет данных. Админ добавляет: /dep Я 10000 125")
        return
    try:
        prices = await get_prices()
    except Exception:
        await update.message.reply_text("Не удалось получить курс монет, попробуй позже.")
        return

    rows = {}
    for name, p in people.items():
        r = avg_rate(p)
        usd = {c: v * usd_price(prices, c) for c, v in p["coins"].items() if v > EPS}
        rows[name] = {"p": p, "rate": r, "usd": usd, "usd_total": sum(usd.values())}

    pool_usd = sum(x["usd_total"] for x in rows.values())
    sum_in = sum(p["rub_in"] for p in people.values())
    sum_bought = sum(p["usdt_bought"] for p in people.values())
    all_rate = sum_in / sum_bought if sum_bought > EPS else 0
    all_value = all_profit = 0.0

    lines = ["📊 Статистика (в рублях по ср. курсу покупки $)"]
    for name, x in rows.items():
        p, r = x["p"], x["rate"]
        value = x["usd_total"] * r
        profit = value + p["rub_out"] - p["rub_in"]
        all_value += value
        all_profit += profit
        share = f" · доля {x['usd_total'] / pool_usd * 100:.1f}%" if pool_usd > EPS else ""
        lines.append(f"\n{name}{share}")
        lines.append(f"Внесено {rub(p['rub_in'])}, выведено {rub(p['rub_out'])}")
        lines.append(f"Ср. курс $: {r:.2f} ₽")
        lines.append(f"Портфель: ${x['usd_total']:,.2f} ≈ {rub(value)}")
        lines.append(f"Итог: {rub(profit, sign=True)}")
        for c, u in x["usd"].items():
            lines.append(f"  • {c}: {q(p['coins'][c])} ≈ {rub(u * r)}")
    lines.append(f"\nВместе: портфель {rub(all_value)}, итог {rub(all_profit, sign=True)}")
    if all_rate:
        lines.append(f"Общий ср. курс $: {all_rate:.2f} ₽")
    await update.message.reply_text("\n".join(lines))

    # Telegram сам скачивает картинки по ссылке — бот памяти не тратит
    urls = [(n, chart_url(n, {c: u * x["rate"] for c, u in x["usd"].items()}))
            for n, x in rows.items() if x["usd"] and x["rate"]]
    if not urls:
        return
    try:
        if len(urls) == 1:
            await update.message.reply_photo(urls[0][1])
        else:
            await update.message.reply_media_group(
                [InputMediaPhoto(u, caption=n) for n, u in urls[:10]])
    except Exception:
        await update.message.reply_text("Не удалось построить диаграммы (QuickChart недоступен).")


# ---------- админские команды ----------
async def dep(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/dep Я 10000 125  — внёс 10000 ₽, купил 125 USDT"""
    if not await is_admin(update):
        return
    try:
        if len(ctx.args) != 3:
            raise ValueError
        name, rub_amt, usdt = norm_name(ctx.args[0]), num(ctx.args[1]), num(ctx.args[2])
    except ValueError:
        await update.message.reply_text("Формат: /dep Я 10000 125\n(рубли, потом сколько USDT получилось)")
        return
    d = load()
    snapshot(d)
    p = person_of(d, name)
    p["rub_in"] += rub_amt
    p["usdt_bought"] += usdt
    p["coins"]["USDT"] = p["coins"].get("USDT", 0.0) + usdt
    save(d)
    await update.message.reply_text(
        f"✅ Депозит: {name} +{rub(rub_amt)} → {q(usdt)} USDT\n"
        f"Курс этой покупки: {rub_amt / usdt:.2f} ₽/$\n"
        f"Средний курс {name}: {avg_rate(p):.2f} ₽/$")


async def change(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/change Я USDT TON 100 [25] — обмен монеты на монету"""
    if not await is_admin(update):
        return
    a = ctx.args
    try:
        if len(a) not in (4, 5):
            raise ValueError
        name, src, dst = norm_name(a[0]), norm_coin(a[1]), norm_coin(a[2])
        amt = num(a[3])
        got = num(a[4]) if len(a) == 5 else None
        if src == dst:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "Формат: /change Я USDT TON 100\nили с точным результатом: /change Я USDT TON 100 25\n"
            "Монеты: USDT, XAUT, BTC, TON")
        return
    d = load()
    have = balance(d, name, src)
    if amt > have * (1 + EPS) + EPS:
        await update.message.reply_text(f"У {name} только {q(have)} {src}.")
        return
    amt = min(amt, have)
    auto = got is None
    if auto:
        try:
            pr = await get_prices()
        except Exception:
            await update.message.reply_text(
                "Рыночный курс недоступен — укажи сколько получил: /change Я USDT TON 100 25")
            return
        got = amt * usd_price(pr, src) / usd_price(pr, dst)
    snapshot(d)
    c = person_of(d, name)["coins"]
    c[src] = max(c.get(src, 0.0) - amt, 0.0)
    if c[src] < EPS:
        c[src] = 0.0
    c[dst] = c.get(dst, 0.0) + got
    save(d)
    await update.message.reply_text(
        f"🔄 {name}: {q(amt)} {src} → {q(got)} {dst}\n"
        f"1 {dst} = {q(round(amt / got, 6))} {src}" + (" (по рынку)" if auto else ""))


async def wd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/wd Я TON 25 3000 — продал 25 TON за 3000 ₽"""
    if not await is_admin(update):
        return
    try:
        if len(ctx.args) != 4:
            raise ValueError
        name, coin = norm_name(ctx.args[0]), norm_coin(ctx.args[1])
        amt, rub_amt = num(ctx.args[2]), num(ctx.args[3])
    except ValueError:
        await update.message.reply_text("Формат: /wd Я TON 25 3000\n(монета, сколько продал, сколько рублей получил)")
        return
    d = load()
    have = balance(d, name, coin)
    if amt > have * (1 + EPS) + EPS:
        await update.message.reply_text(f"У {name} только {q(have)} {coin}.")
        return
    amt = min(amt, have)
    snapshot(d)
    p = person_of(d, name)
    p["coins"][coin] = max(have - amt, 0.0)
    if p["coins"][coin] < EPS:
        p["coins"][coin] = 0.0
    p["rub_out"] += rub_amt
    save(d)
    await update.message.reply_text(
        f"💸 Вывод: {name} продал {q(amt)} {coin} за {rub(rub_amt)}\n"
        f"Это {rub_amt / amt:.2f} ₽ за 1 {coin}")


async def undo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return
    d = load()
    if d["prev"] is None:
        await update.message.reply_text("Нечего отменять.")
        return
    d["people"], d["prev"] = d["prev"], None
    save(d)
    await update.message.reply_text("↩️ Последняя операция отменена.")


def main():
    app = Application.builder().token(TOKEN).build()
    for n, fn in [("start", start), ("course", course), ("stats", stats), ("dep", dep),
                  ("change", change), ("wd", wd), ("undo", undo)]:
        app.add_handler(CommandHandler(n, fn))
    app.run_polling()


if __name__ == "__main__":
    main()
