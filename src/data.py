# -*- coding: utf-8 -*-
"""A 股数据层:东方财富为主(JSON,utf-8),新浪/腾讯为备用(GBK)。

接口说明(均为公开行情接口,无需登录):
- 批量实时行情: push2.eastmoney.com/api/qt/ulist.np/get
- 历史 K 线:     push2his.eastmoney.com/api/qt/stock/kline/get
"""
import json

from . import http

# 东财市场前缀:沪=1,深/北=0
_SH_PREFIXES = ("60", "68", "90", "51", "58", "11", "13")


def to_secid(code):
    """把 6 位代码转成东财 secid,如 600519 -> 1.600519。"""
    code = str(code).strip()
    if code.startswith(_SH_PREFIXES):
        return "1." + code
    return "0." + code


def _f(x):
    """字符串 -> float,失败返回 None。"""
    try:
        return float(x)
    except (ValueError, TypeError):
        return None


def realtime_quotes(codes):
    """批量实时行情。东财(字段最全) -> 腾讯 -> 新浪 三级回退。

    返回 list[dict],字段:code/name/price/change_pct/change/volume(手)/
    amount(元)/turnover(换手%)/pe(市盈率TTM)/vol_ratio(量比)/
    high/low/open/prev_close/total_mv(总市值)/float_mv(流通市值)/pb(市净率)。
    备用源缺的字段置 None。
    """
    if not codes:
        return []
    for fn in (_realtime_eastmoney, _realtime_tencent, _realtime_sina):
        try:
            rows = fn(codes)
            if rows:
                return rows
        except Exception:  # noqa: BLE001
            continue
    return []


def _realtime_eastmoney(codes):
    secids = ",".join(to_secid(c) for c in codes)
    fields = "f2,f3,f4,f5,f6,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23"
    url = (f"https://push2.eastmoney.com/api/qt/ulist.np/get"
           f"?secids={secids}&fields={fields}&fltt=2")
    data = http.http_get_json(url)
    diff = (data.get("data") or {}).get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())

    rows = []
    for it in diff:
        if not it:
            continue
        rows.append({
            "code": it.get("f12"),
            "name": it.get("f14"),
            "price": it.get("f2"),
            "change_pct": it.get("f3"),
            "change": it.get("f4"),
            "volume": it.get("f5"),       # 手
            "amount": it.get("f6"),       # 元
            "turnover": it.get("f8"),     # 换手率 %
            "pe": it.get("f9"),           # 市盈率 TTM
            "vol_ratio": it.get("f10"),   # 量比
            "high": it.get("f15"),
            "low": it.get("f16"),
            "open": it.get("f17"),
            "prev_close": it.get("f18"),
            "total_mv": it.get("f20"),    # 总市值(元)
            "float_mv": it.get("f21"),    # 流通市值(元)
            "pb": it.get("f23"),          # 市净率
        })
    return rows


def _realtime_tencent(codes):
    """腾讯 qt.gtimg.cn,字段:[1]名 [2]码 [3]现价 [4]昨收 [5]今开
    [6]量 [31]涨跌额 [32]涨跌幅 [33]高 [34]低。"""
    symbols = ",".join(_symbol(c) for c in codes)
    txt = http.http_get(f"https://qt.gtimg.cn/q={symbols}", decode="gbk")
    rows = []
    for line in txt.strip().split(";"):
        line = line.strip()
        if '="' not in line:
            continue
        p = line.split('="', 1)[1].rstrip('"').split("~")
        if len(p) < 35:
            continue
        rows.append({
            "code": p[2],
            "name": p[1],
            "price": _f(p[3]),
            "change_pct": _f(p[32]),
            "change": _f(p[31]),
            "volume": _f(p[6]),
            "amount": None,
            "turnover": None,
            "pe": None,
            "vol_ratio": None,
            "high": _f(p[33]),
            "low": _f(p[34]),
            "open": _f(p[5]),
            "prev_close": _f(p[4]),
            "total_mv": None,
            "float_mv": None,
            "pb": None,
        })
    return rows


