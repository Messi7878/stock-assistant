# -*- coding: utf-8 -*-
"""网页仪表盘:监听 127.0.0.1,纯标准库,无需 pip。

运行:
  python app.py
然后浏览器打开 http://127.0.0.1:8756

登录:若 config.json 的 web.password 非空,则所有页面/接口都要求
HTTP Basic Auth(用户名任意,密码即 web.password)。留空则不校验。

接口:
  GET /api/quotes     实时行情(缓存 15s)
  GET /api/portfolio  持仓诊断 + 盈亏(缓存 60s)
  GET /api/alerts     提醒(缓存 30s)
  GET /api/ai         DeepSeek 自然语言解读(需配 key)
"""
import base64
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import alerts, allocation, analysis, data, orders, plan, screen, track, watchlist  # noqa: E402
from src.portfolio import Portfolio  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "config.json")
PORTFOLIO = os.path.join(BASE, "portfolio.json")
WEB_DIR = os.path.join(BASE, "web")
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8756"))

_cache = {}


def cached(key, fn, ttl):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _web_password():
    """登录密码:config.json → web.password(留空=不校验)。"""
    try:
        return ((load_config().get("web") or {}).get("password") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def get_codes():
    cfg = load_config()
    pf = Portfolio(PORTFOLIO)
    codes = list(cfg.get("watchlist", []))
    for p in pf.positions():
        if p["code"] not in codes:
            codes.append(p["code"])
    return codes, cfg, pf


def api_quotes():
    codes, _, _ = get_codes()
    return {"quotes": data.realtime_quotes(codes), "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def api_watchlist():
    codes = watchlist.list_codes(BASE)
    return {"codes": codes, "quotes": data.realtime_quotes(codes)}


def api_orders():
    _, _, pf = get_codes()
    return {"orders": orders.conditional_orders(pf.positions())}


def api_portfolio():
    _, _, pf = get_codes()
    positions = pf.positions()
    if not positions:
        return {"positions": [], "summary": None}
    return analysis.portfolio_diagnosis(positions)


def api_alerts():
    codes, cfg, _ = get_codes()
    ac = cfg.get("alert", {})
    return {"alerts": alerts.scan(
        codes,
        price_alerts=ac.get("price_alerts", []),
        change_pct_threshold=ac.get("change_pct_threshold", 3.0),
        vol_spike_ratio=ac.get("vol_spike_ratio", 2.0),
    )}


def api_plans():
    codes, _, _ = get_codes()
    return {"plans": [plan.trade_plan(c) for c in codes]}


def api_position():
    _, cfg, pf = get_codes()
    total_capital = (cfg.get("account") or {}).get("total_capital", 0)
    return allocation.allocation_advice(pf.positions(), total_capital=total_capital)


def api_picks():
    cfg = load_config()
    pick_cfg = cfg.get("pick", {})
    if not pick_cfg.get("enabled", True):
        return {"picks": []}
    return {"picks": screen.daily_picks(top=pick_cfg.get("top", 5),
                                        pool_size=pick_cfg.get("pool_size", 15))}


def api_review():
    return track.evaluate(BASE)


def api_ai():
    from src import llm
    key = llm.get_api_key()
    if not key:
        return {"error": "未配置 DeepSeek API key。请设置环境变量 DEEPSEEK_API_KEY 或写入 secrets.json。"}
    codes, cfg, pf = get_codes()
    positions = pf.positions()
    ac = cfg.get("alert", {})
    report = {
        "监控标的": [analysis.stock_diagnosis(c) for c in codes],
        "持仓": analysis.portfolio_diagnosis(positions) if positions else None,
        "提醒": alerts.scan(codes, price_alerts=ac.get("price_alerts", []),
                          change_pct_threshold=ac.get("change_pct_threshold", 3.0),
                          vol_spike_ratio=ac.get("vol_spike_ratio", 2.0)),
    }
    try:
        return {"text": llm.narrate(report, key)}
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}


class Handler(BaseHTTPRequestHandler):
    def _auth_ok(self):
        pwd = _web_password()
        if not pwd:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header[6:].strip()).decode("utf-8")
            _, _, given = raw.partition(":")
            return given == pwd
        except Exception:  # noqa: BLE001
            return False

    def _unauthorized(self):
        body = "需要登录:用户名任意,密码为 config.json 中 web.password。".encode("utf-8")
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Stock", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self._json({"error": "not found"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._auth_ok():
            return self._unauthorized()
        route = urlparse(self.path).path
        try:
            if route in ("/", "/index.html"):
                return self._file(os.path.join(WEB_DIR, "index.html"),
                                  "text/html; charset=utf-8")
            if route == "/api/quotes":
                return self._json(cached("quotes", api_quotes, 15))
            if route == "/api/watchlist":
                return self._json(api_watchlist())
            if route == "/api/portfolio":
                return self._json(cached("portfolio", api_portfolio, 60))
            if route == "/api/alerts":
                return self._json(cached("alerts", api_alerts, 30))
            if route == "/api/plans":
                return self._json(cached("plans", api_plans, 60))
            if route == "/api/position":
                return self._json(cached("position", api_position, 120))
            if route == "/api/picks":
                return self._json(cached("picks", api_picks, 600))
            if route == "/api/review":
                return self._json(cached("review", api_review, 300))
            if route == "/api/orders":
                return self._json(cached("orders", api_orders, 60))
            if route == "/api/ai":
                return self._json(api_ai())
            return self._json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": repr(exc)}, 500)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return {}

    def do_POST(self):
        if not self._auth_ok():
            return self._unauthorized()
        route = urlparse(self.path).path
        if route == "/api/positions":
            try:
                body = self._read_body()
                code = str(body.get("code", "")).strip()
                shares = float(body.get("shares") or 0)
                cost = float(body.get("cost") or 0)
                name = str(body.get("name") or "").strip()
                if not (len(code) == 6 and code.isdigit()):
                    return self._json({"error": "代码需为 6 位数字"}, 400)
                if shares <= 0:
                    return self._json({"error": "股数需大于 0"}, 400)
                Portfolio(PORTFOLIO).add(code, shares, cost, name)
                _cache.pop("portfolio", None)
                _cache.pop("quotes", None)
                return self._json({"ok": True, "code": code})
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": repr(exc)}, 400)
        if route == "/api/watchlist":
            try:
                body = self._read_body()
                code = str(body.get("code", "")).strip()
                added = watchlist.add(BASE, code)
                _cache.clear()
                return self._json({"ok": True, "code": code, "added": added})
            except Exception as exc:  # noqa: BLE001
                return self._json({"error": repr(exc)}, 400)
        return self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        if not self._auth_ok():
            return self._unauthorized()
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "positions"]:
            ok = Portfolio(PORTFOLIO).remove(parts[2])
            _cache.pop("portfolio", None)
            _cache.pop("quotes", None)
            return self._json({"ok": ok})
        if len(parts) == 3 and parts[:2] == ["api", "watchlist"]:
            ok = watchlist.remove(BASE, parts[2])
            _cache.clear()
            return self._json({"ok": ok})
        return self._json({"error": "not found"}, 404)

    def log_message(self, *args):  # 静默日志
        pass


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"A股账户助手仪表盘: http://{HOST}:{PORT}  (Ctrl+C 退出)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
