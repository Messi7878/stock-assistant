# -*- coding: utf-8 -*-
"""总仓位与分散度建议:结合大盘环境、当前仓位、集中度、行业分散度给出建议。"""
from . import data, market


def allocation_advice(positions, total_capital=0):
    env = market.market_env()
    if not positions:
        return {"positions": [], "total_mv": 0, "position_pct": None, "sectors": [],
                "market": env,
                "advice": ["暂无持仓"] + ([env["verdict"]] if env.get("verdict") else [])}

    quotes = {q["code"]: q for q in data.realtime_quotes([p["code"] for p in positions])}
    rows = []
    total_mv = 0.0
    for p in positions:
        q = quotes.get(p["code"], {})
        price = float(q.get("price") or 0)
        mv = price * float(p["shares"])
        total_mv += mv
        rows.append({
            "code": p["code"],
            "name": q.get("name") or p.get("name") or p["code"],
            "shares": float(p["shares"]),
            "cost": float(p["cost"]),
            "price": price,
            "mv": round(mv, 2),
        })
    for r in rows:
        r["weight_pct"] = round(r["mv"] / total_mv * 100, 1) if total_mv else 0.0
    rows.sort(key=lambda x: -x["weight_pct"])

    # 行业归属 + 行业分散度
    sectors = {}
    for r in rows:
        try:
            r["industry"] = data.industry(r["code"])
        except Exception:  # noqa: BLE001
            r["industry"] = None
        key = r["industry"] or "未知行业"
        sectors[key] = sectors.get(key, 0.0) + r["mv"]
    sector_list = [{"industry": k, "mv": round(v, 2),
                    "weight_pct": round(v / total_mv * 100, 1) if total_mv else 0.0}
                   for k, v in sorted(sectors.items(), key=lambda x: -x[1])]

    advice = []

    # 仓位
    position_pct = None
    if total_capital and total_capital > 0:
        position_pct = round(total_mv / total_capital * 100, 1)
        cash = total_capital - total_mv
        rng = env.get("suggest_position")
        if rng:
            lo, hi = rng
            if position_pct > hi:
                advice.append(f"当前仓位 {position_pct}%(可用现金约 {cash:,.0f} 元),"
                              f"高于建议区间 {lo}%-{hi}%,建议减仓、留出现金")
            elif position_pct < lo:
                advice.append(f"当前仓位 {position_pct}%,低于建议区间 {lo}%-{hi}%,可考虑适度加仓")
            else:
                advice.append(f"当前仓位 {position_pct}%,处于建议区间 {lo}%-{hi}% 内")
    else:
        advice.append("未设置总资金,无法计算仓位%;可在 config.json 的 account.total_capital 填入")

    # 集中度
    if rows and rows[0]["weight_pct"] >= 50:
        advice.append(f"{rows[0]['name']} 占 {rows[0]['weight_pct']}%,单只过度集中,建议单只不超过 30%-40%")
    elif rows and rows[0]["weight_pct"] >= 40:
        advice.append(f"{rows[0]['name']} 占 {rows[0]['weight_pct']}%,略偏集中,可再分散")
    if len(rows) < 3:
        advice.append(f"当前仅 {len(rows)} 只持仓,建议分散到 3-5 只不同行业,降低单只风险")

    # 行业分散度
    if len(rows) >= 2 and sector_list:
        top = sector_list[0]
        if top["weight_pct"] >= 60:
            advice.append(f"行业集中:{top['industry']} 占 {top['weight_pct']}%,建议跨行业分散")
        elif top["weight_pct"] >= 45:
            advice.append(f"{top['industry']} 占 {top['weight_pct']}%,行业略集中,可再均衡")

    if env.get("verdict"):
        advice.append(env["verdict"])

    return {"positions": rows, "total_mv": round(total_mv, 2),
            "position_pct": position_pct, "cash": round((total_capital or 0) - total_mv, 2)
            if total_capital else None,
            "sectors": sector_list, "market": env, "advice": advice}
