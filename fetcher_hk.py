"""
港股内部交易监控 - 数据抓取模块
从HKEX权益披露系统(Disclosure of Interests)抓取董事及大股东权益变动数据
"""
import re
import time
from datetime import datetime, timedelta

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config import (HKEX_DI_BASE_URL, HK_HEADERS, HK_MAX_RETRIES,
                    HK_PAGE_SIZE, HK_REQUEST_INTERVAL)


# 表单类型前缀 -> 披露人身份
FORM_TYPE_MAP = {
    "CS": "大股东",      # Form 2 - Substantial Shareholder (Corporate)
    "IS": "大股东",      # Form 1 - Substantial Shareholder (Individual)
    "DA": "董事/高管",   # Form 3A - Director/Chief Executive
    "DB": "董事/高管",   # Form 3B - Director (associated corp)
}

# 披露原因代码 -> 说明
REASON_CODE_MAP = {
    "1001": "获得/处置权益",
    "1013": "获得/处置权益",
    "1101": "董事权益变动",
    "1113": "董事权益变动",
    "0801": "成为/不再是大股东",
    "15015": "获得/处置淡仓",
}


def _parse_position_value(text: str) -> dict:
    """
    解析含仓位标识的数值，如 '11,067,400(L)' 或 '20,360,969(L)13,654,837(S)'
    返回 {'L': 11067400, 'S': 0, 'P': 0}
    """
    result = {"L": 0, "S": 0, "P": 0}
    if not text:
        return result
    # 匹配 数字(仓位标识) 的模式
    matches = re.findall(r'([\d,]+)\(([LSP])\)', text)
    for num_str, pos_type in matches:
        val = int(num_str.replace(",", ""))
        result[pos_type] = val
    return result


def _parse_pct_value(text: str) -> dict:
    """
    解析百分比值，如 '7.91(L)' 或 '11.92(L)7.99(S)'
    返回 {'L': 7.91, 'S': 7.99, 'P': 0}
    """
    result = {"L": 0.0, "S": 0.0, "P": 0.0}
    if not text:
        return result
    matches = re.findall(r'([\d.]+)\(([LSP])\)', text)
    for num_str, pos_type in matches:
        try:
            result[pos_type] = float(num_str)
        except ValueError:
            pass
    return result


def _parse_price(text: str) -> float:
    """解析价格，如 'HKD 20.0900' -> 20.09"""
    if not text:
        return 0.0
    # 去掉货币符号
    cleaned = re.sub(r'[A-Za-z$\s]', '', text)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _extract_stock_code_from_serial(serial: str) -> str:
    """
    尝试从表单编号提取信息。表单编号格式如 CS20260213E00007
    前缀(CS/DA/IS) + 日期 + E + 序号，不含股票代码。
    返回空字符串表示无法从编号提取。
    """
    return ""


def _infer_filer_type(serial: str) -> str:
    """根据表单编号前缀推断披露人类型"""
    if not serial:
        return "未知"
    prefix = serial[:2].upper()
    return FORM_TYPE_MAP.get(prefix, "未知")


def _infer_direction(reason_code: str, shares_text: str) -> str:
    """
    推断交易方向。
    reason_code含0801可能是成为/不再是大股东。
    shares_text中(L)一般是多头变动。
    """
    # 简单方向：如果有shares变动数据，默认为"变动"
    # 更精确的方向需要看具体的form详情
    if not reason_code:
        return "变动"
    code = re.match(r'(\d+)', reason_code)
    if code:
        c = code.group(1)
        if c.startswith("08"):
            return "成为/不再是大股东"
    return "权益变动"


