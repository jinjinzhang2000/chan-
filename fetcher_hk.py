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
                    HK_REQUEST_INTERVAL, WEBB_SDI_URL)


FORM_TYPE_MAP = {
    "CS": "大股东",
    "IS": "大股东",
    "DA": "董事/高管",
    "DB": "董事/高管",
}

REASON_CODE_MAP = {
    "1001": "获得/处置权益",
    "1013": "获得/处置权益",
    "1101": "董事权益变动",
    "1113": "董事权益变动",
    "0801": "成为/不再是大股东",
    "15015": "获得/处置淡仓",
}

_STOCK_CODE_RE = re.compile(r"(?:sc|stock[_-]?code)=(\d{1,5})", re.I)
_STOCK_PAREN_RE = re.compile(r"\((\d{1,5})\)")
_hkex_session = requests.Session()
_hkex_session.headers.update(HK_HEADERS)
_warmed = False


def _parse_position_value(text: str) -> dict:
    """
    解析含仓位标识的数值，如 '11,067,400(L)' 或 '20,360,969(L)13,654,837(S)'
    返回 {'L': 11067400, 'S': 0, 'P': 0}
    """
    result = {"L": 0, "S": 0, "P": 0}
    if not text:
        return result
    matches = re.findall(r"([\d,]+)\(([LSP])\)", text)
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
    matches = re.findall(r"([\d.]+)\(([LSP])\)", text)
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
    cleaned = re.sub(r"[A-Za-z$\s]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def extract_stock_code(cell, corp_name: str) -> str:
    """从公司单元格链接或名称中提取5位港股代码。"""
    if cell is not None:
        link = cell.find("a")
        if link and link.get("href"):
            match = _STOCK_CODE_RE.search(link.get("href"))
            if match:
                return match.group(1).zfill(5)
        cell_text = cell.get_text(" ", strip=True)
        match = _STOCK_PAREN_RE.search(cell_text)
        if match:
            return match.group(1).zfill(5)
    if corp_name:
        match = _STOCK_PAREN_RE.search(corp_name)
        if match:
            return match.group(1).zfill(5)
    return ""


def _infer_filer_type(serial: str) -> str:
    """根据表单编号前缀推断披露人类型"""
    if not serial:
        return "未知"
    prefix = serial[:2].upper()
    return FORM_TYPE_MAP.get(prefix, "未知")


def _infer_direction(reason_code: str, shares_text: str) -> str:
    """推断交易方向。"""
    if not reason_code:
        return "变动"
    code = re.match(r"(\d+)", reason_code)
    if code:
        c = code.group(1)
        if c.startswith("08"):
            return "成为/不再是大股东"
    return "权益变动"


def _warm_hkex_session():
    """Visit the search entry pages so HKEX can set cookies."""
    global _warmed
    if _warmed:
        return
    try:
        _hkex_session.headers.update({
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Cache-Control": "max-age=0",
        })
        search_url = HKEX_DI_BASE_URL.replace("NSAllFormList.aspx", "NSSrchMethod.aspx")
        _hkex_session.get(search_url, timeout=15)
        date_url = HKEX_DI_BASE_URL.replace("NSAllFormList.aspx", "NSSrchDate.aspx")
        _hkex_session.get(date_url, params={"lang": "EN"}, timeout=15)
        _warmed = True
    except Exception:
        # Warm-up is best-effort; the list request may still succeed.
        pass


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

    _warm_hkex_session()
    headers = dict(HK_HEADERS)
    headers["Referer"] = HKEX_DI_BASE_URL.replace("NSAllFormList.aspx", "NSSrchDate.aspx")

    for retry in range(HK_MAX_RETRIES):
        try:
            resp = _hkex_session.get(
                HKEX_DI_BASE_URL, params=params, headers=headers, timeout=30,
            )
            resp.raise_for_status()

            if "temporarily unavailable" in resp.text.lower():
                print(f"  [警告] HKEX页面暂时不可用，重试 {retry + 1}/{HK_MAX_RETRIES}")
                if retry < min(1, HK_MAX_RETRIES - 1):
                    time.sleep(2)
                    continue
                break
            if "lblRecCount" not in resp.text:
                print(f"  [警告] HKEX返回异常（无记录表），重试 {retry + 1}/{HK_MAX_RETRIES}")
                time.sleep(2 ** retry)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            lbl_count = soup.find(id="lblRecCount")
            total = int(lbl_count.text.strip()) if lbl_count and lbl_count.text.strip().isdigit() else 0

            paging = soup.find(id="grdPaging")
            if not paging:
                return [], total

            all_trs = paging.find_all("tr")
            if len(all_trs) <= 1:
                return [], total

            rows = []
            for tr in all_trs[1:]:
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
                stock_code = extract_stock_code(cells[2], corp_name)

                shares_changed = _parse_position_value(shares_changed_text)
                avg_price = _parse_price(avg_price_text)
                shares_interested = _parse_position_value(shares_interested_text)
                voting_pct = _parse_pct_value(voting_pct_text)

                shares_num = shares_changed.get("L", 0) or shares_changed.get("S", 0)
                trade_amount = shares_num * avg_price

                reason_code = re.match(r"(\d+)", reason) if reason else None
                reason_code = reason_code.group(1) if reason_code else ""

                rows.append({
                    "FORM_SERIAL": serial,
                    "EVENT_DATE": event_date,
                    "CORP_NAME": corp_name,
                    "STOCK_CODE": stock_code,
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


def _parse_plain_number(text: str) -> float:
    if not text:
        return 0.0
    cleaned = str(text).replace(",", "").replace(" ", "").strip()
    if not cleaned or cleaned in {".", "-"}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _infer_webb_date(mmdd: str, today=None) -> datetime:
    """Webb-site lists dates as MM-DD without a year."""
    today = today or datetime.now()
    parts = (mmdd or "").split("-")
    if len(parts) != 2:
        return today
    try:
        month, day = int(parts[0]), int(parts[1])
        candidate = datetime(today.year, month, day)
    except ValueError:
        return today
    if candidate.date() > (today + timedelta(days=1)).date():
        candidate = datetime(today.year - 1, month, day)
    return candidate


def _webb_direction(reason: str, shares: float) -> str:
    text = (reason or "").lower()
    if any(key in text for key in ("bought", "purchased", "given", "received", "other inc", "exercised")):
        return "增持"
    if any(key in text for key in ("sold", "other dec", "delivered", "ceased")):
        return "减持"
    if shares < 0:
        return "减持"
    if shares > 0:
        return "增持"
    return "权益变动"


def parse_webb_sdi_html(html: str, days: int = 3, today=None) -> list:
    """
    Parse Webb-site 'Latest director & CEO dealings' HTML into HK row dicts.
    Data compiled by Webb-site.com, CC-BY 4.0.
    """
    today = today or datetime.now()
    cutoff = today - timedelta(days=days)
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return []

    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all("td")
        if len(cells) < 12:
            continue

        date_text = cells[0].get_text(strip=True)
        event_dt = _infer_webb_date(date_text, today=today)
        if event_dt < cutoff.replace(hour=0, minute=0, second=0, microsecond=0):
            continue

        stock_code = "".join(ch for ch in cells[1].get_text(strip=True) if ch.isdigit()).zfill(5)
        corp_name = cells[2].get_text(" ", strip=True)
        person_name = cells[3].get_text(" ", strip=True)
        reason = cells[4].get_text(" ", strip=True)
        shares = _parse_plain_number(cells[6].get_text(strip=True))
        onex = _parse_plain_number(cells[8].get_text(strip=True))
        offex = _parse_plain_number(cells[9].get_text(strip=True))
        avg_price = onex or offex
        value = _parse_plain_number(cells[10].get_text(strip=True))
        if value == 0 and shares and avg_price:
            value = shares * avg_price
        stake = _parse_plain_number(cells[11].get_text(strip=True))
        form_id = ""
        link = cells[0].find("a")
        if link and link.get("href"):
            match = re.search(r"[?&]r=(\d+)", link.get("href"))
            if match:
                form_id = match.group(1)

        rows.append({
            "FORM_SERIAL": f"WEBB{form_id}" if form_id else "",
            "EVENT_DATE": event_dt.strftime("%Y-%m-%d"),
            "CORP_NAME": corp_name,
            "STOCK_CODE": stock_code,
            "PERSON_NAME": person_name,
            "REASON_CODE": "1101",
            "REASON_TEXT": reason or "董事权益变动",
            "FILER_TYPE": "董事/高管",
            "SHARES_CHANGED": shares,
            "AVG_PRICE": avg_price,
            "TRADE_AMOUNT": round(value, 2),
            "SHARES_INTERESTED_L": 0,
            "SHARES_INTERESTED_S": 0,
            "VOTING_PCT_L": stake,
            "VOTING_PCT_S": 0.0,
            "DIRECTION": _webb_direction(reason, shares),
            "DATA_SOURCE": "Webb-site",
        })
    return rows


def _fetch_webb_sdi(days: int = 3) -> pd.DataFrame:
    """Fetch latest director/CEO dealings from the Webb-site Database mirror."""
    try:
        resp = requests.get(WEBB_SDI_URL, headers=HK_HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
    except Exception as e:
        print(f"  [错误] Webb-site 请求失败: {e}")
        return pd.DataFrame()

    if "Latest director" not in resp.text and "numtable" not in resp.text:
        print("  [警告] Webb-site 页面结构异常")
        return pd.DataFrame()

    rows = parse_webb_sdi_html(resp.text, days=days)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["EVENT_DATE"] = pd.to_datetime(df["EVENT_DATE"], errors="coerce")
    return df


def fetch_hk_insider_changes(days: int = 3) -> pd.DataFrame:
    """
    抓取港股权益披露数据（董事+大股东）
    返回DataFrame，包含字段:
        FORM_SERIAL, EVENT_DATE, CORP_NAME, STOCK_CODE, PERSON_NAME, ...
    """
    print("🇭🇰 正在抓取港股权益披露数据...")

    end = datetime.now()
    start = end - timedelta(days=days)
    start_str = start.strftime("%d/%m/%Y")
    end_str = end.strftime("%d/%m/%Y")

    rows, total = _fetch_hkex_di_page(start_str, end_str, page=1)
    if total == 0 and not rows:
        print("  ↻ HKEX 无数据，改用 Webb-site Database（董事/CEO 买卖，CC-BY 4.0）")
        df = _fetch_webb_sdi(days=days)
        print(f"  ✅ 获取 {len(df)} 条港股权益披露记录（Webb-site）")
        return df

    print(f"  共 {total or '?'} 条记录，第1页已获取 {len(rows)} 条")

    # Keep fetching until an empty page (do not trust HK_PAGE_SIZE alone).
    page = 2
    while page <= 100:
        if total and len(rows) >= total:
            break
        time.sleep(HK_REQUEST_INTERVAL)
        page_rows, _ = _fetch_hkex_di_page(start_str, end_str, page=page)
        if not page_rows:
            break
        rows.extend(page_rows)
        print(f"  第{page}页，累计 {len(rows)} 条")
        page += 1

    df = pd.DataFrame(rows)

    if not df.empty:
        df["EVENT_DATE"] = pd.to_datetime(
            df["EVENT_DATE"], format="%d/%m/%Y", errors="coerce",
        )
        for col in ["SHARES_CHANGED", "AVG_PRICE", "TRADE_AMOUNT",
                     "SHARES_INTERESTED_L", "SHARES_INTERESTED_S",
                     "VOTING_PCT_L", "VOTING_PCT_S"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["DATA_SOURCE"] = "HKEX"

    print(f"  ✅ 获取 {len(df)} 条港股权益披露记录（HKEX）")
    return df
