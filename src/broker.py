# -*- coding: utf-8 -*-
"""自动交易接口(预留,**默认关闭**)。

真实资金阶段,交易功能默认禁用。只有当券商开通了 QMT / Ptrade 等程序化
交易权限后,才应实现下方接口并显式打开开关。当前没有任何真实下单能力,
所有下单调用都会被安全闸门拒绝。

安全设计:
- ENABLED 默认 False;打开需 config.json 中 trading.enabled=true 且
  trading.confirm_word 与确认词一致。
- 未接入真实券商接口前,即使打开开关也只会抛 NotImplementedError。
"""


class TradingDisabled(Exception):
    """交易功能未开启或未接入时抛出。"""


ENABLED = False


def _check_enabled(config=None):
    if not config:
        import json
        import os
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_path = os.path.join(base, "config.json")
        try:
            with open(cfg_path, encoding="utf-8") as f:
                config = json.load(f)
        except (OSError, ValueError):
            config = {}
    trading = config.get("trading", {})
    if not trading.get("enabled"):
        raise TradingDisabled(
            "自动交易默认关闭。如需启用,请先接入券商 QMT/Ptrade 接口,"
            "并在 config.json 中把 trading.enabled 设为 true。"
        )
    if trading.get("confirm_word") != "我确认开启自动交易":
        raise TradingDisabled("未填写正确的确认词,拒绝开启交易。")


class Broker:
    """券商接口基类。接入 QMT/Ptrade 时实现具体子类。"""

    def place_order(self, code, side, quantity, price=None):
        raise NotImplementedError("未实现:需接入券商 QMT/Ptrade 接口")

    def cancel_order(self, order_id):
        raise NotImplementedError("未实现")

    def query_positions(self):
        raise NotImplementedError("未实现")

    def query_orders(self):
        raise NotImplementedError("未实现")


def place_order(*args, **kwargs):
    """下单入口:默认拒绝,未接入前不可用。"""
    _check_enabled()
    raise NotImplementedError("尚未接入券商接口,无法下单。")


def query_positions(*args, **kwargs):
    _check_enabled()
    raise NotImplementedError("尚未接入券商接口,无法查询。")
