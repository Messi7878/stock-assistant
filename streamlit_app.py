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
import time
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

# Streamlit 的 Secrets 不会自动变成环境变量;这里把 LLM_* 预算参数透传过去,
# 想改每日上限只要在 Secrets 里加一行,例如 LLM_DAILY_COST = 2.0
try:
    for _k in list(st.secrets.keys()):
        if str(_k).startswith("LLM_") and str(_k) not in os.environ:
            os.environ[str(_k)] = str(st.secrets[_k]).strip()
except Exception:  # noqa: BLE001
    pass

from src import (  # noqa: E402
    alerts, allocation, data, llm, news, orders, plan, pricing, screen,
)
import streamlit_authenticator as stauth  # noqa: E402


def _md_item(date, title, url, extra=""):
    """把一条公告/新闻渲染成可点击的列表项(新标签页打开,电脑、手机都能点)。"""
    import html as _html
    t = _html.escape(title or "")
    tail = " · ".join(x for x in (date, extra) if x)
    if url:
        head = (f'<a href="{_html.escape(url, quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">{t}</a>')
    else:
        head = t
    return "<li>" + head + (f" · {tail}" if tail else "") + "</li>"


def _md_list(items):
    return '<ul style="margin:0.2rem 0 0.8rem 0;padding-left:1.2rem">' + "".join(items) + "</ul>"


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


def sb_put(user, key_name, value, quiet=False):
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
        if not quiet:
            st.error(f"保存失败:{exc}")
        return False


