# -*- coding: utf-8 -*-
"""Streamlit 版 · A股账户助手(多账号 / 手机异地访问 / 持仓存 Supabase)

部署:GitHub 仓库 -> Streamlit Community Cloud,主文件填 streamlit_app.py。
需要的 Secrets(Streamlit Cloud -> Settings -> Secrets):

    DEEPSEEK_API_KEY = "sk-xxxx"

    [supabase]
    url = "https://xxxx.supabase.co"
    key = "eyJhbGciOi..."

本地运行:streamlit run streamlit_app.py
"""
import json
import os
import sys
import urllib.parse
import urllib.request

import pandas as pd
import streamlit as st

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

st.set_page_config(page_title="A股账户助手", page_icon="📈", layout="wide")


# ---------------------------------------------------------------- secrets
def _sec(key, default=None):
    try:
        return st.secrets[key]
    except Exception:  # noqa: BLE001
        return default


_dk = _sec("DEEPSEEK_API_KEY")
if _dk:
    os.environ["DEEPSEEK_API_KEY"] = str(_dk).strip()

from src import (  # noqa: E402
    alerts, allocation, data, llm, news, orders, plan, pricing, screen,
)
import streamlit_authenticator as stauth  # noqa: E402

# ---------------------------------------------------------------- 存储层
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _sb_cfg():
    try:
        s = st.secrets["supabase"]
        url = str(s["url"]).rstrip("/")
        try:
            key = str(s["key"])
        except Exception:  # noqa: BLE001
            key = str(s["anon_key"])
        if url.startswith("http") and key:
            return url, key
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _sb_headers(key):
    """新版 publishable key(sb_publishable_...)只放 apikey;旧版 JWT(eyJ...)才加 Bearer。"""
    h = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        h["Authorization"] = f"Bearer {key}"
    return h


def sb_get(user, key_name, default=None):
    url, key = _sb_cfg()
    if not url:
        return default
    q = (f"{url}/rest/v1/kv?user_id=eq.{urllib.parse.quote(user)}"
         f"&key=eq.{urllib.parse.quote(key_name)}&select=value")
    try:
        req = urllib.request.Request(q, headers=_sb_headers(key))
        with _DIRECT.open(req, timeout=20) as resp:
            rows = json.loads(resp.read().decode("utf-8"))
        if not rows:
            return default
        return rows[0]["value"]
    except Exception:  # noqa: BLE001
        return default


