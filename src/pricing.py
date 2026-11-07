# -*- coding: utf-8 -*-
"""保守多因子定价。

在技术面(均线/布林/筹码)基础上,额外加入:
  - 波动率 ATR 自适应(止损按波动放大,避免被噪声扫掉)
  - 多因子打分 + 门控(趋势/动量/量能/位置/大盘/波动)
  - 风险预算仓位(每笔只亏总资金的固定比例)
  - 风险回报比目标价(2R / 3R)

注意:这是"更保守、更讲纪律"的参考,不保证盈利,不构成投资建议。
新闻/公告没有可靠的免费结构化接口,本模块不含新闻变量;可在 LLM 解读里人工补充。
"""
import pandas as pd

from . import data, market
from .analysis import bollinger, macd, rsi, to_df


def _atr(df, n=14):
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])


def conservative_plan(code, total_capital=0, risk_pct=0.015, max_pos_pct=0.30):
    q = data.realtime_quotes([code])
    name = q[0]["name"] if q else code
    rq_price = q[0].get("price") if q else None

    ks = data.daily_kline(code, limit=250, adjust="qfq")
    if len(ks) < 60:
        return {"code": code, "name": name, "error": "历史数据不足(需 60 个交易日以上)"}
    df = to_df(ks)
    close = df["close"]
    price = float(rq_price) if rq_price else float(close.iloc[-1])

    ma5 = float(close.rolling(5).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1])
    ma120 = float(close.rolling(120).mean().iloc[-1]) if len(close) >= 120 else None
    atr = _atr(df, 14)
    atr_pct = atr / price * 100 if price else 0.0

    up, mid, low = bollinger(close, 20, 2)
    boll_low = float(low.iloc[-1])

    low20 = float(df["low"].tail(20).min())
    low60 = float(df["low"].tail(60).min())
    high60 = float(df["high"].tail(60).max())

    rsi_val = float(rsi(close).iloc[-1])
    dif, dea, hist = macd(close)
    macd_gold = float(dif.iloc[-1]) > float(dea.iloc[-1])
    vol_avg = float(df["volume"].rolling(20).mean().iloc[-1])
    vol_ratio = float(df["volume"].iloc[-1]) / vol_avg if vol_avg else 0.0

    env = market.market_env()
    trends = [i["trend"] for i in env.get("indices", [])]
    strong = trends.count("强势")
    weak = trends.count("弱势")

    # ---------- 多因子打分 ----------
    score = 0
    reasons = []
    if ma5 > ma20 > ma60:
        score += 30
        reasons.append("均线多头排列(+30)")
    elif ma20 > ma60 and price > ma60:
        score += 15
        reasons.append("中期趋势向上(+15)")
    elif ma20 > ma60:
        score += 5
        reasons.append("20日线在60日线上方,但价格已跌破(趋势待修复,+5)")
    if price > ma60:
        score += 10
        reasons.append("站上60日线(+10)")
    if macd_gold:
        score += 8
        reasons.append("MACD金叉(+8)")
    if 40 <= rsi_val <= 65:
        score += 10
        reasons.append(f"RSI {rsi_val:.0f} 健康(+10)")
    elif rsi_val > 75:
        score -= 8
        reasons.append(f"RSI {rsi_val:.0f} 超买(-8)")
    if 1.0 <= vol_ratio <= 2.5:
        score += 7
        reasons.append(f"量能 {vol_ratio:.1f} 倍(+7)")
    pos60 = (price - low60) / (high60 - low60) * 100 if high60 > low60 else 50.0
    if pos60 > 90:
        score -= 8
        reasons.append("接近60日新高(-8)")
    if atr_pct <= 5:
        score += 5
        reasons.append(f"波动 ATR {atr_pct:.1f}% 温和(+5)")
    elif atr_pct > 8:
        score -= 5
        reasons.append(f"波动 ATR {atr_pct:.1f}% 偏大(-5)")
    if strong >= 2:
        score += 15
        reasons.append("大盘偏强(+15)")
    elif weak >= 2:
        score -= 10
        reasons.append("大盘偏弱(-10)")

    # ---------- 门控 ----------
    bearish = (ma5 < ma20) and (price < ma60)
    if bearish and weak >= 2:
        stance = "暂不建议做多:个股与大盘双弱,等趋势改善"
    elif rsi_val > 75:
        stance = "不追高:等回踩支撑再考虑"
    elif ma5 > ma20 > ma60 and price > ma60:
        stance = "可持有 / 回踩关注"
    else:
        stance = "观望为主"

    # ---------- 保守定价 ----------
    cand = [x for x in (low20, boll_low, ma60) if x is not None and x < price]
    structural = max(cand) if cand else price - 2 * atr

    buy_low = round(structural - 0.5 * atr, 2)
    buy_high = round(structural + 0.5 * atr, 2)
    entry = buy_high                          # 保守:以区间上沿作入场参考

    # 止损:结构支撑下方 1 ATR;钳制在入场价下方 4%~12%;且必须低于结构支撑
    stop = structural - 1.0 * atr
    stop = max(stop, entry * 0.88)            # 最远 -12%
    stop = min(stop, entry * 0.96)            # 最近 -4%
    stop = min(stop, structural * 0.995)      # 必须低于结构支撑
    stop = round(stop, 2)

    risk = round(entry - stop, 2)
    stop_pct = round(risk / entry * 100, 2) if entry else None

    target1 = round(entry + 2 * risk, 2) if risk > 0 else None   # 2R
    target2 = round(entry + 3 * risk, 2) if risk > 0 else None   # 3R

    # ---------- 风险预算仓位 ----------
    shares = None
    position_value = None
    sizing_note = None
    risk_budget = round((total_capital or 0) * risk_pct, 2) if total_capital else None
    if total_capital and total_capital > 0 and risk > 0:
        by_risk = risk_budget / risk
        by_cap = total_capital * max_pos_pct / entry
        shares = int(min(by_risk, by_cap) // 100 * 100)   # A股按手(100股)
        if shares < 100:
            shares = 0
            sizing_note = (f"按 {risk_pct * 100:.1f}% 风险预算({risk_budget:,.0f}元)不足 1 手;"
                           f"若买 100 股,单笔风险约 {100 * risk:,.0f} 元"
                           f"(占总资金 {100 * risk / total_capital * 100:.1f}%)")
        else:
            position_value = round(shares * entry, 2)

    return {
        "code": code, "name": name, "price": round(price, 2),
        "date": ks[-1]["date"],
        "score": score, "stance": stance, "reasons": reasons,
        "atr": round(atr, 2), "atr_pct": round(atr_pct, 2),
        "ma20": round(ma20, 2), "ma60": round(ma60, 2),
        "rsi": round(rsi_val, 1), "macd_gold": macd_gold,
        "vol_ratio": round(vol_ratio, 2),
        "structural": round(structural, 2),
        "buy_range": [buy_low, buy_high],
        "stop": stop, "stop_pct": stop_pct,
        "target1": target1, "target2": target2,
        "rr": 2.0 if risk > 0 else None,
        "shares": shares, "position_value": position_value,
        "risk_budget": risk_budget, "sizing_note": sizing_note,
        "market_trends": trends,
    }
