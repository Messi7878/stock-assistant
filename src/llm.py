# -*- coding: utf-8 -*-
"""大模型解读层(可选):把结构化诊断交给 DeepSeek,生成自然语言总结。

API key 读取顺序:环境变量 DEEPSEEK_API_KEY -> 本地 secrets.json
(secrets.json 不提交/不上传)。不填 key 时本模块不会被调用;
分析本身(analysis.py)离线即可运行。

花钱保护(四层,都可用环境变量覆盖):
1. 单次输出上限 LLM_MAX_TOKENS(默认 800),防止一次生成几千字;
2. **每日花费上限 LLM_DAILY_COST(默认 2.00 元)**,按官方价估算;
3. 每日调用次数上限 LLM_DAILY_CALLS(默认 80);
4. 每日 token 上限 LLM_DAILY_TOKENS(默认 300000)。
超过上限直接报错,不会静默继续烧钱。用量记在项目根目录 llm_usage.json
(已 gitignore,只对本机/本容器有效,重启容器会重置;若写不进去则退化为
进程内存计数,同一进程内照样拦得住)。
"""
import datetime as _dt
import json
import os

from . import http

API_URL = "https://api.deepseek.com/chat/completions"
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # stock-assistant 根目录
_USAGE_FILE = os.path.join(_BASE, "llm_usage.json")


def _env_int(name, default):
    try:
        return int(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name) or default)
    except (TypeError, ValueError):
        return default


MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 800)
DAILY_CALLS = _env_int("LLM_DAILY_CALLS", 80)
DAILY_TOKENS = _env_int("LLM_DAILY_TOKENS", 300000)

# DeepSeek 官方价(元 / 百万 tokens)。涨价了改这几个环境变量即可,不用改代码。
PRICE_IN_HIT = _env_float("LLM_PRICE_IN_HIT", 0.5)    # 输入,命中缓存
PRICE_IN_MISS = _env_float("LLM_PRICE_IN_MISS", 2.0)   # 输入,未命中缓存
PRICE_OUT = _env_float("LLM_PRICE_OUT", 8.0)           # 输出
DAILY_COST = _env_float("LLM_DAILY_COST", 2.0)         # 每天最多花多少元


def _cost(usage):
    """按本次返回的 usage 估算花了多少钱(元)。"""
    if not isinstance(usage, dict):
        return 0.0
    out = usage.get("completion_tokens") or 0
    hit = usage.get("prompt_cache_hit_tokens")
    miss = usage.get("prompt_cache_miss_tokens")
    if hit is None and miss is None:
        miss = usage.get("prompt_tokens") or 0
        hit = 0
    try:
        return (
            float(hit or 0) * PRICE_IN_HIT
            + float(miss or 0) * PRICE_IN_MISS
            + float(out) * PRICE_OUT
        ) / 1_000_000
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------- 用量记账
def _today():
    return _dt.date.today().isoformat()


_MEM = {"date": "", "calls": 0, "tokens": 0, "cost": 0.0}