def sb_put(user, key_name, value):
    url, key = _sb_cfg()
    if not url:
        return False
    body = json.dumps([{"user_id": user, "key": key_name, "value": value}],
                      ensure_ascii=False).encode("utf-8")
    hdrs = _sb_headers(key)
    hdrs["Prefer"] = "resolution=merge-duplicates,return=minimal"
    try:
        req = urllib.request.Request(f"{url}/rest/v1/kv", data=body,
                                     headers=hdrs, method="POST")
        with _DIRECT.open(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:  # noqa: BLE001
        st.error(f"保存失败:{exc}")
        return False


class Store:
    """有 Supabase 就云端存;没有就退化成当前会话内存(刷新丢失)。"""

    def __init__(self, user):
        self.user = user
        self.persistent = bool(_sb_cfg()[0])

    def get(self, key_name, default=None):
        if self.persistent:
            v = sb_get(self.user, key_name, None)
            return default if v is None else v
        return st.session_state.get(f"{self.user}:{key_name}", default)

    def put(self, key_name, value):
        if self.persistent:
            return sb_put(self.user, key_name, value)
        st.session_state[f"{self.user}:{key_name}"] = value
        return True


# ---------------------------------------------------------------- 登录
AUTH_FILE = os.path.join(BASE, "auth_config.yaml")


def load_auth_config():
    import yaml
    with open(AUTH_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


try:
    _auth_cfg = load_auth_config()
except Exception as exc:  # noqa: BLE001
    st.error(f"缺少 auth_config.yaml:{exc}")
    st.stop()

authenticator = stauth.Authenticate(
    _auth_cfg["credentials"],
    _auth_cfg["cookie"]["name"],
    _auth_cfg["cookie"]["key"],
    _auth_cfg["cookie"]["expiry_days"],
)

_res = authenticator.login(location="main", key="login")
if isinstance(_res, tuple) and len(_res) == 3:
    name, auth_status, username = _res
else:  # 兼容新版 API
    name = st.session_state.get("name")
    auth_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username")

if auth_status is False:
    st.error("用户名或密码错误")
    st.stop()
if auth_status is None:
    st.info("请在上方输入用户名和密码登录。忘记密码请找管理员重置。")
    st.caption("本工具只做技术面参考,不构成投资建议。")
    st.stop()


# ---------------------------------------------------------------- 缓存取数
@st.cache_data(ttl=60, show_spinner=False)
def fetch_quotes(codes):
    try:
        return data.realtime_quotes(list(codes))
    except Exception:  # noqa: BLE001
        return []


@st.cache_data(ttl=300, show_spinner=False)
def fetch_alloc(positions_key, capital):
    pos = [{"code": c, "name": n, "shares": s, "cost": k}
           for c, n, s, k in positions_key]
    try:
        return allocation.allocation_advice(pos, total_capital=capital)
    except Exception:  # noqa: BLE001
        return {}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_picks(top, pool):
    try:
        return screen.daily_picks(top=top, pool_size=pool)
    except Exception:  # noqa: BLE001
        return []


@st.cache_data(ttl=900, show_spinner=False)
def fetch_plans(codes):
    out = {}
    for c in codes:
        try:
            tp = plan.trade_plan(c)
            if not tp.get("error"):
                out[c] = tp
        except Exception:  # noqa: BLE001
            continue
    return out


@st.cache_data(ttl=300, show_spinner=False)
def fetch_alerts(codes, pct, spike):
    try:
        raw = alerts.scan(list(codes), price_alerts=[],
                          change_pct_threshold=pct, vol_spike_ratio=spike)
        return alerts.classify(raw, critical_change_pct=5.0)
    except Exception:  # noqa: BLE001
        return {"critical": [], "info": []}


# ---------------------------------------------------------------- 状态
store = Store(username)
positions = store.get("portfolio", []) or []
watchlist = [str(w) for w in (store.get("watchlist", []) or [])]
capital = float(store.get("total_capital", 0) or 0)
codes = list(dict.fromkeys([p["code"] for p in positions] + watchlist))

# ---------------------------------------------------------------- 侧边栏
with st.sidebar:
    st.markdown(f"### 👤 {name or username}")
    st.caption(f"账号:{username}")
    authenticator.logout(location="sidebar", key="logout")
    st.divider()

    st.markdown("**我的总资金(元)**")
    cap_in = st.number_input("总资金", min_value=0.0, value=capital, step=1000.0,
                             format="%.2f", label_visibility="collapsed")
    if st.button("保存总资金", key="btn_cap"):
        if store.put("total_capital", float(cap_in)):
            st.success("已保存")
            st.rerun()

    st.divider()
    st.markdown("**自选股**")
    new_w = st.text_input("添加代码", placeholder="如 600519",
                          label_visibility="collapsed")
    if st.button("添加自选", key="btn_wadd") and new_w.strip():
        w = new_w.strip().zfill(6)
        if w not in watchlist:
            watchlist.append(w)
            store.put("watchlist", watchlist)
            st.rerun()

    if watchlist:
        drop = st.multiselect("删除自选", watchlist, label_visibility="collapsed")
        if st.button("删除所选", key="btn_wdel") and drop:
            watchlist = [w for w in watchlist if w not in drop]
            store.put("watchlist", watchlist)
            st.rerun()

    st.divider()
    if not store.persistent:
        st.warning("未配置 Supabase 或连接失败:持仓只存在当前浏览器会话里,刷新会丢失。")
        _u, _k = _sb_cfg()
        if _u:
            st.caption(f"尝试连接的地址:{_u}(连不上就核对拼写)")
    else:
        _u, _k = _sb_cfg()
        st.caption(f"云端存储:{_u.split('//')[-1] if _u else '-'}")

# ---------------------------------------------------------------- 取数
quotes = fetch_quotes(tuple(codes)) if codes else []
qmap = {q["code"]: q for q in quotes}
positions_key = tuple((p["code"], p.get("name", ""), float(p["shares"]),
                       float(p["cost"])) for p in positions)
alloc = fetch_alloc(positions_key, capital)
env = alloc.get("market", {}) or {}

st.title("📈 A股账户助手")
st.caption(f"数据为实时/收盘快照 · {pd.Timestamp.now():%Y-%m-%d %H:%M} · "
           "仅技术面参考,不构成投资建议")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["🧭 大盘与仓位", "💼 我的持仓", "⭐ 自选股", "🎯 每日推荐", "📋 条件单", "🧠 AI 解读"])

# ------------------------------------------------ 1 大盘与仓位
with tab1:
    inds = env.get("indices", [])
    if inds:
        cols = st.columns(len(inds))
        for col, i in zip(cols, inds):
            col.metric(i["name"], f"{i['price']}", f"{i.get('chg20_pct', 0):+.2f}% (20日)")
            col.caption(i.get("trend", ""))
    else:
        st.warning("大盘数据获取失败,稍后刷新页面重试。")

    sp = env.get("suggest_position")
    if sp:
        st.info(f"**建议总仓位:{sp[0]}% - {sp[1]}%** —— {env.get('verdict', '')}")

    if positions:
        c1, c2, c3 = st.columns(3)
        c1.metric("持仓市值", f"{alloc.get('total_mv', 0):,.0f}")
        c2.metric("仓位", f"{alloc.get('position_pct')}%")
        c3.metric("可用现金", f"{alloc.get('cash') or 0:,.0f}")
        for a in alloc.get("advice", []):
            st.write("- " + a)
        if alloc.get("sectors") and len(positions) >= 2:
            st.write("**行业分布:** " + "、".join(
                f"{s['industry']} {s['weight_pct']}%" for s in alloc["sectors"]))
    else:
        st.info("还没有持仓,去「我的持仓」添加。")
        if capital <= 0:
            st.caption("提示:先在左下角填「总资金」,才能算出仓位% 和买卖股数。")

    with st.expander("🔍 单只股票详细分析(可选读公告/新闻)"):
        one = st.text_input("股票代码", placeholder="如 600403", key="one_code")
        with_news = st.checkbox("同时用 AI 判断公告/新闻(各 1 次调用)", value=False)
        if st.button("开始分析", key="btn_one") and one.strip():
            code = one.strip().zfill(6)
            with st.spinner("计算中…"):
                try:
                    cp = pricing.conservative_plan(code, total_capital=capital)
                except Exception as exc:  # noqa: BLE001
                    cp = {"error": str(exc)}
            if cp.get("error"):
                st.error(cp["error"])
            else:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("现价", cp["price"])
                m2.metric("评分", cp["score"])
                m3.metric("ATR%", cp["atr_pct"])
                m4.metric("RSI", cp["rsi"])
                st.write(f"**结论:** {cp['stance']}")
                st.write(f"**买入区间:** {cp['buy_range'][0]} ~ {cp['buy_range'][1]}"
                         f" | **止损:** {cp['stop']}(-{cp['stop_pct']}%)"
                         f" | **目标:** {cp['target1']} / {cp['target2']}")
                if cp.get("shares"):
                    st.write(f"**按风险预算建议股数:** {cp['shares']} 股"
                             f"(约 {cp['position_value']:,.0f} 元)")
                elif cp.get("sizing_note"):
                    st.write("**仓位提示:** " + cp["sizing_note"])
                st.write("**依据:** " + "、".join(cp["reasons"]))
                if with_news:
                    with st.spinner("读取公告/新闻 + AI 判断…"):
                        try:
                            nd = news.fetch_all(code)
                            st.write(f"公告 {len(nd.get('announcements', []))} 条 / "
                                     f"新闻 {len(nd.get('news', []))} 条")
                            for a in nd.get("announcements", [])[:5]:
                                st.write(f"- {a['date']} {a['title']}")
                            res = llm.analyze_news(cp["name"], code, nd)
                            if res:
                                st.success(f"AI 判断:{res.get('sentiment')}"
                                           f"({res.get('score')}) —— {res.get('reason')}")
                                st.caption("风险:" + str(res.get("risk")))
                        except Exception as exc:  # noqa: BLE001
                            st.warning(f"新闻分析失败:{exc}")

# ------------------------------------------------ 2 持仓
with tab2:
    if positions:
        rows = []
        tot_cost = tot_mv = 0.0
        for p in positions:
            q = qmap.get(p["code"], {})
            price = float(q.get("price") or 0)
            sh, cost = float(p["shares"]), float(p["cost"])
            pnl = (price - cost) * sh if price else 0.0
            pct = (price - cost) / cost * 100 if price and cost else 0.0
            tot_cost += cost * sh
            tot_mv += price * sh if price else 0.0
            rows.append({"代码": p["code"],
                         "名称": q.get("name") or p.get("name", ""),
                         "持股": sh, "成本": cost, "现价": price or None,
                         "盈亏": round(pnl, 2), "盈亏%": round(pct, 2),
                         "市值": round(price * sh, 2) if price else None})
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        c1, c2 = st.columns(2)
        c1.metric("总市值", f"{tot_mv:,.2f}")
        c2.metric("总盈亏", f"{tot_mv - tot_cost:+,.2f}",
                  f"{(tot_mv - tot_cost) / tot_cost * 100:+.2f}%" if tot_cost else None)
    else:
        st.info("暂无持仓,在下面添加。")

    st.divider()
    with st.form("add_pos", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        code_in = c1.text_input("代码", placeholder="600519")
        sh_in = c2.number_input("股数", min_value=0, step=100, value=100)
        cost_in = c3.number_input("成本价", min_value=0.0, step=0.01, format="%.4f")
        name_in = c4.text_input("名称(可选)")
        if st.form_submit_button("添加 / 更新持仓"):
            c = code_in.strip().zfill(6)
            if not (c.isdigit() and len(c) == 6):
                st.error("代码格式不对,应为 6 位数字")
            elif sh_in <= 0 or cost_in <= 0:
                st.error("股数和成本价必须大于 0")
            else:
                positions = [p for p in positions if p["code"] != c]
                positions.append({"code": c, "name": name_in.strip(),
                                  "shares": int(sh_in), "cost": float(cost_in)})
                if store.put("portfolio", positions):
                    st.success("已保存")
                    st.rerun()

    if positions:
        drop = st.multiselect("删除持仓",
                              [f"{p['code']} {p.get('name', '')}" for p in positions])
        if st.button("删除所选持仓", key="btn_pdel") and drop:
            drop_codes = {d.split()[0] for d in drop}
            positions = [p for p in positions if p["code"] not in drop_codes]
            if store.put("portfolio", positions):
                st.success("已删除")
                st.rerun()

# ------------------------------------------------ 3 自选股
with tab3:
    if not watchlist:
        st.info("左侧可以添加自选股。")
    else:
        if st.button("刷新自选股参考", key="btn_watch"):
            with st.spinner("逐只拉 K 线算区间,约 2 秒/只…"):
                st.session_state["_plans"] = fetch_plans(tuple(watchlist))
        plans = st.session_state.get("_plans") or {}
        rows = []
        for c in watchlist:
            q = qmap.get(c, {})
            tp = plans.get(c, {})
            rows.append({
                "代码": c,
                "名称": q.get("name") or tp.get("name", ""),
                "现价": q.get("price"),
                "涨跌%": q.get("change_pct"),
                "趋势": tp.get("trend", ""),
                "买入区间": "~".join(str(x) for x in tp.get("buy_range", [])) or "",
                "卖出区间": "~".join(str(x) for x in tp.get("sell_range", [])) or "",
                "止损": tp.get("stop_loss"),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        if not plans:
            st.caption("点上面的按钮才会计算买卖区间(K 线要一只只拉,慢)。")

        if st.button("检查异动提醒", key="btn_alert"):
            with st.spinner("检查中…"):
                st.session_state["_alerts"] = fetch_alerts(tuple(codes), 3.0, 2.0)
        graded = st.session_state.get("_alerts") or {}
        if graded.get("critical"):
            st.markdown("#### ⚠️ 重要提醒")
            for a in graded["critical"]:
                st.warning(f"[{a['kind']}] {a['message']}")
        if graded.get("info"):
            st.markdown("#### 一般提醒")
            for a in graded["info"]:
                st.write(f"- [{a['kind']}] {a['message']}")

# ------------------------------------------------ 4 每日推荐
with tab4:
    st.caption("按技术面打分筛选,非荐股。")
    if st.button("获取今日推荐", key="btn_pick"):
        with st.spinner("筛 15 只候选并逐只打分,约 10-20 秒…"):
            st.session_state["_picks"] = fetch_picks(5, 15)
    picks = st.session_state.get("_picks")
    if not picks:
        st.info("点上面按钮生成今日推荐(结果缓存 30 分钟)。")
    else:
        for p in picks:
            st.markdown(f"**{p['name']}({p['code']})** · {p['price']} · "
                        f"{p.get('industry') or ''} · 评分 **{p['score']}**")
            st.caption("、".join(p.get("reasons", [])))

# ------------------------------------------------ 5 条件单
with tab5:
    st.caption("复制到券商 App 的「条件单 / 智能委托」。触发价与委托价已留缓冲。")
    if not positions:
        st.info("先添加持仓。")
    else:
        if st.button("生成条件单参数", key="btn_orders"):
            with st.spinner("计算止损/止盈价…"):
                try:
                    st.session_state["_orders"] = orders.conditional_orders(positions)
                except Exception as exc:  # noqa: BLE001
                    st.session_state["_orders"] = []
                    st.error(f"计算失败:{exc}")
        rows = st.session_state.get("_orders") or []
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True)
        else:
            st.info("点上面按钮生成。")

# ------------------------------------------------ 6 AI 解读
with tab6:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        st.warning("未配置 DEEPSEEK_API_KEY,AI 解读不可用。")
    else:
        st.caption("点一次 = 调用一次 DeepSeek(约 1-2 千 tokens)。")
        if st.button("生成今天的 AI 解读", key="btn_ai"):
            with st.spinner("AI 正在写…"):
                plans = fetch_plans(tuple(codes)) if codes else {}
                payload = {
                    "持仓": [{"代码": p["code"], "股数": p["shares"], "成本": p["cost"]}
                             for p in positions],
                    "仓位": {"市值": alloc.get("total_mv"),
                             "仓位%": alloc.get("position_pct"),
                             "现金": alloc.get("cash")},
                    "大盘": {"指数": env.get("indices", []),
                             "建议仓位": env.get("suggest_position"),
                             "仓位建议": alloc.get("advice", [])},
                    "个股参考": list(plans.values()),
                    "每日推荐": st.session_state.get("_picks") or [],
                }
                try:
                    st.markdown(llm.narrate(payload))
                except Exception as exc:  # noqa: BLE001
                    st.error(f"AI 调用失败:{exc}")

st.divider()
st.caption("以上为技术面参考,不构成投资建议,据此操作风险自负。")
