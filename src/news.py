# -*- coding: utf-8 -*-
"""个股新闻/公告抓取(东方财富)。

- 公告:np-anotice-stock.eastmoney.com/api/security/ann
- 资讯:search-api-web.eastmoney.com/search/jsonp(按股票代码搜索)

接口可能限流或变更,任何失败都返回空列表,不影响主流程。
"""
import json
import re

from . import http

_ANN = ("https://np-anotice-stock.eastmoney.com/api/security/ann"
        "?sr=-1&page_size={n}&page_index=1&ann_type=A&client_source=web&stock_list={code}")

# 搜索接口的 param 是 URL 编码的 JSON,{code}/{n} 为占位符(其余花括号均已编码)
_NEWS = ("https://search-api-web.eastmoney.com/search/jsonp?cb=%24&param="
         "%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{code}%22%2C"
         "%22type%22%3A%5B%22cmsArticleWebOld%22%5D%2C%22client%22%3A%22web%22%2C"
         "%22clientType%22%3A%22web%22%2C%22clientVersion%22%3A%22curr%22%2C"
         "%22param%22%3A%7B%22cmsArticleWebOld%22%3A%7B%22searchScope%22%3A%22default%22%2C"
         "%22sort%22%3A%22default%22%2C%22pageIndex%22%3A1%2C%22pageSize%22%3A{n}%7D%7D%7D")


def _strip(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def fetch_announcements(code, limit=5):
    try:
        j = json.loads(http.http_get(_ANN.format(code=code, n=limit), retries=2, timeout=12))
        out = []
        for it in (j.get("data") or {}).get("list") or []:
            out.append({
                "date": (it.get("notice_date") or it.get("display_time") or "")[:10],
                "title": _strip(it.get("title")),
            })
        return out
    except Exception:  # noqa: BLE001
        return []


def fetch_news(code, limit=8):
    try:
        txt = http.http_get(_NEWS.format(code=code, n=limit), retries=2, timeout=12)
        s, e = txt.find("("), txt.rfind(")")
        if s < 0 or e <= s:
            return []
        j = json.loads(txt[s + 1:e])
        out = []
        for it in (j.get("result") or {}).get("cmsArticleWebOld") or []:
            out.append({
                "date": (it.get("date") or "")[:10],
                "title": _strip(it.get("title")),
                "media": it.get("mediaName") or "",
            })
        return out
    except Exception:  # noqa: BLE001
        return []


def fetch_all(code, ann_limit=5, news_limit=8):
    return {"announcements": fetch_announcements(code, ann_limit),
            "news": fetch_news(code, news_limit)}