def _load_usage():
    """今天的用量 = 磁盘文件 与 进程内存 取较大值。

    云上容器的文件系统可能是只读的(写盘失败),内存兜底能保证
    至少在同一进程内不会无视上限;磁盘那份则负责跨重启累计。
    """
    today = _today()
    disk = {"date": today, "calls": 0, "tokens": 0, "cost": 0.0}
    try:
        with open(_USAGE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and d.get("date") == today:
            disk["calls"] = int(d.get("calls") or 0)
            disk["tokens"] = int(d.get("tokens") or 0)
            disk["cost"] = float(d.get("cost") or 0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    if _MEM["date"] != today:
        _MEM.update({"date": today, "calls": 0, "tokens": 0, "cost": 0.0})
    return {
        "date": today,
        "calls": max(disk["calls"], _MEM["calls"]),
        "tokens": max(disk["tokens"], _MEM["tokens"]),
        "cost": max(disk["cost"], _MEM["cost"]),
    }


def _save_usage(d):
    try:
        with open(_USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except OSError:
        pass  # 记不上账也不该让业务失败


def _check_budget():
    u = _load_usage()
    if u["cost"] >= DAILY_COST:
        raise RuntimeError(
            f"今日 AI 花费已达上限({DAILY_COST:.2f} 元),明天再来;"
            f"确需放开请设环境变量 LLM_DAILY_COST")
    if u["calls"] >= DAILY_CALLS:
        raise RuntimeError(
            f"今日 AI 调用已达上限({DAILY_CALLS} 次),明天再试;"
            f"确需放开请设环境变量 LLM_DAILY_CALLS")
    if u["tokens"] >= DAILY_TOKENS:
        raise RuntimeError(
            f"今日 AI token 用量已达上限({DAILY_TOKENS}),明天再试;"
            f"确需放开请设环境变量 LLM_DAILY_TOKENS")


def _record(usage):
    u = _load_usage()
    u["calls"] += 1
    if isinstance(usage, dict):
        try:
            u["tokens"] += int(usage.get("total_tokens") or 0)
        except (TypeError, ValueError):
            pass
    u["cost"] = round(u["cost"] + _cost(usage), 6)
    _MEM.update(u)
    _save_usage(u)


def usage_today():
    """给界面显示用:今天的调用次数、token 与花费。"""
    u = _load_usage()
    return {
        **u,
        "call_limit": DAILY_CALLS,
        "token_limit": DAILY_TOKENS,
        "cost_limit": DAILY_COST,
    }


def get_api_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key.strip()
    secrets_path = os.path.join(_BASE, "secrets.json")
    if os.path.exists(secrets_path):
        try:
            with open(secrets_path, encoding="utf-8") as f:
                return (json.load(f).get("deepseek_api_key") or "").strip() or None
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _call(payload, api_key):
    """统一的调用入口:先查预算,再发请求,最后记账。"""
    if not api_key:
        raise ValueError("未配置 DeepSeek API key")
    _check_budget()
    payload = {**payload, "max_tokens": MAX_TOKENS}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    resp = http.http_post(API_URL, json.dumps(payload).encode("utf-8"), headers=headers)
    data = json.loads(resp)
    if "choices" in data:
        _record(data.get("usage"))
    return data


def narrate(structured_report, api_key=None, model="deepseek-chat"):
    """把结构化报告交给 DeepSeek,返回中文自然语言解读文本。"""
    if api_key is None:
        api_key = get_api_key()
    if not api_key:
        raise ValueError("未配置 DeepSeek API key")

    system = (
        "你是一名谨慎的 A 股投资研究助手。请基于给定的结构化数据,用简洁、口语化的中文输出:"
        "① 一句话点评大盘环境与建议总仓位;"
        "② 持仓与自选个股:参考买入区间、卖出区间、止损位,各配一句理由与主要风险;"
        "③ 每日推荐股:每只一句话点评(说明入选亮点和该警惕的风险)。"
        "所有价位都只是技术面参考,不是预测也不是承诺,不要承诺收益。"
        "结尾固定附一句:「以上为技术面参考,不构成投资建议,据此操作风险自负」。"
        "控制在 500 字以内。"
    )
    user = "以下是今日结构化诊断(JSON):\n" + json.dumps(structured_report, ensure_ascii=False)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "stream": False,
    }
    data = _call(payload, api_key)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return "解读失败:" + json.dumps(data, ensure_ascii=False)[:400]


def analyze_news(stock_name, code, news_data, api_key=None, model="deepseek-chat"):
    """让 DeepSeek 判断近期公告/新闻对该股的影响,返回结构化 dict。

    返回:{"sentiment": "利好|利空|中性", "score": -1..1, "reason": str, "risk": str}
    无新闻或无 key 时返回 None。
    """
    if api_key is None:
        api_key = get_api_key()

    ann = (news_data or {}).get("announcements") or []
    news = (news_data or {}).get("news") or []
    if not ann and not news:
        return None
    if not api_key:
        raise ValueError("未配置 DeepSeek API key")

    lines = [f"股票:{stock_name}({code})", "", "近期公告:"]
    lines += [f"- {a['date']} {a['title']}" for a in ann] or ["- 无"]
    lines += ["", "近期新闻:"]
    lines += [f"- {n['date']} {n['title']}({n.get('media', '')})" for n in news] or ["- 无"]
    user = "\n".join(lines)

    system = (
        "你是 A 股研究助手。根据给定的公告和新闻标题,判断这些信息对该股"
        "短期(数日内)的影响。只输出 JSON(不要任何多余文字):"
        '{"sentiment":"利好|利空|中性","score":-1到1的小数,'
        '"reason":"一句话理由","risk":"主要风险"}'
    )
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    data = _call(payload, api_key)
    try:
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError):
        return None