def _realtime_sina(codes):
    """新浪 hq.sinajs.cn,字段:[0]名 [1]今开 [2]昨收 [3]现价 [4]高 [5]低
    [8]量(股) [9]额(元)。涨跌幅本地计算。"""
    symbols = ",".join(_symbol(c) for c in codes)
    txt = http.http_get(
        f"https://hq.sinajs.cn/list={symbols}",
        headers={"Referer": "https://finance.sina.com.cn/"}, decode="gbk")
    rows = []
    for line in txt.strip().split("\n"):
        line = line.strip()
        if '="' not in line:
            continue
        sym = line.split("=")[0].split("_")[-1].strip()
        p = line.split('="', 1)[1].rstrip('"').split(",")
        if len(p) < 10 or not p[0]:
            continue
        price = _f(p[3])
        prev_close = _f(p[2])
        code = sym[2:] if sym[:2] in ("sh", "sz") else sym
        rows.append({
            "code": code,
            "name": p[0],
            "price": price,
            "change_pct": (price - prev_close) / prev_close * 100
                          if (price and prev_close) else None,
            "change": (price - prev_close)
                      if (price is not None and prev_close is not None) else None,
            "volume": _f(p[8]),
            "amount": _f(p[9]),
            "turnover": None,
            "pe": None,
            "vol_ratio": None,
            "high": _f(p[4]),
            "low": _f(p[5]),
            "open": _f(p[1]),
            "prev_close": prev_close,
            "total_mv": None,
            "float_mv": None,
            "pb": None,
        })
    return rows


def _symbol(code):
    """东财 secid -> 新浪/腾讯 symbol(sh600519 / sz000001)。"""
    return ("sh" if to_secid(code).startswith("1.") else "sz") + code


def industry(code):
    """取单只股票所属行业(东财 f127)。取不到返回 None。"""
    secid = to_secid(code)
    for host in ("push2", "1.push2", "7.push2", "82.push2"):
        try:
            d = http.http_get_json(
                f"https://{host}.eastmoney.com/api/qt/stock/get"
                f"?secid={secid}&fields=f57,f58,f127", retries=1, timeout=8)
            ind = (d.get("data") or {}).get("f127")
            if ind:
                return ind
        except Exception:  # noqa: BLE001
            continue
    return None


def daily_kline(code, limit=250, adjust="qfq"):
    """日线历史 K 线。新浪为主(快且稳),腾讯为备用(2026-11 起偶发 501)。

    adjust: qfq=前复权 / hfq=后复权 / none=不复权。
    返回 list[dict],按日期升序,每条含 open/close/high/low/volume/amount/
    amplitude/change_pct/change/turnover。腾讯源不含 amount/turnover,置 None;
    change_pct / amplitude / change 由本地计算。
    """
    for fn in (_kline_sina, _kline_tencent):
        try:
            out = fn(code, limit, adjust)
            if out:
                return out
        except Exception:  # noqa: BLE001
            continue
    return []


def _finalize_rows(rows, limit):
    """补算涨跌幅/涨跌额/振幅,并截取最近 limit 条。"""
    prev_close = None
    for r in rows:
        c = r["close"]
        if prev_close:
            r["change_pct"] = (c - prev_close) / prev_close * 100
            r["change"] = c - prev_close
            r["amplitude"] = (r["high"] - r["low"]) / prev_close * 100
        else:
            r["change_pct"] = 0.0
            r["change"] = 0.0
            r["amplitude"] = 0.0
        prev_close = c
    return rows[-limit:]


def _kline_tencent(code, limit, adjust):
    adjust_map = {"qfq": "qfq", "hfq": "hfq", "none": ""}
    symbol = _symbol(code)
    a = adjust_map[adjust]
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={symbol},day,,,{limit},{a}")
    d = http.http_get_json(url)
    node = (d.get("data") or {}).get(symbol) or {}
    arr = node.get("qfqday") or node.get("hfqday") or node.get("day") or []
    rows = []
    for r in arr:
        if len(r) < 6:
            continue
        try:
            rows.append({
                "date": r[0],
                "open": float(r[1]),
                "close": float(r[2]),
                "high": float(r[3]),
                "low": float(r[4]),
                "volume": float(r[5]),   # 手
                "amount": None,
                "amplitude": 0.0,
                "change_pct": 0.0,
                "change": 0.0,
                "turnover": None,
            })
        except (ValueError, IndexError, TypeError):
            continue
    return _finalize_rows(rows, limit)


def _kline_sina(code, limit, adjust):
    symbol = _symbol(code)
    url = (f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/"
           f"CN_MarketDataService.getKLineData"
           f"?symbol={symbol}&scale=240&ma=no&datalen={limit}")
    txt = http.http_get(url)
    start = txt.find("[")
    end = txt.rfind("]") + 1
    if start == -1 or end <= start:
        return []
    arr = json.loads(txt[start:end])
    rows = []
    for r in arr:
        try:
            rows.append({
                "date": r["day"],
                "open": float(r["open"]),
                "close": float(r["close"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "volume": float(r.get("volume") or 0),
                "amount": float(r.get("amount") or 0) if r.get("amount") else None,
                "amplitude": 0.0,
                "change_pct": 0.0,
                "change": 0.0,
                "turnover": None,
            })
        except (KeyError, ValueError, TypeError):
            continue
    return _finalize_rows(rows, limit)
