# -*- coding: utf-8 -*-
"""交易参考计划:支撑/压力位 + 买入/卖出区间 + 止损位 + 触发信号。

全部由技术指标计算而来(均线、布林带、近期高低点、简版筹码分布),
是可复现的"参考价位",不是预测、不构成投资建议。
"""
import numpy as np

from . import data
from .analysis import to_df, macd, rsi, bollinger


def _round(x, nd=2):
    return round(float(x), nd)


def chip_density_peak(df, days=120, bins=120):
    """简版筹码分布:近 N 日成交量按三角分布摊到 [low,high],峰值在收盘价。

    返回成交最密集的价位(成本密集区),是重要的支撑/压力参考。
    """
    d = df.tail(days)
    low = float(d["low"].min())
    high = float(d["high"].max())
    if high <= low:
        return None
    hist = np.zeros(bins)
    edges = np.linspace(low, high, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    width = (high - low) / bins

    for lo, hi, vol, c in zip(d["low"], d["high"], d["volume"], d["close"]):
        lo, hi, vol, c = float(lo), float(hi), float(vol), float(c)
        if hi <= lo or vol <= 0:
            continue
        span = hi - lo
        # 三角形权重:离收盘价越近权重越高
        w = np.maximum(0.0, 1.0 - np.abs(centers - c) / span)
        mask = (centers >= lo) & (centers <= hi)
        hist += w * mask * vol

    total = hist.sum()
    if total <= 0:
        return None
    peak_bin = int(np.argmax(hist))
    return float(centers[peak_bin])


def _candidate_levels(df, chip_peak):
    close = df["close"]
    price = float(close.iloc[-1])
    ma = lambda n: float(close.rolling(n).mean().iloc[-1]) if len(close) >= n else None
    up, mid, low = bollinger(close, 20, 2)
    return {
        "20日均线": ma(20),
        "60日均线": ma(60),
        "120日均线": ma(120),
        "布林上轨": float(up.iloc[-1]),
        "布林下轨": float(low.iloc[-1]),
        "近20日低点": float(df["low"].tail(20).min()),
        "近20日高点": float(df["high"].tail(20).max()),
        "近60日低点": float(df["low"].tail(60).min()),
        "近60日高点": float(df["high"].tail(60).max()),
        "筹码密集区": chip_peak,
    }


def trade_plan(code, kline_limit=250):
    """生成单只股票的交易参考计划(结构化 dict)。"""
    ks = data.daily_kline(code, limit=kline_limit, adjust="qfq")
    if len(ks) < 30:
        return {"code": code, "error": "历史数据不足"}

    q = data.realtime_quotes([code])
    name = q[0]["name"] if q else code
    rq_price = q[0].get("price") if q else None

    df = to_df(ks)
    close = df["close"]
    price = float(rq_price) if rq_price is not None else float(close.iloc[-1])
    ma5 = float(close.rolling(5).mean().iloc[-1])
    ma10 = float(close.rolling(10).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else None

    chip_peak = chip_density_peak(df, 120)
    levels = _candidate_levels(df, chip_peak)

    supports, resistances = [], []
    for label, p in levels.items():
        if p is None or not np.isfinite(p):
            continue
        p = _round(p)
        if p < price:
            supports.append({"price": p, "label": label,
                             "distance_pct": _round((p - price) / price * 100)})
        elif p > price:
            resistances.append({"price": p, "label": label,
                                "distance_pct": _round((p - price) / price * 100)})
    supports.sort(key=lambda x: -x["price"])     # 离现价最近的支撑在前
    resistances.sort(key=lambda x: x["price"])   # 离现价最近的压力在前

    # 参考买卖区间 / 止损
    nearest_support = supports[0]["price"] if supports else None
    nearest_resistance = resistances[0]["price"] if resistances else None
    buy_range = [_round(nearest_support * 0.98), _round(nearest_support * 1.03)] if nearest_support else None
    sell_range = [_round(nearest_resistance * 0.97), _round(nearest_resistance * 1.02)] if nearest_resistance else None
    stop_loss = _round(nearest_support * 0.97) if nearest_support else None

    # 指标与信号
    rsi_val = float(rsi(close).iloc[-1])
    dif, dea, hist = macd(close)
    macd_state = "金叉/多头动能" if dif.iloc[-1] > dea.iloc[-1] else "死叉/空头动能"
    vol_avg20 = float(df["volume"].rolling(20).mean().iloc[-1])
    vol_ratio = _round(float(ks[-1]["volume"]) / vol_avg20, 2) if vol_avg20 else None

    trend = "多头排列" if ma5 > ma10 > ma20 else ("空头排列" if ma5 < ma10 < ma20 else "震荡")
    signals = []
    if rsi_val > 70:
        signals.append(f"RSI={rsi_val:.0f} 超买,接近压力位可考虑分批卖出")
    elif rsi_val < 30:
        signals.append(f"RSI={rsi_val:.0f} 超卖,接近支撑位可关注")
    else:
        signals.append(f"RSI={rsi_val:.0f} 中性")
    if ma60 is not None:
        signals.append("股价在60日线上方" if price >= ma60 else "股价在60日线下方(中期偏弱)")
    if vol_ratio is not None and vol_ratio >= 2:
        signals.append(f"今日放量 {vol_ratio} 倍,注意资金异动")

    return {
        "code": code, "name": name, "date": ks[-1]["date"],
        "price": _round(price),
        "trend": trend, "macd": macd_state, "rsi": _round(rsi_val, 1),
        "volume_ratio": vol_ratio,
        "supports": supports[:4],
        "resistances": resistances[:4],
        "buy_range": buy_range,
        "sell_range": sell_range,
        "stop_loss": stop_loss,
        "signals": signals,
    }
