# -*- coding: utf-8 -*-
"""极简 HTTP 客户端:只用标准库,带浏览器 UA / Referer、重试、gzip 解压。

A 股行情接口(东财/新浪/腾讯)对裸请求很敏感,必须带浏览器请求头,
否则会被直接断开连接。这里统一封装。
"""
import urllib.request
import gzip
import json
import time

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 本机可能开了系统代理(如 Watt Toolkit)。默认走系统代理,失败则直连,
# 这样代理开着或关掉都能正常工作。
_OPENER_PROXY = urllib.request.build_opener()
_OPENER_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _open(req, timeout, use_proxy):
    opener = _OPENER_PROXY if use_proxy else _OPENER_DIRECT
    return opener.open(req, timeout=timeout)


def _read(req, timeout, retries):
    """按 代理 -> 直连 -> 代理 交替重试,返回原始字节。"""
    last_err = None
    for attempt in range(retries):
        try:
            with _open(req, timeout, use_proxy=(attempt % 2 == 0)) as resp:
                raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return raw
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(0.4 * (attempt + 1))
    raise last_err


def http_get(url, headers=None, timeout=10, retries=4, decode="utf-8"):
    """GET 并返回解码后的文本。默认按 utf-8 解码,GBK 源可传入 decode='gbk'。"""
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    return _read(req, timeout, retries).decode(decode, "ignore")


def http_get_json(url, headers=None, **kwargs):
    """GET 并解析 JSON。"""
    return json.loads(http_get(url, headers=headers, **kwargs))


def http_post(url, body, headers=None, timeout=30, retries=4):
    """POST(JSON body),返回解码后的文本。"""
    hdrs = dict(DEFAULT_HEADERS)
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    return _read(req, timeout, retries).decode("utf-8", "ignore")
