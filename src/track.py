# -*- coding: utf-8 -*-
"""推荐胜率复盘:记录每日推荐,回看 N 个交易日后的涨跌,统计真实胜率。

记录存在 picks_history.json,复盘时用历史 K 线计算"推荐日之后第 N 个交易日"的收益。
"""
import datetime
import json
import os

from . import data

HIST_FILE = "picks_history.json"


def _path(base_dir):
    return os.path.join(base_dir, HIST_FILE)


def load_history(base_dir):
    path = _path(base_dir)
    if not os.path.exists(path):
        return {"records": []}
    try:
        with open(path, encoding="utf-8") as f:
            hist = json.load(f)
        hist.setdefault("records", [])
        return hist
    except (json.JSONDecodeError, OSError):
        return {"records": []}


def save_history(base_dir, hist):
    with open(_path(base_dir), "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)


def record_picks(base_dir, picks, date=None):
    """把当日推荐写入历史(按 日期+代码 去重),返回新增条数。"""
    date = date or datetime.date.today().isoformat()
    hist = load_history(base_dir)
    existing = {(r.get("date"), r.get("code")) for r in hist["records"]}
    added = 0
    for p in picks:
        key = (date, p.get("code"))
        if key in existing:
            continue
        hist["records"].append({
            "date": date,
            "code": p.get("code"),
            "name": p.get("name"),
            "price": p.get("price"),
            "score": p.get("score"),
            "industry": p.get("industry"),
        })
        added += 1
    if added:
        save_history(base_dir, hist)
    return added


def evaluate(base_dir, horizons=(5, 10)):
    """回看推荐结果,返回 {summary: {h: {...}}, detail: [...], total: n}。"""
    records = load_history(base_dir).get("records", [])
    by_code = {}
    for r in records:
        if r.get("code") and r.get("price"):
            by_code.setdefault(r["code"], []).append(r)

    results = []
    for code, recs in by_code.items():
        try:
            ks = data.daily_kline(code, limit=250)
        except Exception:  # noqa: BLE001
            continue
        dates = [k["date"] for k in ks]
        for r in recs:
            if r["date"] not in dates:
                continue
            i = dates.index(r["date"])
            row = {"date": r["date"], "code": code, "name": r.get("name"),
                   "rec_price": r.get("price"), "score": r.get("score"),
                   "industry": r.get("industry"), "returns": {}}
            for h in horizons:
                j = i + h
                if j < len(ks):
                    row["returns"][str(h)] = round(
                        (float(ks[j]["close"]) / float(r["price"]) - 1) * 100, 2)
            if row["returns"]:
                results.append(row)

    summary = {}
    for h in horizons:
        vals = [r["returns"][str(h)] for r in results if str(h) in r["returns"]]
        if vals:
            wins = sum(1 for v in vals if v > 0)
            summary[str(h)] = {
                "n": len(vals),
                "win_rate": round(wins / len(vals) * 100, 1),
                "avg_return": round(sum(vals) / len(vals), 2),
                "best": max(vals),
                "worst": min(vals),
            }
    results.sort(key=lambda x: x["date"], reverse=True)
    return {"summary": summary, "detail": results, "total": len(records)}
