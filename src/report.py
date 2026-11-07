# -*- coding: utf-8 -*-
"""每日报告:今日重点 + 大盘与仓位 + 持仓盈亏 + 买卖参考 + 每日推荐 + 胜率复盘 + 提醒 + AI。"""
import datetime
import json
import os

from . import alerts, allocation, data, llm, orders, plan, screen, track
from .portfolio import Portfolio


def load_config(base_dir):
    with open(os.path.join(base_dir, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def build_daily_report(base_dir, with_ai=True):
    cfg = load_config(base_dir)
    pf = Portfolio(os.path.join(base_dir, "portfolio.json"))
    positions = pf.positions()

    codes = list(cfg.get("watchlist", []))
    for p in positions:
        if p["code"] not in codes:
            codes.append(p["code"])

    total_capital = (cfg.get("account") or {}).get("total_capital", 0)
    alloc = allocation.allocation_advice(positions, total_capital=total_capital)
    env = alloc.get("market", {})

    quotes = {q["code"]: q for q in data.realtime_quotes(codes)}
    plans = {}
    for c in codes:
        tp = plan.trade_plan(c)
        if not tp.get("error"):
            plans[c] = tp

    pick_cfg = cfg.get("pick", {})
    picks = []
    if pick_cfg.get("enabled", True):
        try:
            picks = screen.daily_picks(top=pick_cfg.get("top", 5),
                                       pool_size=pick_cfg.get("pool_size", 15))
        except Exception:  # noqa: BLE001
            picks = []
    if picks:
        try:
            track.record_picks(base_dir, picks)
        except Exception:  # noqa: BLE001
            pass

    ac = cfg.get("alert", {})
    al = alerts.scan(codes,
                     price_alerts=ac.get("price_alerts", []),
                     change_pct_threshold=ac.get("change_pct_threshold", 3.0),
                     vol_spike_ratio=ac.get("vol_spike_ratio", 2.0))
    graded = alerts.classify(al, critical_change_pct=ac.get("critical_change_pct", 5.0))

    L = ["# A股账户助手 · 每日报告",
         f"日期:{datetime.date.today().isoformat()}", ""]

    # 今日重点(提醒分级:只有重要提醒才置顶)
    L.append("## ⚠️ 今日重点")
    if graded["critical"]:
        L.extend([f"- **[{a['kind']}]** {a['message']}" for a in graded["critical"]])
    else:
        L.append("- 无重要异动")
    L.append("")

    # 一、大盘与仓位建议
    L.append("## 一、大盘与仓位建议")
    for i in env.get("indices", []):
        L.append(f"- {i['name']} {i['price']}({i['trend']},近20日 {i['chg20_pct']}%)")
    if env.get("suggest_position"):
        L.append(f"- **建议总仓位:{env['suggest_position'][0]}%-{env['suggest_position'][1]}%**"
                 f" —— {env.get('verdict', '')}")
    for a in alloc.get("advice", []):
        L.append(f"- {a}")
    if alloc.get("sectors") and len(alloc["positions"]) >= 2:
        sec = "、".join(f"{s['industry']} {s['weight_pct']}%" for s in alloc["sectors"])
        L.append(f"- 行业分布:{sec}")
    L.append("")

    # 二、持仓盈亏
    L.append("## 二、持仓盈亏")
    if positions:
        total_cost = total_mv = 0.0
        for p in positions:
            q = quotes.get(p["code"], {})
            price = float(q.get("price") or 0)
            cost, sh = float(p["cost"]), float(p["shares"])
            if not price:
                L.append(f"- {p.get('name') or p['code']}:行情缺失")
                continue
            pnl = (price - cost) * sh
            pct = (price - cost) / cost * 100 if cost else 0.0
            total_cost += cost * sh
            total_mv += price * sh
            L.append(f"- {q.get('name') or p.get('name') or p['code']}({p['code']}) "
                     f"{sh:g}股,成本 {cost},现价 {price},盈亏 {pnl:+,.0f} ({pct:+.2f}%)")
        if total_cost:
            L.append(f"- **合计**:总市值 {total_mv:,.0f},"
                     f"总盈亏 {total_mv - total_cost:+,.0f} "
                     f"({(total_mv - total_cost) / total_cost * 100:+.2f}%)")
            if alloc.get("position_pct") is not None:
                L.append(f"- 占总资金 {alloc['position_pct']}%,"
                         f"可用现金约 {alloc.get('cash', 0):,.0f} 元")
    else:
        L.append("- 暂无持仓")
    L.append("")

    # 三、买卖参考(含止损位,方便挂单)
    L.append("## 三、买卖参考")
    for c in codes:
        tp = plans.get(c)
        if not tp:
            continue
        buy = "~".join(str(x) for x in tp["buy_range"]) if tp["buy_range"] else "-"
        sell = "~".join(str(x) for x in tp["sell_range"]) if tp["sell_range"] else "-"
        L.append(f"- **{tp['name']}({c})** 现价 {tp['price']} · {tp['trend']}:"
                 f"买入 {buy} / 卖出 {sell} / **止损 {tp['stop_loss']}**")
    L.append("")

    # 三-补:开盘前条件单参数
    if positions:
        try:
            order_rows = orders.conditional_orders(positions)
        except Exception:  # noqa: BLE001
            order_rows = []
        if order_rows:
            L.append("**开盘前条件单参数(复制到券商 App 的「条件单 / 智能委托」):**")
            for r in order_rows:
                L.append(f"- {r['name']}({r['code']}) 持股 {r['shares']:g}:"
                         f"止损 触发 {r['stop_trigger']} / 委托 {r['stop_order']} / 数量 {r['shares']:g}"
                         + (f";止盈(可选) 触发 {r['take_trigger']} / 委托 {r['take_order']}"
                            if r.get("take_trigger") else ""))
            L.append("")

    # 四、每日推荐
    if picks:
        L.append("## 四、每日推荐(技术面筛选,非荐股)")
        for p in picks:
            L.append(f"- **{p['name']}({p['code']})** {p['price']} · {p.get('industry') or ''} "
                     f"· 评分 {p['score']} —— {'、'.join(p['reasons'])}")
        L.append("")

    # 五、推荐胜率复盘
    try:
        rev = track.evaluate(base_dir)
    except Exception:  # noqa: BLE001
        rev = {"summary": {}, "detail": [], "total": 0}
    if rev["summary"]:
        L.append("## 五、推荐胜率复盘")
        for h, s in rev["summary"].items():
            L.append(f"- 推荐后 {h} 个交易日:{s['n']} 只样本,"
                     f"**胜率 {s['win_rate']}%**,平均 {s['avg_return']:+.2f}%"
                     f"(最好 {s['best']:+.2f}% / 最差 {s['worst']:+.2f}%)")
        L.append("")

    # 六、一般提醒
    if graded["info"]:
        L.append("## 六、提醒")
        L.extend([f"- [{a['kind']}] {a['message']}" for a in graded["info"]])
        L.append("")

    # 七、AI 解读
    if with_ai:
        L.append("## 七、AI 解读")
        key = llm.get_api_key()
        if not key:
            L.append("(未配置 DeepSeek API key,跳过)")
        else:
            payload = {
                "今日重点": [a["message"] for a in graded["critical"]] or ["无重要异动"],
                "大盘与仓位": {"指数": env.get("indices", []),
                              "建议仓位": env.get("suggest_position"),
                              "仓位建议": alloc.get("advice", []),
                              "行业分布": alloc.get("sectors", [])},
                "持仓与自选": list(plans.values()),
                "每日推荐": [{k: p[k] for k in
                              ("code", "name", "price", "industry", "score", "reasons")
                              if k in p} for p in picks],
            }
            try:
                L.append(llm.narrate(payload, key))
            except Exception as exc:  # noqa: BLE001
                L.append(f"(AI 调用失败:{exc})")
        L.append("")

    L.append("---")
    L.append("以上为技术面参考,不构成投资建议,据此操作风险自负。")
    return "\n".join(L), graded