def _fetch_hkex_di_page(start_date: str, end_date: str,
                        page: int = 1) -> tuple:
    """
    抓取HKEX权益披露单页数据
    日期格式: dd/mm/yyyy
    返回: (rows_list, total_records)
    """
    params = {
        "sa1": "cl",
        "scsd": start_date,
        "sced": end_date,
        "sc": "",
        "src": "MAIN",
        "lang": "EN",
    }
    if page > 1:
        params["pg"] = str(page)

    for retry in range(HK_MAX_RETRIES):
        try:
            resp = requests.get(HKEX_DI_BASE_URL, params=params,
                                headers=HK_HEADERS, timeout=30)
            resp.raise_for_status()

            if "temporarily unavailable" in resp.text:
                print(f"  [警告] HKEX页面暂时不可用，重试 {retry + 1}/{HK_MAX_RETRIES}")
                time.sleep(2 ** retry)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # 获取总记录数
            lbl_count = soup.find(id="lblRecCount")
            total = int(lbl_count.text.strip()) if lbl_count else 0

            # 解析数据表格
            paging = soup.find(id="grdPaging")
            if not paging:
                return [], total

            all_trs = paging.find_all("tr")
            if len(all_trs) <= 1:  # 只有表头或空
                return [], total

            rows = []
            for tr in all_trs[1:]:  # 跳过表头
                cells = tr.find_all("td")
                if len(cells) < 9:
                    continue

                serial = cells[0].get_text(strip=True)
                event_date = cells[1].get_text(strip=True)
                corp_name = cells[2].get_text(strip=True)
                person_name = cells[3].get_text(strip=True)
                reason = cells[4].get_text(strip=True)
                shares_changed_text = cells[5].get_text(strip=True)
                avg_price_text = cells[6].get_text(strip=True)
                shares_interested_text = cells[7].get_text(strip=True)
                voting_pct_text = cells[8].get_text(strip=True)

                # 解析数值
                shares_changed = _parse_position_value(shares_changed_text)
                avg_price = _parse_price(avg_price_text)
                shares_interested = _parse_position_value(shares_interested_text)
                voting_pct = _parse_pct_value(voting_pct_text)

                # 主要用多头(L)数据
                shares_num = shares_changed.get("L", 0) or shares_changed.get("S", 0)
                trade_amount = shares_num * avg_price

                # 提取原因代码
                reason_code = re.match(r'(\d+)', reason) if reason else None
                reason_code = reason_code.group(1) if reason_code else ""

                rows.append({
                    "FORM_SERIAL": serial,
                    "EVENT_DATE": event_date,
                    "CORP_NAME": corp_name,
                    "PERSON_NAME": person_name,
                    "REASON_CODE": reason_code,
                    "REASON_TEXT": REASON_CODE_MAP.get(reason_code, reason),
                    "FILER_TYPE": _infer_filer_type(serial),
                    "SHARES_CHANGED": shares_num,
                    "AVG_PRICE": avg_price,
                    "TRADE_AMOUNT": round(trade_amount, 2),
                    "SHARES_INTERESTED_L": shares_interested.get("L", 0),
                    "SHARES_INTERESTED_S": shares_interested.get("S", 0),
                    "VOTING_PCT_L": voting_pct.get("L", 0.0),
                    "VOTING_PCT_S": voting_pct.get("S", 0.0),
                    "DIRECTION": _infer_direction(reason_code, shares_changed_text),
                })

            return rows, total

        except Exception as e:
            print(f"  [错误] HKEX请求第{page}页失败: {e}")
            if retry < HK_MAX_RETRIES - 1:
                time.sleep(2 ** retry)
            continue

    return [], 0


def fetch_hk_insider_changes(days: int = 3) -> pd.DataFrame:
    """
    抓取港股权益披露数据（董事+大股东）
    返回DataFrame，包含字段:
        FORM_SERIAL, EVENT_DATE, CORP_NAME, PERSON_NAME, REASON_CODE,
        REASON_TEXT, FILER_TYPE, SHARES_CHANGED, AVG_PRICE, TRADE_AMOUNT,
        SHARES_INTERESTED_L, SHARES_INTERESTED_S, VOTING_PCT_L, VOTING_PCT_S,
        DIRECTION
    """
    print("🇭🇰 正在抓取港股权益披露数据...")

    end = datetime.now()
    start = end - timedelta(days=days)
    start_str = start.strftime("%d/%m/%Y")
    end_str = end.strftime("%d/%m/%Y")

    # 第一页
    rows, total = _fetch_hkex_di_page(start_str, end_str, page=1)
    if total == 0:
        print("  ✅ 获取 0 条港股权益披露记录")
        return pd.DataFrame()

    print(f"  共 {total} 条记录，第1页已获取 {len(rows)} 条")

    # 后续分页
    total_pages = (total + HK_PAGE_SIZE - 1) // HK_PAGE_SIZE
    for pg in range(2, total_pages + 1):
        time.sleep(HK_REQUEST_INTERVAL)
        page_rows, _ = _fetch_hkex_di_page(start_str, end_str, page=pg)
        rows.extend(page_rows)
        print(f"  第{pg}/{total_pages}页，累计 {len(rows)} 条")

    df = pd.DataFrame(rows)

    if not df.empty:
        # 转换日期格式 dd/mm/yyyy -> datetime
        df["EVENT_DATE"] = pd.to_datetime(df["EVENT_DATE"],
                                          format="%d/%m/%Y",
                                          errors="coerce")
        # 数值类型转换
        for col in ["SHARES_CHANGED", "AVG_PRICE", "TRADE_AMOUNT",
                     "SHARES_INTERESTED_L", "SHARES_INTERESTED_S",
                     "VOTING_PCT_L", "VOTING_PCT_S"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    print(f"  ✅ 获取 {len(df)} 条港股权益披露记录")
    return df
