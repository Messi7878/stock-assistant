# -*- coding: utf-8 -*-
"""持仓管理:手动录入,存 JSON。真实资金阶段不碰任何下单接口。"""
import json
import os
import datetime


class Portfolio:
    """持仓 = list[{code, name, shares, cost, note}],cost 为每股成本价。"""

    def __init__(self, path):
        self.path = path
        self.data = {"positions": [], "updated_at": None}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.data = {"positions": [], "updated_at": None}

    def save(self):
        self.data["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def positions(self):
        return self.data.get("positions", [])

    def add(self, code, shares, cost, name="", note=""):
        code = str(code).strip()
        shares = float(shares)
        cost = float(cost)
        for pos in self.positions():
            if pos["code"] == code:
                pos["shares"] = shares
                pos["cost"] = cost
                if name:
                    pos["name"] = name
                if note:
                    pos["note"] = note
                self.save()
                return pos
        pos = {"code": code, "name": name, "shares": shares, "cost": cost, "note": note}
        self.positions().append(pos)
        self.save()
        return pos

    def remove(self, code):
        code = str(code).strip()
        before = len(self.positions())
        self.data["positions"] = [p for p in self.positions() if p["code"] != code]
        if len(self.positions()) != before:
            self.save()
            return True
        return False

    def get(self, code):
        code = str(code).strip()
        for p in self.positions():
            if p["code"] == code:
                return p
        return None
