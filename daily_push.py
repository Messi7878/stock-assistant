# -*- coding: utf-8 -*-
"""每日推送:生成报告并发送到手机。

可手动运行,也可由 Windows 计划任务每天自动调用(见 安装每日推送.bat)。
"""
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from src import notify  # noqa: E402
from src.report import build_daily_report, load_config  # noqa: E402


def main():
    cfg = load_config(BASE)
    with_ai = cfg.get("report", {}).get("with_ai", True)
    print("正在生成报告...")
    text, graded = build_daily_report(BASE, with_ai=with_ai)

    # 提醒分级:有重要提醒时,标题加前缀,手机通知更醒目
    prefix = "⚠️重要提醒 · " if graded.get("critical") else ""
    title = f"{prefix}A股助手 每日报告 {datetime.date.today().isoformat()}"
    print("正在推送...")
    results = notify.push(title, text, cfg.get("notify", {}))

    log_path = os.path.join(BASE, "push.log")
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] critical={len(graded.get('critical', []))} "
                + json.dumps(results, ensure_ascii=False) + "\n")

    for ch, ok, info in results:
        print(f"  {ch}: {'✅' if ok else '❌'} {info}")

    print("\n--- 报告预览(前 800 字)---")
    print(text[:800])


if __name__ == "__main__":
    main()
