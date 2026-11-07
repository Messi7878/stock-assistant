# -*- coding: utf-8 -*-
"""自选股管理:增删改存于 config.json 的 watchlist。"""
import json
import os


def load(base_dir):
    with open(os.path.join(base_dir, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def save(base_dir, cfg):
    with open(os.path.join(base_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def list_codes(base_dir):
    return load(base_dir).get("watchlist", [])


def _check_code(code):
    code = str(code).strip()
    if not (len(code) == 6 and code.isdigit()):
        raise ValueError("代码需为 6 位数字")
    return code


def add(base_dir, code):
    """加入自选,返回是否新增(False 表示已存在)。"""
    code = _check_code(code)
    cfg = load(base_dir)
    wl = cfg.setdefault("watchlist", [])
    if code in wl:
        return False
    wl.append(code)
    save(base_dir, cfg)
    return True


def remove(base_dir, code):
    """移除自选,返回是否确实删除。"""
    code = str(code).strip()
    cfg = load(base_dir)
    wl = cfg.setdefault("watchlist", [])
    if code in wl:
        wl.remove(code)
        save(base_dir, cfg)
        return True
    return False
