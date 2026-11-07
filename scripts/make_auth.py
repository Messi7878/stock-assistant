# -*- coding: utf-8 -*-
"""生成 / 重置登录账号。

用法(在 stock-assistant 目录下):

    python scripts/make_auth.py                       # 首次:建 3 个账号并随机生成密码
    python scripts/make_auth.py owner=NewPass123      # 改某个账号的密码
    python scripts/make_auth.py family1=abc12345 family2=xyz98765
    python scripts/make_auth.py --add family3=pass123 --name family3=家人3

改完密码后,把 auth_config.yaml 提交到 GitHub,Streamlit 会自动重新部署。
密码只以 bcrypt 哈希形式保存,配置文件泄露也拿不到明文。
"""
import os
import secrets
import string
import sys

import bcrypt
import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTH_FILE = os.path.join(BASE, "auth_config.yaml")

DEFAULT_USERS = [("owner", "我"), ("family1", "家人1"), ("family2", "家人2")]

_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def rand_password(n=8):
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def hash_password(pw):
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def load():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}
    cfg.setdefault("credentials", {}).setdefault("usernames", {})
    cfg.setdefault("cookie", {})
    cfg["cookie"].setdefault("expiry_days", 30)
    cfg["cookie"].setdefault("name", "stock_assistant")
    if not cfg["cookie"].get("key"):
        cfg["cookie"]["key"] = secrets.token_urlsafe(24)
    cfg.setdefault("preauthorized", {"emails": []})
    return cfg


def save(cfg):
    with open(AUTH_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def main(argv):
    cfg = load()
    users = cfg["credentials"]["usernames"]
    added = []

    args = [a for a in argv if not a.startswith("--")]
    names = {a.split("=", 1)[0].replace("--name ", ""): a.split("=", 1)[1]
             for a in argv if a.startswith("--name")}

    if not args and not users:
        for u, n in DEFAULT_USERS:
            pw = rand_password()
            users[u] = {"name": n, "email": f"{u}@example.com",
                        "password": hash_password(pw)}
            added.append((u, n, pw))
    else:
        for a in args:
            if "=" not in a:
                print(f"跳过(格式应为 user=password):{a}")
                continue
            u, pw = a.split("=", 1)
            users.setdefault(u, {"name": names.get(u, u),
                                 "email": f"{u}@example.com"})
            users[u]["password"] = hash_password(pw)
            added.append((u, users[u].get("name", u), pw))

    if not added:
        print("没有改动。当前账号:")
        for u, v in users.items():
            print(f"  - {u} ({v.get('name', '')})")
        return

    save(cfg)
    print("已写入", AUTH_FILE)
    print("=" * 46)
    for u, n, pw in added:
        print(f"  用户名: {u:<12} 密码: {pw:<12} ({n})")
    print("=" * 46)


if __name__ == "__main__":
    main(sys.argv[1:])
