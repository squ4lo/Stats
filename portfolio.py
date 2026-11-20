"""Данные о вложениях (data/portfolio.json)."""
import copy

from config import EPS, LEGACY_FILE, PORTFOLIO_FILE
from storage import read_json, write_json


def load():
    d = read_json(PORTFOLIO_FILE)
    if d is None:
        d = read_json(LEGACY_FILE)  # перенос из старого data.json
    if not d or "people" not in d:
        d = {"people": {}, "prev": None}
    return d


def save(d):
    write_json(PORTFOLIO_FILE, d)


def person_of(d, name):
    return d["people"].setdefault(
        name, {"rub_in": 0.0, "usdt_bought": 0.0, "rub_out": 0.0, "usd_out": 0.0, "coins": {}})


def balance(d, name, coin):
    return d["people"].get(name, {}).get("coins", {}).get(coin, 0.0)


def snapshot(d):
    d["prev"] = copy.deepcopy(d["people"])  # одна копия — для /undo


def avg_rate(p):
    return p["rub_in"] / p["usdt_bought"] if p["usdt_bought"] > EPS else 0.0


def holders(coin):
    """Имена людей, у которых есть эта монета."""
    return [n for n, p in load()["people"].items() if p["coins"].get(coin, 0) > EPS]