def sb_get_all(key_like):
    """跨账号读一批 key(只给 owner 看使用统计用)。"""
    url, key = _sb_cfg()
    if not url:
        return []
    q = (f"{url}/rest/v1/kv?key=like.{urllib.parse.quote(key_like)}"
         "&select=user_id,key,value")
    try:
        req = urllib.request.Request(q, headers=_sb_headers(key))
        with _DIRECT.open(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8")) or []
    except Exception:  # noqa: BLE001
        return []


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


# ---------------------------------------------------------------- 使用统计
# 不做第三方埋点,复用 kv 表:每个账号每天一行 `usage:YYYY-MM-DD`,value={"n": 次数}。
# 一次浏览器会话记一次(打开/刷新新会话才算),owner 在侧边栏能看到汇总。
USAGE_KEY = "usage:"


def log_usage(user):
    if st.session_state.get("_usage_logged"):
        return
    st.session_state["_usage_logged"] = True
    if not _sb_cfg()[0]:
        return
    day = pd.Timestamp.now().strftime("%Y-%m-%d")
    cur = sb_get(user, USAGE_KEY + day, None) or {}
    try:
        n = int(cur.get("n", 0)) + 1 if isinstance(cur, dict) else 1
    except Exception:  # noqa: BLE001
        n = 1
    sb_put(user, USAGE_KEY + day,
           {"n": n, "last": pd.Timestamp.now().strftime("%m-%d %H:%M")}, quiet=True)


@st.cache_data(ttl=120, show_spinner=False)
def fetch_usage(days=7):
    """把所有人的 usage:{日期} 记录汇总成 [(日期, 次数, 人数, 明细)]。"""
    agg = {}
    for r in sb_get_all(USAGE_KEY + "*"):
        k = str(r.get("key") or "")
        if not k.startswith(USAGE_KEY):
            continue
        day = k[len(USAGE_KEY):]
        try:
            n = int((r.get("value") or {}).get("n", 0))
        except Exception:  # noqa: BLE001
            n = 0
        d = agg.setdefault(day, {"n": 0, "users": {}})
        d["n"] += n
        u = r.get("user_id") or "?"
        d["users"][u] = d["users"].get(u, 0) + n
    out = sorted(agg.items(), reverse=True)[:days]
    return [(day, v["n"], len(v["users"]),
             "、".join(f"{u} {c} 次" for u, c in sorted(v["users"].items())))
            for day, v in out]


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

@st.cache_resource(show_spinner=False)
def _cookie_key():
    """登录 cookie 的签名密钥。

    优先用 Secrets 里的 COOKIE_KEY;没配就**每次启动随机生成一个**——
    这样即使仓库里的兜底值被人看到,也无法伪造登录 cookie
    (代价:应用重启后需要重新登录)。
    """
    k = _sec("COOKIE_KEY")
    if k:
        return str(k)
    import secrets as _s
    return _s.token_urlsafe(32)


authenticator = stauth.Authenticate(
    _auth_cfg["credentials"],
    _auth_cfg["cookie"]["name"],
    _cookie_key(),
    _auth_cfg["cookie"]["expiry_days"],
)

_res = authenticator.login(location="main", key="login")
if isinstance(_res, tuple) and len(_res) == 3:
    name, auth_status, username = _res
else:  # 兼容新版 API
    name = st.session_state.get("name")
    auth_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username")

# --- 登录失败限速:同一用户名 10 分钟内错 5 次就锁一会儿 ---
# 登录页是公网可访问的,这条用来挡住暴力猜密码(bcrypt 12 轮本身也要 0.2 秒/次)。
# 用 cache_resource 存,保证跨会话/跨 rerun 共用同一份计数。
_LOGIN_WINDOW = 600
_LOGIN_MAX_FAIL = 5


@st.cache_resource(show_spinner=False)
def _throttle_store():
    return {}


_THROTTLE = _throttle_store()


def _login_guard_fail(u):
    now = time.time()
    cnt, ts = _THROTTLE.get(u, (0, now))
    if now - ts > _LOGIN_WINDOW:
        cnt, ts = 0, now
    cnt += 1
    _THROTTLE[u] = (cnt, ts)
    return cnt, int(_LOGIN_WINDOW - (now - ts))


if auth_status is False:
    _u = (st.session_state.get("username") or "?").strip()
    _cnt, _left = _login_guard_fail(_u)
    if _cnt >= _LOGIN_MAX_FAIL:
        st.error(f"密码错误次数过多,请 {max(_left, 60) // 60} 分钟后再试。")
    else:
        st.error(f"用户名或密码错误(还可尝试 {_LOGIN_MAX_FAIL - _cnt} 次)")
    st.stop()
if auth_status:
    _THROTTLE.pop((username or "").strip(), None)
if auth_status is None:
    st.info("请在上方输入用户名和密码登录。忘记密码请找管理员重置。")
    st.caption("本工具只做技术面参考,不构成投资建议。")
    st.stop()

if auth_status:
    log_usage(username)


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

    if username == "owner":
        st.divider()
        with st.expander("📊 使用统计(最近 7 天)"):
            rows = fetch_usage(7)
            if not rows:
                st.caption("还没有记录。从这次打开开始计数,明天再来看就有数了。")
            else:
                st.dataframe(
                    pd.DataFrame(rows, columns=["日期", "访问次数", "使用人数", "账号明细"]),
                    hide_index=True, use_container_width=True)
                st.caption("一次新打开/刷新算一次;同一会话里点按钮不重复计数。")
            st.button("刷新统计", key="btn_usage",
                      on_click=lambda: fetch_usage.clear())

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
                            anns = nd.get("announcements", [])
                            news_list = nd.get("news", [])
                            st.write(f"公告 {len(anns)} 条 / 新闻 {len(news_list)} 条"
                                     f"(点标题在新标签页打开原文)")
                            if anns:
                                st.markdown("**📄 公告**")
                                st.markdown(_md_list(
                                    _md_item(a["date"], a["title"], a.get("url"))
                                    for a in anns[:5]), unsafe_allow_html=True)
                                st.caption(f"[查看全部公告](https://data.eastmoney.com/"
                                           f"notices/stock/{code}.html)")
                            if news_list:
                                st.markdown("**📰 新闻**")
                                st.markdown(_md_list(
                                    _md_item(n["date"], n["title"], n.get("url"),
                                             n.get("media"))
                                    for n in news_list[:8]), unsafe_allow_html=True)
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
        try:
            _u = llm.usage_today()
            st.caption(
                f"今日已用 ¥{_u['cost']:.2f} / ¥{_u['cost_limit']:.2f} · "
                f"{_u['calls']} / {_u['call_limit']} 次 · "
                f"{_u['tokens']:,} / {_u['token_limit']:,} tokens"
            )
        except Exception:  # noqa: BLE001
            pass
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
