# -*- coding: utf-8 -*-
"""每日推荐:从东财排行接口取候选池,再用技术面打分筛选。

不做全市场逐只爬取(会被封 IP),而是 1~3 次请求拿到候选池,
再对候选(默认 30 只)取 K 线打分,输出前 N 名。
"""
import json
import time

import pandas as pd

from . import data, http

# 东财排行接口有多个镜像,单个 502 时自动换下一个
CLIST_HOSTS = ["1.push2", "7.push2", "82.push2", "push2delay", "push2"]
FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"  # 沪深A股:深主板/创业板/沪主板/科创板


def _parse_clist(d):
    diff = (d.get("data") or {}).get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    out = []
    for it in diff:
        if not it or not it.get("f12"):
            continue
        name = it.get("f14") or ""
        if "ST" in name.upper() or "退" in name:
            continue
        out.append({"code": it["f12"], "name": name, "price": it.get("f2"),
                    "change_pct": it.get("f3"), "main_inflow": it.get("f62"),
                    "industry": it.get("f100")})
    return out


def _sina_rank(size=30):
    """备用候选源:新浪沪深A股涨幅榜。"""
    url = ("http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"Market_Center.getHQNodeData?page=1&num={size}"
           "&sort=changepercent&asc=0&node=hs_a&symbol=")
    arr = json.loads(http.http_get(url, retries=1, timeout=10))
    out = []
    for it in arr or []:
        code, name = it.get("code"), it.get("name") or ""
        if not code or "ST" in name.upper() or "退" in name:
            continue
        out.append({"code": code, "name": name,
                    "price": float(it.get("trade") or 0),
                    "change_pct": float(it.get("changepercent") or 0),
                    "main_inflow": None, "industry": None})
    return out


def _clist(fid, size=30):
    """按 fid 排序取榜单。f62=主力净流入, f3=涨跌幅, f6=成交额。"""
    qs = (f"?pn=1&pz={size}&po=1&np=1&fltt=2&invt=2"
          f"&fid={fid}&fs={FS}&fields=f12,f14,f2,f3,f62,f100")
    for host in CLIST_HOSTS:
        try:
            d = http.http_get_json(f"https://{host}.eastmoney.com/api/qt/clist/get{qs}",
                                   retries=1, timeout=10)
            out = _parse_clist(d)
            if out:
                return out
        except Exception:  # noqa: BLE001
            continue
    return _sina_rank(size)


def candidate_pool(size=30):
    """合并三个榜单去重,得到候选池。"""
    pool = {}
    for fid in ("f62", "f3", "f6"):
        try:
            for it in _clist(fid, size):
                pool.setdefault(it["code"], it)
        except Exception:  # noqa: BLE001
            continue
        time.sleep(0.3)
    return list(pool.values())


def _score(code, kline_limit=120):
    ks = data.daily_kline(code, limit=kline_limit)
    if len(ks) < 60:
        return None
    df = pd.DataFrame(ks)
    c = df["close"]
    price = float(c.iloc[-1])
    ma5 = float(c.rolling(5).mean().iloc[-1])
    ma10 = float(c.rolling(10).mean().iloc[-1])
    ma20 = float(c.rolling(20).mean().iloc[-1])
    ma60 = float(c.rolling(60).mean().iloc[-1])

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_gold = float(dif.iloc[-1]) > float(dea.iloc[-1])

    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    rs = gain.ewm(alpha=1 / 14, adjust=False).mean() / loss.ewm(alpha=1 / 14, adjust=False).mean()
    rsi_val = float((100 - 100 / (1 + rs)).iloc[-1])

    chg20 = (price / float(c.iloc[-21]) - 1) * 100 if len(c) >= 21 else 0.0
    vol_avg = float(df["volume"].rolling(20).mean().iloc[-1])
    vol_ratio = float(df["volume"].iloc[-1]) / vol_avg if vol_avg else 0.0

    score = 0
    reasons = []
    if ma5 > ma10 > ma20:
        score += 2
        reasons.append("均线多头排列")
    if price > ma60:
        score += 2
        reasons.append("站上60日线")
    if macd_gold:
        score += 1
        reasons.append("MACD金叉")
    if 40 <= rsi_val <= 70:
        score += 2
        reasons.append(f"RSI {rsi_val:.0f} 健康")
    elif rsi_val > 80:
        score -= 1
        reasons.append(f"RSI {rsi_val:.0f} 超买")
    if 0 <= chg20 <= 20:
        score += 1
        reasons.append(f"20日涨幅 {chg20:.1f}% 温和")
    elif chg20 > 40:
        score -= 1
        reasons.append(f"20日涨幅 {chg20:.1f}% 过热")
    if 1.0 <= vol_ratio <= 2.5:
        score += 1
        reasons.append(f"量能 {vol_ratio:.1f} 倍")

    return {"score": score, "reasons": reasons, "rsi": round(rsi_val, 1),
            "chg20_pct": round(chg20, 1), "volume_ratio": round(vol_ratio, 2),
            "above_ma60": price > ma60}


def daily_picks(top=6, pool_size=30):
    """返回打分靠前的推荐股票列表。"""
    pool = candidate_pool(pool_size)
    scored = []
    for it in pool:
        try:
            s = _score(it["code"])
        except Exception:  # noqa: BLE001
            s = None
        if s:
            row = dict(it)
            row.update(s)
            scored.append(row)
        time.sleep(0.15)
    scored.sort(key=lambda x: -x["score"])
    return scored[:top]
