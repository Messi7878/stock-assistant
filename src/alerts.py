# -*- coding: utf-8 -*-
"""提醒模块:涨跌幅异动、放量、价格触发,并支持按重要程度分级。

scan() 返回 list[dict],每条含 kind/level/value/message;
classify() 把结果分成 重要(critical)/ 一般(info) 两档。
"""
from . import data


def scan(codes, price_alerts=None, change_pct_threshold=3.0, vol_spike_ratio=2.0):
    """扫描一组代码,返回触发的提醒列表。

    price_alerts: list[{code, above?, below?}],above=上破价,below=下破价。
    """
    results = []
    quotes = {q["code"]: q for q in data.realtime_quotes(codes)}

    # 1) 涨跌幅异动
    for code in codes:
        q = quotes.get(code)
        if not q:
            continue
        chg = q.get("change_pct")
        if chg is not None and abs(chg) >= change_pct_threshold:
            direction = "上涨" if chg > 0 else "下跌"
            results.append({
                "code": code, "name": q["name"], "kind": "涨跌幅异动", "level": "warn",
                "value": round(float(chg), 2),
                "message": f"{q['name']}({code}) 今日{direction} {chg:+.2f}%,现价 {q['price']}",
            })

    # 2) 放量(当日量 vs 前 20 日均量)
    for code in codes:
        q = quotes.get(code)
        try:
            ks = data.daily_kline(code, limit=30)
        except Exception:  # noqa: BLE001
            continue
        if len(ks) < 21:
            continue
        vol_today = ks[-1]["volume"]
        avg = sum(k["volume"] for k in ks[-21:-1]) / 20
        if avg and vol_today / avg >= vol_spike_ratio:
            ratio = vol_today / avg
            results.append({
                "code": code, "name": q.get("name") if q else code, "kind": "放量",
                "level": "info", "value": round(ratio, 2),
                "message": f"{q.get('name') if q else code}({code}) 今日成交量为 20 日均量 {ratio:.1f} 倍",
            })

    # 3) 价格触发
    for pa in (price_alerts or []):
        code = str(pa.get("code", "")).strip()
        q = quotes.get(code)
        if not q or q.get("price") is None:
            continue
        price = float(q["price"])
        if pa.get("above") is not None and price >= float(pa["above"]):
            results.append({
                "code": code, "name": q["name"], "kind": "价格触发", "level": "warn",
                "value": price,
                "message": f"{q['name']}({code}) 现价 {price} 已上破目标价 {pa['above']}",
            })
        if pa.get("below") is not None and price <= float(pa["below"]):
            results.append({
                "code": code, "name": q["name"], "kind": "价格触发", "level": "warn",
                "value": price,
                "message": f"{q['name']}({code}) 现价 {price} 已下破目标价 {pa['below']}",
            })

    return results


def classify(alerts_list, critical_change_pct=5.0):
    """按重要程度分档:价格触发 / 大幅异动 -> critical,其余 -> info。"""
    crit, info = [], []
    for a in alerts_list:
        if a.get("kind") == "价格触发":
            crit.append(a)
        elif a.get("kind") == "涨跌幅异动" and abs(a.get("value") or 0) >= critical_change_pct:
            crit.append(a)
        else:
            info.append(a)
    return {"critical": crit, "info": info}
