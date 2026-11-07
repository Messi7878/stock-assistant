# -*- coding: utf-8 -*-
"""AI 分析层:技术指标 + 单股诊断 + 组合诊断 + 风险提示。

全部基于本地计算(均线/ MACD / RSI / 布林 / 量能),不依赖外部 API,
所以离线也能跑。诊断结果输出为结构化 dict,便于后续接大模型做自然语言解读。
"""
import pandas as pd

from . import data

# ------------------------- 技术指标 -------------------------


def to_df(klines):
    df = pd.DataFrame(klines)
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "close", "high", "low", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _sma(series, n):
    return series.rolling(n).mean()


def macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


def rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def bollinger(close, n=20, k=2):
    mid = close.rolling(n).mean()
    std = close.rolling(n).std(ddof=0)
    return mid + k * std, mid, mid - k * std


# ------------------------- 单股诊断 -------------------------


def stock_diagnosis(code, kline_limit=120):
    """对单只股票做技术面诊断,返回结构化 dict。"""
    ks = data.daily_kline(code, limit=kline_limit)
    if len(ks) < 20:
        return {"code": code, "error": "历史数据不足"}

    df = to_df(ks)
    close = df["close"]
    last = ks[-1]
    price = float(last["close"])

    ma5 = _sma(close, 5).iloc[-1]
    ma10 = _sma(close, 10).iloc[-1]
    ma20 = _sma(close, 20).iloc[-1]
    ma60 = _sma(close, 60).iloc[-1] if len(ks) >= 60 else None

    # 趋势
    if ma5 > ma10 > ma20:
        trend = "多头排列(短期强势)"
    elif ma5 < ma10 < ma20:
        trend = "空头排列(短期弱势)"
    else:
        trend = "均线纠缠(震荡)"

    # MACD
    dif, dea, hist = macd(close)
    macd_state = "金叉/多头动能" if dif.iloc[-1] > dea.iloc[-1] else "死叉/空头动能"

    # RSI
    rsi_val = float(rsi(close).iloc[-1])
    if rsi_val > 70:
        rsi_state = "超买"
    elif rsi_val < 30:
        rsi_state = "超卖"
    else:
        rsi_state = "中性"

    # 量能(当日 vs 20 日均量)
    vol_avg20 = df["volume"].rolling(20).mean().iloc[-1]
    vol_ratio = float(last["volume"] / vol_avg20) if vol_avg20 else None

    # 近 60 日位置
    high60 = float(df["high"].tail(60).max())
    low60 = float(df["low"].tail(60).min())
    pos60 = (price - low60) / (high60 - low60) * 100 if high60 > low60 else None

    # 风险/机会旗标
    flags = []
    notes = []
    if ma60 is not None:
        if price < ma60:
            flags.append("股价低于 60 日均线,中期趋势偏弱")
        else:
            notes.append("股价站稳 60 日均线之上")
    if rsi_val > 70:
        flags.append(f"RSI={rsi_val:.0f},超买,短线谨防回调")
    elif rsi_val < 30:
        flags.append(f"RSI={rsi_val:.0f},超卖,存在超跌反弹可能")
    if vol_ratio is not None and vol_ratio >= 2.0:
        flags.append(f"今日放量 {vol_ratio:.1f} 倍,关注资金异动")
    if pos60 is not None and pos60 > 90:
        flags.append("股价接近 60 日新高,追高需谨慎")
    if pos60 is not None and pos60 < 10:
        notes.append("股价接近 60 日新低,关注是否超跌")

    return {
        "code": code,
        "name": _name(code),
        "date": last["date"],
        "price": price,
        "change_pct": float(last["change_pct"]),
        "trend": trend,
        "ma5": round(float(ma5), 2),
        "ma10": round(float(ma10), 2),
        "ma20": round(float(ma20), 2),
        "ma60": round(float(ma60), 2) if ma60 is not None else None,
        "macd": macd_state,
        "rsi": round(rsi_val, 1),
        "rsi_state": rsi_state,
        "volume_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
        "pos_60d_pct": round(pos60, 1) if pos60 is not None else None,
        "flags": flags,
        "notes": notes,
    }


def _name(code):
    q = data.realtime_quotes([code])
    return q[0]["name"] if q else code


# ------------------------- 组合诊断 -------------------------


def portfolio_diagnosis(positions, kline_limit=120):
    """对持仓组合做整体诊断。

    positions: list[{code, name, shares, cost}]
    返回 dict:{positions:[{...诊断+盈亏...}], summary:{...}}
    """
    codes = [p["code"] for p in positions]
    quotes = {q["code"]: q for q in data.realtime_quotes(codes)}

    diags = []
    total_cost = total_mv = 0.0
    for p in positions:
        q = quotes.get(p["code"], {})
        d = stock_diagnosis(p["code"], kline_limit=kline_limit)
        shares = float(p["shares"])
        cost = float(p["cost"])
        price = float(q.get("price") or 0)
        pnl = (price - cost) * shares if price else None
        pnl_pct = (price - cost) / cost * 100 if (price and cost) else None
        if price:
            total_cost += cost * shares
            total_mv += price * shares
        diags.append({
            "code": p["code"],
            "name": q.get("name") or p.get("name") or p["code"],
            "shares": shares,
            "cost": cost,
            "price": price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "diagnosis": d,
        })

    # 组合层风险
    summary_flags = []
    if total_cost:
        total_pnl_pct = (total_mv - total_cost) / total_cost * 100
        for d in diags:
            if d["price"]:
                mv = d["price"] * d["shares"]
                weight = mv / total_mv * 100 if total_mv else 0
                if weight > 50:
                    summary_flags.append(f"{d['name']}({d['code']})占比 {weight:.0f}%,集中度过高")
        worst = min(diags, key=lambda x: x["pnl_pct"] if x["pnl_pct"] is not None else 0)
        summary_flags.append(f"最大亏损持仓:{worst['name']} {worst['pnl_pct']:+.2f}%")
    else:
        total_pnl_pct = 0.0

    return {
        "positions": diags,
        "summary": {
            "total_cost": round(total_cost, 2),
            "total_mv": round(total_mv, 2),
            "total_pnl": round(total_mv - total_cost, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "flags": summary_flags,
        },
    }
