# -*- coding: utf-8 -*-
"""提交前自检:确保仓库里没有任何真实密钥。

用法(在 stock-assistant 目录):
    python scripts/check_secrets.py

退出码 0 = 干净;1 = 发现疑似密钥(不要提交)。
这个仓库是公开的,GitHub 上有大量爬虫专扫 sk- 开头的字符串,
一旦真实 key 被推送,几分钟内就会被人拿去用。
"""
import re
import subprocess
import sys

try:  # Windows 控制台默认 GBK,避免打印特殊符号时崩
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{24,}"), "DeepSeek / OpenAI 风格 key"),
    (re.compile(r"sbp_[A-Za-z0-9]{20,}"), "Supabase 个人访问令牌"),
    (re.compile(r"sb_secret_[A-Za-z0-9_\-]{10,}"), "Supabase secret key"),
    (re.compile(r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_\-]{20,}"),
     "JWT(可能是 anon / service_role key)"),
]

FORBIDDEN_FILES = {
    "secrets.json", "config.json", "portfolio.json", "llm_usage.json",
    "picks_history.json", "secrets.toml",
}
SKIP_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf", ".ico", ".zip")


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        print("不是 git 仓库或 git 不可用,跳过检查")
        return []
    return [f for f in out.stdout.split("\0") if f]


def main():
    hits = []
    for path in tracked_files():
        name = path.replace("\\", "/").split("/")[-1]
        if name in FORBIDDEN_FILES:
            hits.append(f"{path}: 这个文件不应该进仓库")
            continue
        if path.lower().endswith(SKIP_EXT):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        for pat, label in PATTERNS:
            for m in pat.finditer(text):
                line = text[:m.start()].count("\n") + 1
                hits.append(f"{path}:{line}: 疑似{label} — {m.group(0)[:10]}")

    if hits:
        print("发现疑似密钥,已阻止:\n")
        for h in hits:
            print("  " + h)
        print("\n把它们换成占位符(如 sk-xxxx)后再提交。")
        return 1
    print("检查通过:仓库内没有疑似密钥 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
