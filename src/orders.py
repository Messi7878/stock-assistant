# -*- coding: utf-8 -*-
"""条件单参数:根据持仓 + 交易参考,生成可直接录入券商 App 的条件单参数。

券商 App 一般有「条件单 / 智能委托 / 止盈止损单」功能:
  条件是「最新价 >= 触发价(止盈)」或「最新价 <= 触发价(止损)」,
  动作是「卖出 N 股,委托价 = X(限价)或 市价」。

本模块只计算参数,不连接任何券商账户、不下单。
"""
from . import data, plan


def _order_price(trigger, direction):
    """限价委托价:止损向下让一点、止盈向上让一点,尽量保证成交。"""
    t = float(trigger)
    if direction == "stop":
        return round(t * 0.998, 2)
    return round(t * 1.002, 2)


def conditional_orders(positions):
    """返回每只持仓的条件单参数列表。"""
    if not positions:
        return []
    quotes = {q["code"]: q for q in data.realtime_quotes([p["code"] for p in positions])}
    out = []
    for p in positions:
        tp = plan.trade_plan(p["code"])
        if tp.get("error"):
            continue
        q = quotes.get(p["code"], {})
        price = float(q.get("price") or tp["price"])
        cost = float(p["cost"])
        shares = float(p["shares"])
        stop = tp.get("stop_loss")
        take = tp["sell_range"][1] if tp.get("sell_range") else None
        out.append({
            "code": p["code"],
            "name": q.get("name") or tp.get("name") or p["code"],
            "shares": shares,
            "cost": cost,
            "price": price,
            "pnl_pct": round((price / cost - 1) * 100, 2) if cost else None,
            "stop_trigger": stop,
            "stop_order": _order_price(stop, "stop") if stop else None,
            "take_trigger": take,
            "take_order": _order_price(take, "take") if take else None,
        })
    return out
