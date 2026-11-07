# -*- coding: utf-8 -*-
"""命令行入口:查行情、看 K 线、管理持仓。

用法:
  python scripts/quote.py quote                  # 查自选股实时行情
  python scripts/quote.py quote 600519 000001    # 查指定股票
  python scripts/quote.py kline 600519 --limit 5 # 最近 N 日 K 线
  python scripts/quote.py portfolio              # 看持仓盈亏
  python scripts/quote.py add 600519 100 1600 贵州茅台   # 录入持仓
  python scripts/quote.py remove 600519          # 删除持仓
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import data  # noqa: E402
from src.portfolio import Portfolio  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(BASE, "config.json")
PORTFOLIO = os.path.join(BASE, "portfolio.json")


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def fmt_amount(v):
    if v is None:
        return "-"
    v = float(v)
    if v >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if v >= 1e4:
        return f"{v / 1e4:.2f}万"
    return f"{v:.0f}"


def fmt_quote(q):
    chg = q.get("change_pct")
    chg_s = f"{'+' if (chg or 0) >= 0 else ''}{chg}%" if chg is not None else "-"
    to = f"{q.get('turnover')}%" if q.get("turnover") is not None else "-"
    return (f"{q['name']:<8} {q['code']}  现价 {q['price']:<10} {chg_s}  "
            f"开 {q['open']}  高 {q['high']}  低 {q['low']}  "
            f"额 {fmt_amount(q.get('amount'))}  换手 {to}")


def cmd_quote(args):
    codes = args.codes or load_config().get("watchlist", [])
    quotes = data.realtime_quotes(codes)
    if not quotes:
        print("未获取到行情")
        return
    for q in quotes:
        print(fmt_quote(q))


def cmd_kline(args):
    ks = data.daily_kline(args.code, limit=args.limit or 30)
    if not ks:
        print("无数据")
        return
    print(f"{args.code} 最近 {len(ks)} 个交易日:")
    for k in ks:
        to = f"{k['turnover']:.2f}%" if k.get("turnover") is not None else "-"
        print(f"  {k['date']}  开 {k['open']:<9} 收 {k['close']:<9} "
              f"高 {k['high']:<9} 低 {k['low']:<9} "
              f"涨跌 {k['change_pct']:+.2f}%  换手 {to}")


def cmd_portfolio(args):
    pf = Portfolio(PORTFOLIO)
    positions = pf.positions()
    if not positions:
        print("持仓为空。示例: python scripts/quote.py add 600519 100 1600 贵州茅台")
        return
    quotes = {q["code"]: q for q in data.realtime_quotes([p["code"] for p in positions])}
    total_cost = total_mv = 0.0
    print(f"{'名称':<8}{'代码':<8}{'持股':>8}{'成本':>10}{'现价':>10}{'盈亏':>12}{'盈亏%':>8}")
    for p in positions:
        q = quotes.get(p["code"])
        if not q or q["price"] is None:
            print(f"{p.get('name') or p['code']:<8}{p['code']:<8}"
                  f"{p['shares']:>8.0f}{p['cost']:>10.2f}  行情缺失")
            continue
        price = float(q["price"])
        cost = float(p["cost"])
        shares = float(p["shares"])
        pnl = (price - cost) * shares
        pnl_pct = (price - cost) / cost * 100 if cost else 0.0
        total_cost += cost * shares
        total_mv += price * shares
        print(f"{q['name']:<8}{p['code']:<8}{shares:>8.0f}{cost:>10.2f}{price:>10.2f}"
              f"{pnl:>+12.2f}{pnl_pct:>+7.2f}%")
    if total_cost:
        tp = total_mv - total_cost
        print(f"\n总成本 {total_cost:,.2f}  总市值 {total_mv:,.2f}  "
              f"总盈亏 {tp:+,.2f}  ({tp / total_cost * 100:+.2f}%)")


def cmd_add(args):
    pf = Portfolio(PORTFOLIO)
    pf.add(args.code, args.shares, args.cost, args.name or "", args.note or "")
    print(f"已记录 {args.code} 持股 {args.shares:g} 成本 {args.cost:g}")


def cmd_remove(args):
    pf = Portfolio(PORTFOLIO)
    print("已删除" if pf.remove(args.code) else "未找到该代码")


def cmd_check(args):
    from src import alerts
    cfg = load_config()
    alert_cfg = cfg.get("alert", {})
    if not alert_cfg.get("enabled", True):
        print("提醒已关闭(config.json 中 alert.enabled=false)")
        return
    pf = Portfolio(PORTFOLIO)
    codes = list(cfg.get("watchlist", []))
    codes += [p["code"] for p in pf.positions() if p["code"] not in codes]
    if not codes:
        print("无监控标的:请在 config.json 的 watchlist 添加代码,或用 add 录入持仓。")
        return
    res = alerts.scan(
        codes,
        price_alerts=alert_cfg.get("price_alerts", []),
        change_pct_threshold=alert_cfg.get("change_pct_threshold", 3.0),
        vol_spike_ratio=alert_cfg.get("vol_spike_ratio", 2.0),
    )
    if not res:
        print("当前无触发提醒。")
        return
    print(f"触发 {len(res)} 条提醒:")
    for a in res:
        tag = {"warn": "[!]", "info": "[i]"}.get(a["level"], "")
        print(f"  {tag} {a['kind']}: {a['message']}")


def cmd_import(args):
    from src import importer
    pf = Portfolio(PORTFOLIO)
    try:
        items = importer.parse_holdings(args.path)
    except Exception as exc:  # noqa: BLE001
        print("导入失败:", repr(exc))
        return
    if not items:
        print("未解析到持仓。请确认 CSV 含「代码」「持股数量」等列。")
        return
    for it in items:
        pf.add(it["code"], it["shares"], it["cost"], it["name"], "导入")
    print(f"已导入 {len(items)} 条持仓:")
    for it in items:
        print(f"  {it['name'] or ''}  {it['code']}  {it['shares']:g} 股  成本 {it['cost']:g}")


def cmd_watch(args):
    from src import data, watchlist
    action = args.action
    if action == "add":
        if not args.code:
            print("用法: python main.py watch add 600519")
            return
        try:
            print("已加入自选" if watchlist.add(BASE, args.code) else f"{args.code} 已在自选中")
        except ValueError as exc:
            print("错误:", exc)
    elif action == "remove":
        if not args.code:
            print("用法: python main.py watch remove 600519")
            return
        print("已移除" if watchlist.remove(BASE, args.code) else f"{args.code} 不在自选中")
    else:  # list
        codes = watchlist.list_codes(BASE)
        if not codes:
            print("自选为空。用: python main.py watch add 600519")
            return
        for q in data.realtime_quotes(codes):
            print(fmt_quote(q))


def cmd_plan(args):
    from src import plan
    p = plan.trade_plan(args.code)
    if "error" in p:
        print(p["error"])
        return
    print(f"\n===== {p['name']}({p['code']}) 交易参考 @ {p['date']} =====")
    print(f"现价 {p['price']}  趋势 {p['trend']}  MACD {p['macd']}  RSI {p['rsi']}")
    print("\n支撑位:")
    for s in p["supports"]:
        print(f"  {s['price']:<10} ({s['label']}, 距现价 {s['distance_pct']:+.1f}%)")
    print("压力位:")
    for r in p["resistances"]:
        print(f"  {r['price']:<10} ({r['label']}, 距现价 {r['distance_pct']:+.1f}%)")
    if p["buy_range"]:
        print(f"\n参考买入区间: {p['buy_range'][0]} ~ {p['buy_range'][1]}")
    if p["sell_range"]:
        print(f"参考卖出区间: {p['sell_range'][0]} ~ {p['sell_range'][1]}")
    if p["stop_loss"]:
        print(f"参考止损位:   {p['stop_loss']}")
    print("\n信号:")
    for s in p["signals"]:
        print(f"  · {s}")
    print("\n(以上为技术面参考,不构成投资建议)")


def cmd_pick(args):
    from src import screen
    print("正在从榜单取候选池并做技术面筛选,约需 20-40 秒...")
    picks = screen.daily_picks(top=args.top, pool_size=args.pool)
    if not picks:
        print("未取到候选数据(榜单接口可能临时不可用),请稍后再试。")
        return
    print(f"\n===== 每日推荐(技术面筛选,非荐股)· 前 {len(picks)} 名 =====")
    for i, p in enumerate(picks, 1):
        print(f"\n{i}. {p['name']}({p['code']})  现价 {p['price']}  "
              f"行业 {p.get('industry') or '-'}  评分 {p['score']}")
        print(f"   {'、'.join(p['reasons'])}")
    print("\n(以上为技术面参考,不构成投资建议)")


def cmd_review(args):
    from src import track
    rev = track.evaluate(BASE, horizons=tuple(args.horizons))
    if not rev["summary"]:
        print(f"暂无可复盘的样本(历史推荐 {rev['total']} 条,但还没有足够的后续交易日)。")
        print("每天推送后会自动记录推荐,累积几天后再来看。")
        return
    print(f"\n===== 推荐胜率复盘(历史推荐 {rev['total']} 条)=====")
    for h, s in rev["summary"].items():
        print(f"  推荐后 {h} 个交易日:{s['n']} 只样本,胜率 {s['win_rate']}%,"
              f"平均 {s['avg_return']:+.2f}%(最好 {s['best']:+.2f}% / 最差 {s['worst']:+.2f}%)")
    print("\n  明细:")
    for r in rev["detail"][:15]:
        rets = " ".join(f"{h}日 {v:+.2f}%" for h, v in r["returns"].items())
        print(f"   {r['date']} {r['name']}({r['code']}) 推荐价 {r['rec_price']} → {rets}")


def cmd_position(args):
    from src import allocation
    cfg = load_config()
    pf = Portfolio(PORTFOLIO)
    total_capital = (cfg.get("account") or {}).get("total_capital", 0)
    adv = allocation.allocation_advice(pf.positions(), total_capital=total_capital)
    env = adv.get("market", {})
    print("\n===== 大盘环境 =====")
    for i in env.get("indices", []):
        print(f"  {i['name']}: {i['price']} ({i['trend']}, 近20日 {i['chg20_pct']}%)")
    if env.get("suggest_position"):
        print(f"  建议总仓位: {env['suggest_position'][0]}%-{env['suggest_position'][1]}%  {env.get('verdict','')}")
    print(f"\n===== 仓位与分散度 =====")
    print(f"  持仓总市值: {adv['total_mv']:,.2f}   当前仓位: "
          f"{str(adv['position_pct'])+'%' if adv['position_pct'] is not None else '未设置总资金'}")
    for r in adv["positions"]:
        print(f"  {r['name']}({r['code']})  市值 {r['mv']:,.0f}  权重 {r['weight_pct']}%"
              f"  {r.get('industry') or ''}")
    if adv.get("sectors") and len(adv["positions"]) >= 2:
        print("  行业分布: " + "、".join(
            f"{s['industry']} {s['weight_pct']}%" for s in adv["sectors"]))
    print("\n  建议:")
    for a in adv["advice"]:
        print(f"   · {a}")
    print("\n(以上为技术面参考,不构成投资建议)")


def cmd_orders(args):
    from src import orders
    pf = Portfolio(PORTFOLIO)
    rows = orders.conditional_orders(pf.positions())
    if not rows:
        print("暂无持仓。先用 add / import 录入持仓。")
        return
    print("\n===== 开盘前条件单参数(复制到券商 App)=====")
    for r in rows:
        pnl = f"{r['pnl_pct']:+.2f}%" if r["pnl_pct"] is not None else "-"
        print(f"\n{r['name']}({r['code']})  持股 {r['shares']:g}  现价 {r['price']}  盈亏 {pnl}")
        print(f"  止损卖出:触发价 {r['stop_trigger']} / 委托价 {r['stop_order']} / 数量 {r['shares']:g}")
        if r["take_trigger"]:
            print(f"  止盈卖出(可选):触发价 {r['take_trigger']} / 委托价 {r['take_order']} / 数量 {r['shares']:g}")
    print("\n提示:在券商 App「条件单 / 智能委托 / 止盈止损单」里按上表填;")
    print("     怕跌太快不成交时,委托价可选「市价」。")


def cmd_advice(args):
    from src import llm, news, pricing
    cfg = load_config()
    total = (cfg.get("account") or {}).get("total_capital", 0)
    p = pricing.conservative_plan(args.code, total_capital=total)
    if "error" in p:
        print(p["error"])
        return

    sentiment = None
    news_data = None
    if not args.no_news:
        key = llm.get_api_key()
        if key:
            news_data = news.fetch_all(args.code)
            try:
                sentiment = llm.analyze_news(p["name"], args.code, news_data, key)
            except Exception:  # noqa: BLE001
                sentiment = None

    print(f"\n===== {p['name']}({p['code']}) 保守多因子定价 + 新闻面 @ {p['date']} =====")
    print(f"现价 {p['price']}   多因子分 {p['score']}   结论:{p['stance']}")
    print(f"ATR {p['atr']}({p['atr_pct']}%)  MA20 {p['ma20']}  MA60 {p['ma60']}  "
          f"RSI {p['rsi']}  量比 {p['vol_ratio']}")
    print("\n技术因子:")
    for r in p["reasons"]:
        print(f"  · {r}")
    print(f"\n结构支撑 {p['structural']}")
    print(f"买入区间 {p['buy_range'][0]} ~ {p['buy_range'][1]}(回踩支撑附近)")
    print(f"止损 {p['stop']}(支撑下方 1×ATR,距入场 {p['stop_pct']}%)")
    if p["target1"]:
        print(f"目标 2R {p['target1']} / 3R {p['target2']}")
    if p["shares"]:
        print(f"\n保守仓位:约 {p['shares']} 股(市值 {p['position_value']:,.0f} 元),"
              f"单笔风险预算约 {p['risk_budget']:,.0f} 元")
    elif p.get("sizing_note"):
        print(f"\n{p['sizing_note']}")

    # ---- 新闻面 ----
    if news_data and (news_data["announcements"] or news_data["news"]):
        print("\n近期公告:")
        for a in news_data["announcements"][:5]:
            print(f"  · {a['date']} {a['title'][:60]}")
        print("近期新闻:")
        for n in news_data["news"][:5]:
            print(f"  · {n['date']} {n['title'][:60]}")
        if sentiment:
            print(f"\nAI 新闻判断:{sentiment.get('sentiment')}(分数 {sentiment.get('score')})")
            print(f"  理由:{sentiment.get('reason')}")
            print(f"  风险:{sentiment.get('risk')}")
            try:
                sc = float(sentiment.get("score") or 0)
            except (TypeError, ValueError):
                sc = 0.0
            if sc <= -0.3:
                print("  → 综合:新闻偏空,比纯技术面更谨慎(不追、暂缓)")
            elif sc >= 0.3:
                print("  → 综合:新闻偏多,但仍勿追高,等回踩")
            else:
                print("  → 综合:新闻影响中性")
    else:
        print("\n(未获取新闻面:无 API key 或新闻接口不可用)")
    print("\n(参考,不保证盈利,不构成投资建议)")


def cmd_ai(args):
    from src import alerts, analysis, llm, plan
    key = llm.get_api_key()
    if not key:
        print("未找到 DeepSeek API key。请二选一:\n"
              "  1) 设置环境变量 DEEPSEEK_API_KEY\n"
              '  2) 在 stock-assistant/secrets.json 写 {"deepseek_api_key":"你的key"}')
        return

    pf = Portfolio(PORTFOLIO)
    cfg = load_config()
    positions = pf.positions()
    codes = list(cfg.get("watchlist", []))
    codes += [p["code"] for p in positions if p["code"] not in codes]

    alert_cfg = cfg.get("alert", {})
    report = {
        "交易参考": [plan.trade_plan(c) for c in codes],
        "持仓": analysis.portfolio_diagnosis(positions) if positions else None,
        "提醒": alerts.scan(
            codes,
            price_alerts=alert_cfg.get("price_alerts", []),
            change_pct_threshold=alert_cfg.get("change_pct_threshold", 3.0),
            vol_spike_ratio=alert_cfg.get("vol_spike_ratio", 2.0),
        ),
    }

    print("正在调用 DeepSeek 生成解读...")
    try:
        text = llm.narrate(report, key)
    except Exception as exc:  # noqa: BLE001
        print("调用失败:", repr(exc))
        return
    print("=" * 56)
    print(text)
    print("=" * 56)


def cmd_analyze(args):
    from src import analysis
    d = analysis.stock_diagnosis(args.code)
    if "error" in d:
        print(d["error"])
        return
    print(f"\n===== {d['name']}({d['code']}) 技术面诊断 @ {d['date']} =====")
    print(f"现价 {d['price']}  涨跌 {d['change_pct']:+.2f}%")
    print(f"趋势: {d['trend']}")
    print(f"均线: MA5={d['ma5']} MA10={d['ma10']} MA20={d['ma20']} MA60={d['ma60']}")
    print(f"MACD: {d['macd']}   RSI={d['rsi']}({d['rsi_state']})   量比={d['volume_ratio']}")
    print(f"60日位置: {d['pos_60d_pct']}%")
    for f in d["flags"]:
        print(f"  [风险] {f}")
    for n in d["notes"]:
        print(f"  [提示] {n}")


def cmd_report(args):
    from src import analysis
    pf = Portfolio(PORTFOLIO)
    positions = pf.positions()
    cfg = load_config()

    if positions:
        r = analysis.portfolio_diagnosis(positions)
        s = r["summary"]
        print(f"\n===== 组合诊断 =====")
        print(f"总成本 {s['total_cost']:,.2f}  总市值 {s['total_mv']:,.2f}  "
              f"总盈亏 {s['total_pnl']:+,.2f} ({s['total_pnl_pct']:+.2f}%)")
        for f in s["flags"]:
            print(f"  [风险] {f}")
        for p in r["positions"]:
            d = p["diagnosis"]
            print(f"\n--- {p['name']}({p['code']}) 盈亏 {p['pnl_pct']:+.2f}% ---")
            print(f"  趋势:{d['trend']}  MACD:{d['macd']}  "
                  f"RSI:{d['rsi']}({d['rsi_state']})  量比:{d['volume_ratio']}")
            for f in d["flags"]:
                print(f"    [风险] {f}")
    else:
        print("持仓为空,改为诊断自选股:")
        for code in cfg.get("watchlist", []):
            d = analysis.stock_diagnosis(code)
            if "error" in d:
                continue
            print(f"\n--- {d['name']}({d['code']})  趋势:{d['trend']}  "
                  f"MACD:{d['macd']}  RSI:{d['rsi']}({d['rsi_state']})  量比:{d['volume_ratio']}")
            for f in d["flags"]:
                print(f"    [风险] {f}")


def main():
    ap = argparse.ArgumentParser(description="A 股行情与持仓助手")
    sub = ap.add_subparsers(dest="cmd")

    p_q = sub.add_parser("quote", help="实时行情(默认看自选)")
    p_q.add_argument("codes", nargs="*")
    p_q.set_defaults(func=cmd_quote)

    p_k = sub.add_parser("kline", help="日线 K 线")
    p_k.add_argument("code")
    p_k.add_argument("--limit", type=int)
    p_k.set_defaults(func=cmd_kline)

    sub.add_parser("portfolio", help="持仓与盈亏").set_defaults(func=cmd_portfolio)

    p_add = sub.add_parser("add", help="录入持仓")
    p_add.add_argument("code")
    p_add.add_argument("shares", type=float)
    p_add.add_argument("cost", type=float)
    p_add.add_argument("name", nargs="?")
    p_add.add_argument("--note")
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("remove", help="删除持仓")
    p_rm.add_argument("code")
    p_rm.set_defaults(func=cmd_remove)

    p_w = sub.add_parser("watch", help="管理自选股(list/add/remove)")
    p_w.add_argument("action", nargs="?", choices=["list", "add", "remove"], default="list")
    p_w.add_argument("code", nargs="?")
    p_w.set_defaults(func=cmd_watch)

    p_imp = sub.add_parser("import", help="从券商导出的 CSV 一键导入持仓")
    p_imp.add_argument("path")
    p_imp.set_defaults(func=cmd_import)

    p_plan = sub.add_parser("plan", help="交易参考:支撑/压力/买卖区间/止损")
    p_plan.add_argument("code")
    p_plan.set_defaults(func=cmd_plan)

    p_pick = sub.add_parser("pick", help="每日推荐(技术面筛选)")
    p_pick.add_argument("--top", type=int, default=5)
    p_pick.add_argument("--pool", type=int, default=15)
    p_pick.set_defaults(func=cmd_pick)

    sub.add_parser("position", help="大盘环境 + 总仓位/分散度建议").set_defaults(func=cmd_position)

    sub.add_parser("orders", help="开盘前条件单参数(止损/止盈)").set_defaults(func=cmd_orders)

    p_adv = sub.add_parser("advice", help="保守多因子定价(ATR/仓位/风险回报) + 新闻面")
    p_adv.add_argument("code")
    p_adv.add_argument("--no-news", action="store_true", help="跳过新闻抓取与 AI 分析")
    p_adv.set_defaults(func=cmd_advice)

    p_rev = sub.add_parser("review", help="推荐胜率复盘")
    p_rev.add_argument("--horizons", type=int, nargs="*", default=[5, 10])
    p_rev.set_defaults(func=cmd_review)

    p_an = sub.add_parser("analyze", help="单股技术面诊断")
    p_an.add_argument("code")
    p_an.set_defaults(func=cmd_analyze)

    sub.add_parser("report", help="持仓/自选诊断报告").set_defaults(func=cmd_report)

    sub.add_parser("check", help="扫描异动/放量/价格提醒").set_defaults(func=cmd_check)

    sub.add_parser("ai", help="用 DeepSeek 生成自然语言解读").set_defaults(func=cmd_ai)

    args = ap.parse_args()
    if not hasattr(args, "func"):
        ap.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
