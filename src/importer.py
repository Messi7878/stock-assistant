# -*- coding: utf-8 -*-
"""持仓导入:从券商 App 导出的 CSV 或 Excel(.xlsx)文件自动解析持仓。

- CSV:自动识别 utf-8 / gbk 编码
- XLSX:用内置 openpyxl 读取(数字型代码自动补零,如 1 -> 000001)
- 表头:支持常见中英文列名,自动定位「代码」「持股数量」列
"""
import csv
import io
import os
import re

COLUMN_ALIASES = {
    "code": ["代码", "股票代码", "证券代码", "证券编码", "股票", "code", "symbol"],
    "name": ["名称", "股票名称", "证券名称", "简称", "name"],
    "shares": ["持股数量", "持股", "股数", "数量", "持仓数量", "证券数量",
               "参考数量", "当前数量", "shares", "quantity", "qty"],
    "cost": ["成本价", "成本", "参考成本价", "摊薄成本", "持仓成本", "均价",
             "参考均价", "成本均价", "盈亏成本", "cost", "avg_price"],
}


def _norm(s):
    return str(s).strip().replace(" ", "").replace("　", "").lower()


def _clean_code(s):
    m = re.search(r"(\d{6})", _norm(s))
    return m.group(1) if m else ""


def _extract_code(v):
    """从单元格取值中提取 6 位代码,数字型补前导零(000001 不会被读成 1)。"""
    if isinstance(v, bool):
        return ""
    if isinstance(v, (int, float)):
        s = str(int(v))
        return s.zfill(6) if s.isdigit() and len(s) <= 6 else ""
    return _clean_code(v)


def _to_float(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("，", "")
    if s in ("", "-", "--", "None", "null"):
        return None
    try:
        if s.endswith("万"):
            return float(s[:-1]) * 1e4
        if s.endswith("亿"):
            return float(s[:-1]) * 1e8
        return float(s)
    except ValueError:
        return None


def _row_empty(row):
    return all(c is None or str(c).strip() == "" for c in row)


def _match(row):
    headers = [_norm(c) for c in row]
    mapping = {}
    for field, aliases in COLUMN_ALIASES.items():
        for i, h in enumerate(headers):
            if h in [_norm(a) for a in aliases]:
                mapping[field] = i
                break
    return mapping


# ------------------------- 读取 -------------------------


def _read_csv_rows(path):
    text = None
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(path, encoding=enc) as f:
                text = f.read()
            break
        except (UnicodeDecodeError, OSError):
            continue
    if text is None:
        raise ValueError("无法读取 CSV(编码不支持或文件不存在)")
    return [r for r in csv.reader(io.StringIO(text))]


def _read_xlsx_rows(path):
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise ValueError("缺少 openpyxl,无法读取 .xlsx") from exc
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    return [list(row) for row in ws.iter_rows(values_only=True)]


def _read_rows(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return _read_xlsx_rows(path)
    return _read_csv_rows(path)


# ------------------------- 解析 -------------------------


def parse_holdings(path):
    """解析 CSV/XLSX 持仓文件,返回 [{code, name, shares, cost}]。"""
    rows = [r for r in _read_rows(path) if not _row_empty(r)]
    if not rows:
        return []

    # 在前 10 行里找表头(含「代码」和「数量」列的那一行)
    header_idx = mapping = None
    for i, r in enumerate(rows[:10]):
        m = _match(r)
        if "code" in m and "shares" in m:
            header_idx, mapping = i, m
            break
    if mapping is None:
        raise ValueError(f"未识别到「代码」「持股数量」列。表头示例:{rows[0]}")

    result = []
    for r in rows[header_idx + 1:]:
        code = _extract_code(r[mapping["code"]]) if mapping["code"] < len(r) else ""
        if len(code) != 6 or not code.isdigit():
            continue
        shares = _to_float(r[mapping["shares"]]) if mapping["shares"] < len(r) else None
        if not shares:
            continue
        name = r[mapping["name"]] if "name" in mapping and mapping["name"] < len(r) else ""
        cost = (_to_float(r[mapping["cost"]])
                if "cost" in mapping and mapping["cost"] < len(r) else 0.0)
        result.append({"code": code, "name": str(name or "").strip(),
                       "shares": shares, "cost": cost or 0.0})
    return result
