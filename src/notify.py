# -*- coding: utf-8 -*-
"""推送模块:把每日报告发到手机。

支持的渠道(在 config.json 的 notify 里按需启用,可同时开多个):
- email     SMTP 邮件(QQ/163 邮箱,需"授权码"而非登录密码)
- wecom     企业微信群机器人 Webhook
- dingtalk  钉钉群机器人 Webhook
- feishu    飞书群机器人 Webhook
- serverchan Server酱(微信推送,需 SendKey)
- pushplus  PushPlus(微信推送,需 token)

全部免费(短信才要钱)。用标准库 urllib 发送,无需第三方依赖。
"""
import json
import smtplib
import urllib.parse
from email.header import Header
from email.mime.text import MIMEText

from . import http


def _ok(resp_text):
    """通用判定:返回 (是否成功, 摘要)。"""
    try:
        d = json.loads(resp_text)
    except (ValueError, TypeError):
        return True, (resp_text or "")[:100]
    code = d.get("errcode", d.get("code", d.get("Code", 0)))
    if code in (0, 200, None):
        return True, "ok"
    return False, json.dumps(d, ensure_ascii=False)[:150]


def send_email(title, content, cfg):
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = cfg["username"]
    msg["To"] = cfg["to"]
    host = cfg.get("smtp_host", "smtp.qq.com")
    port = int(cfg.get("smtp_port", 465))
    to_list = [x.strip() for x in str(cfg["to"]).split(",") if x.strip()]
    with smtplib.SMTP_SSL(host, port, timeout=30) as s:
        s.login(cfg["username"], cfg["password"])
        s.sendmail(cfg["username"], to_list, msg.as_string())
    return True, f"已发送到 {cfg['to']}"


def send_wecom(title, content, cfg):
    body = json.dumps({"msgtype": "markdown",
                       "markdown": {"content": content}}).encode("utf-8")
    return _ok(http.http_post(cfg["webhook"], body,
                              headers={"Content-Type": "application/json"}))


def send_dingtalk(title, content, cfg):
    body = json.dumps({"msgtype": "markdown",
                       "markdown": {"title": title, "text": content}}).encode("utf-8")
    return _ok(http.http_post(cfg["webhook"], body,
                              headers={"Content-Type": "application/json"}))


def send_feishu(title, content, cfg):
    body = json.dumps({"msg_type": "text",
                       "content": {"text": f"{title}\n\n{content}"}}).encode("utf-8")
    return _ok(http.http_post(cfg["webhook"], body,
                              headers={"Content-Type": "application/json"}))


def send_serverchan(title, content, cfg):
    key = str(cfg["sendkey"]).strip()
    url = key if key.startswith("http") else f"https://sctapi.ftqq.com/{key}.send"
    data = urllib.parse.urlencode({"title": title, "desp": content}).encode("utf-8")
    return _ok(http.http_post(url, data,
                              headers={"Content-Type": "application/x-www-form-urlencoded"}))


def send_pushplus(title, content, cfg):
    body = json.dumps({"token": cfg["token"], "title": title,
                       "content": content, "template": "markdown"}).encode("utf-8")
    return _ok(http.http_post("https://www.pushplus.plus/send", body,
                              headers={"Content-Type": "application/json"}))


_CHANNELS = {
    "email": send_email,
    "wecom": send_wecom,
    "dingtalk": send_dingtalk,
    "feishu": send_feishu,
    "serverchan": send_serverchan,
    "pushplus": send_pushplus,
}


def push(title, content, notify_cfg):
    """按配置推送,返回 [(渠道, 是否成功, 信息), ...]。"""
    results = []
    if not notify_cfg or not notify_cfg.get("enabled"):
        return [("all", False, "推送未启用(config.json 里 notify.enabled=false)")]
    for name, fn in _CHANNELS.items():
        sub = notify_cfg.get(name) or {}
        if not sub.get("enabled"):
            continue
        try:
            ok, info = fn(title, content, sub)
            results.append((name, ok, info))
        except Exception as exc:  # noqa: BLE001
            results.append((name, False, repr(exc)[:200]))
    if not results:
        results.append(("all", False, "没有任何渠道被启用"))
    return results
