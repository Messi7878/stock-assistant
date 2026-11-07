# -*- coding: utf-8 -*-
"""大盘环境判断:三大指数趋势 -> 建议总仓位区间。"""
import json

import pandas as pd

from . import http

INDICES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
]


def _index_kline_sina(symbol, limit=120):
    """新浪指数日线。指数也能用这个接口,且比腾讯稳定。"""
    url = ("https://quotes.sina.cn/cn/api/jsonp_v2.php/var/"
           "CN_MarketDataService.getKLineData"
           f"?symbol={symbol}&scale=240&ma=no&datalen={limit}")
    txt = http.http_get(url)
    start, end = txt.find("["), txt.rfind("]") + 1
    if start == -1 or end <= start:
        return []
    rows = []
    for r in json.loads(txt[start:end]):
        try:
            rows.append({"date": r["day"], "open": float(r["open"]),
                         "close": float(r["close"]), "high": float(r["high"]),
                         "low": float(r["low"]),
                         "volume": float(r.get("volume") or 0)})
        except (KeyError, ValueError, TypeError):
            continue
    return rows


def _index_kline_tencent(symbol, limit=120):
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={symbol},day,,,{limit},qfq")
    d = http.http_get_json(url)
    node = (d.get("data") or {}).get(symbol) or {}
    arr = node.get("qfqday") or node.get("day") or []
    rows = []
    for r in arr:
        if len(r) < 5:
            continue
        rows.append({"date": r[0], "open": float(r[1]), "close": float(r[2]),
                     "high": float(r[3]), "low": float(r[4]),
                     "volume": float(r[5]) if len(r) > 5 else 0.0})
    return rows


def _index_kline(symbol, limit=120):
    for fn in (_index_kline_sina, _index_kline_tencent):
        try:
            rows = fn(symbol, limit)
            if rows:
                return rows
        except Exception:  # noqa: BLE001
            continue
    return []



def _judge(ks):
    c = pd.DataFrame(ks)["close"]
    price = float(c.iloc[-1])
    ma20 = float(c.rolling(20).mean().iloc[-1]) if len(c) >= 20 else None
    ma60 = float(c.rolling(60).mean().iloc[-1]) if len(c) >= 60 else None
    chg20 = (price / float(c.iloc[-21]) - 1) * 100 if len(c) >= 21 else None
    above20 = ma20 is not None and price > ma20
    above60 = ma60 is not None and price > ma60
    trend = "强势" if (above20 and above60) else ("弱势" if (not above20 and not above60) else "震荡")
    return {"price": round(price, 2),
            "ma20": round(ma20, 2) if ma20 else None,
            "ma60": round(ma60, 2) if ma60 else None,
            "chg20_pct": round(chg20, 2) if chg20 is not None else None,
            "trend": trend}


def market_env():
    """返回 {indices, verdict, suggest_position:[lo,hi]}。"""
    indices = []
    for sym, name in INDICES:
        try:
            ks = _index_kline(sym)
            if len(ks) >= 21:
                j = _judge(ks)
                j["name"] = name
                indices.append(j)
        except Exception:  # noqa: BLE001
            continue
    if not indices:
        return {"indices": [], "verdict": "大盘数据获取失败", "suggest_position": None}

    strong = sum(1 for i in indices if i["trend"] == "强势")
    weak = sum(1 for i in indices if i["trend"] == "弱势")
    if strong >= 2:
        lo, hi, verdict = 70, 100, "大盘偏强,可维持较高仓位"
    elif weak >= 2:
        lo, hi, verdict = 0, 40, "大盘偏弱,建议降低仓位、保留现金"
    else:
        lo, hi, verdict = 40, 70, "大盘震荡,建议中等仓位、留有余地"
    return {"indices": indices, "verdict": verdict, "suggest_position": [lo, hi]}
