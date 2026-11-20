"""Реестр монет (data/coins.json) и поиск новых монет на CoinGecko."""
import copy
import re

import httpx

from config import BASE_COIN, COINS_FILE
from storage import read_json, write_json

API = "https://api.coingecko.com/api/v3"

# Монеты по умолчанию — записываются в coins.json при первом запуске
DEFAULT = {
    "coins": {
        "USDT": {"id": "tether", "name": "Tether"},
        "XAUT": {"id": "tether-gold", "name": "Tether Gold"},
        "BTC": {"id": "bitcoin", "name": "Bitcoin"},
        "TON": {"id": "the-open-network", "name": "Toncoin"},
        "TSTON": {"id": "tonstakers", "name": "Tonstakers"},
    },
    "aliases": {"GRAM": "TON"},
}


def _load():
    d = read_json(COINS_FILE)
    if not d or "coins" not in d:
        d = copy.deepcopy(DEFAULT)
        write_json(COINS_FILE, d)
    d.setdefault("aliases", {})
    return d


def all_coins():
    """{'TON': {'id': 'the-open-network', 'name': 'Toncoin'}, ...}"""
    return _load()["coins"]


def norm_coin(x):
    d = _load()
    c = d["aliases"].get(x.upper(), x.upper())
    if c not in d["coins"]:
        raise ValueError
    return c


def add_coin(cg_id, symbol, name):
    """Добавляет монету, возвращает тикер. ValueError с текстом, если нельзя."""
    ticker = re.sub(r"[^A-Z0-9]", "", symbol.upper())
    if not ticker:
        raise ValueError("У монеты нет подходящего тикера.")
    d = _load()
    if ticker in d["coins"] or ticker in d["aliases"]:
        raise ValueError(f"Тикер {ticker} уже занят другой монетой.")
    for t, c in d["coins"].items():
        if c["id"] == cg_id:
            raise ValueError(f"Эта монета уже добавлена как {t}.")
    d["coins"][ticker] = {"id": cg_id, "name": name}
    write_json(COINS_FILE, d)
    return ticker


def remove_coin(ticker):
    d = _load()
    if ticker == BASE_COIN:
        raise ValueError(f"{BASE_COIN} удалить нельзя — в неё идут депозиты.")
    if ticker not in d["coins"]:
        raise ValueError("Такой монеты нет.")
    del d["coins"][ticker]
    d["aliases"] = {a: t for a, t in d["aliases"].items() if t != ticker}
    write_json(COINS_FILE, d)


async def search(query):
    """До 5 вариантов с CoinGecko: [{'id','name','symbol','rank'}, ...]"""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API}/search", params={"query": query})
    r.raise_for_status()
    return [{"id": x["id"], "name": x["name"], "symbol": x["symbol"],
             "rank": x.get("market_cap_rank")} for x in r.json().get("coins", [])[:5]]


async def fetch_price(cg_id):
    """Цена в $ или None, если у монеты нет цены."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{API}/simple/price", params={"ids": cg_id, "vs_currencies": "usd"})
    r.raise_for_status()
    return r.json().get(cg_id, {}).get("usd")
