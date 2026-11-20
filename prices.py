"""Цены монет и курс доллара к рублю (всё с CoinGecko, кеш 60 секунд)."""
import time

import httpx

import coins

_cache = {"ts": 0, "data": None, "usd_rub": None}


def invalidate():
    """Сбросить кеш (после добавления/удаления монеты)."""
    _cache.update(ts=0, data=None, usd_rub=None)


async def get_prices():
    """{'TON': (цена_в_$, изменение_за_24ч), ...}. Монеты без цены в словарь не попадают."""
    if _cache["data"] and _cache["usd_rub"] and time.time() - _cache["ts"] < 60:
        return _cache["data"]
    ids = {t: c["id"] for t, c in coins.all_coins().items()}
    query = ",".join(set(ids.values()) | {"tether"})
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{coins.API}/simple/price",
                        params={"ids": query, "vs_currencies": "usd,rub",
                                "include_24hr_change": "true"})
    r.raise_for_status()
    j = r.json()
    data = {t: (j[i]["usd"], j[i].get("usd_24h_change") or 0)
            for t, i in ids.items() if i in j and "usd" in j[i]}
    usd_rub = j["tether"]["rub"] / j["tether"]["usd"]  # 1 USDT = $1 в рублях
    _cache.update(ts=time.time(), data=data, usd_rub=usd_rub)
    return data


async def get_usd_rub():
    await get_prices()
    return _cache["usd_rub"]


def usd_price(prices, coin):
    """Цена монеты в $ (None, если цены нет)."""
    if coin == "USDT":
        return 1.0
    return prices[coin][0] if coin in prices else None
