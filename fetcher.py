"""
A股内部交易监控工具 - 数据抓取模块
从东方财富datacenter API抓取4类内部交易数据
"""
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

from config import API_BASE_URL, HEADERS, PAGE_SIZE, REQUEST_TIMEOUT


def _fetch_eastmoney(report_name: str, sort_columns: str, sort_types: str,
                     filter_expr: str = "", extra_params: dict = None) -> pd.DataFrame:
    """通用东方财富API抓取函数，自动分页"""
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "pageSize": str(PAGE_SIZE),
        "pageNumber": "1",
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    if filter_expr:
        params["filter"] = filter_expr
    if extra_params:
        params.update(extra_params)

    all_data = []
    page = 1
    while True:
        params["pageNumber"] = str(page)
        try:
            resp = requests.get(API_BASE_URL, params=params, headers=HEADERS,
                                timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            print(f"  [错误] 请求 {report_name} 第{page}页失败: {e}")
            break

        if not result.get("success") or not result.get("result"):
            break

        data = result["result"].get("data")
        if not data:
            break

        all_data.extend(data)
        total_pages = result["result"].get("pages", 1)
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)  # 避免请求过快

    if not all_data:
        return pd.DataFrame()
    return pd.DataFrame(all_data)


def _date_filter(field: str, days: int) -> str:
    """生成日期过滤表达式"""
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return f'({field}>=\'{start}\')'


def fetch_shareholder_changes(days: int = 3) -> pd.DataFrame:
    """
    抓取大股东增减持数据
    返回字段: SECURITY_CODE, SECURITY_NAME_ABBR, HOLDER_NAME, DIRECTION,
              CHANGE_NUM, CHANGE_RATE, END_DATE, NOTICE_DATE, TRADE_AVERAGE_PRICE, ...
    """
    print("📊 正在抓取大股东增减持数据...")
    date_filter = _date_filter("END_DATE", days)
    extra = {
        "quoteColumns": "f2~01~SECURITY_CODE~NEWEST_PRICE,f3~01~SECURITY_CODE~CHANGE_RATE_QUOTES",
        "quoteType": "0",
    }
    df = _fetch_eastmoney(
        report_name="RPT_SHARE_HOLDER_INCREASE",
        sort_columns="END_DATE,SECURITY_CODE,EITIME",
        sort_types="-1,-1,-1",
        filter_expr=date_filter,
        extra_params=extra,
    )
    if not df.empty:
        # 计算交易金额（变动股数 * 成交均价）
        for col in ["CHANGE_NUM", "TRADE_AVERAGE_PRICE"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "CHANGE_NUM" in df.columns and "TRADE_AVERAGE_PRICE" in df.columns:
            df["TRADE_AMOUNT"] = (df["CHANGE_NUM"].abs() * df["TRADE_AVERAGE_PRICE"]).round(2)
        for col in ["CHANGE_RATE", "CHANGE_FREE_RATIO"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    print(f"  ✅ 获取 {len(df)} 条大股东增减持记录")
    return df


def fetch_executive_changes(days: int = 3) -> pd.DataFrame:
    """
    抓取高管增减持数据
    返回字段: SECURITY_CODE, SECURITY_NAME, PERSON_NAME, CHANGE_DATE,
              CHANGE_SHARES, AVERAGE_PRICE, CHANGE_AMOUNT, POSITION_NAME, ...
    """
    print("👔 正在抓取高管增减持数据...")
    date_filter = _date_filter("CHANGE_DATE", days)
    df = _fetch_eastmoney(
        report_name="RPT_EXECUTIVE_HOLD_DETAILS",
        sort_columns="CHANGE_DATE,SECURITY_CODE,PERSON_NAME",
        sort_types="-1,1,1",
        filter_expr=date_filter,
    )
    if not df.empty:
        for col in ["CHANGE_SHARES", "AVERAGE_PRICE", "CHANGE_AMOUNT", "CHANGE_RATIO"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    print(f"  ✅ 获取 {len(df)} 条高管增减持记录")
    return df


def fetch_buybacks(days: int = 30) -> pd.DataFrame:
    """
    抓取股票回购数据（回购数据更新较慢，默认抓30天）
    返回字段: DIM_SCODE, SECURITYSHORTNAME, REPURAMOUNTLIMIT, REPURAMOUNT,
              REPURPROGRESS, UPDATEDATE, ...
    """
    print("🔄 正在抓取股票回购数据...")
    date_filter = _date_filter("UPDATEDATE", days)
    df = _fetch_eastmoney(
        report_name="RPTA_WEB_GETHGLIST_NEW",
        sort_columns="UPD,DIM_DATE,DIM_SCODE",
        sort_types="-1,-1,-1",
        filter_expr=date_filter,
    )
    if not df.empty:
        for col in ["REPURAMOUNTLIMIT", "REPURAMOUNTLOWER", "REPURAMOUNT",
                     "ZSZXX", "ZSZSX", "REPURNUM"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 映射进度代码
        progress_map = {
            "001": "董事会预案", "002": "股东大会通过", "003": "股东大会否决",
            "004": "实施中", "005": "停止实施", "006": "完成实施",
        }
        if "REPURPROGRESS" in df.columns:
            df["PROGRESS_TEXT"] = df["REPURPROGRESS"].map(progress_map).fillna(df["REPURPROGRESS"])
    print(f"  ✅ 获取 {len(df)} 条股票回购记录")
    return df


def fetch_equity_incentives(days: int = 30) -> pd.DataFrame:
    """
    抓取股权激励数据
    返回字段: SECURITY_CODE, SECURITY_NAME_ABBR, LASTEST_NOTICE_DATE,
              PLAN_PROCESS, EI_TARGET, INCENTIVE_SHARES, EXERCISE_PRICE, ...
    """
    print("🎯 正在抓取股权激励数据...")
    date_filter = _date_filter("LASTEST_NOTICE_DATE", days)
    df = _fetch_eastmoney(
        report_name="RPT_EQUITY_INCENTIVE",
        sort_columns="LASTEST_NOTICE_DATE",
        sort_types="-1",
        filter_expr=date_filter,
    )
    if not df.empty:
        for col in ["INCENTIVE_SHARES", "EXERCISE_PRICE", "INITIAL_EXERCISE_PRICE"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
    print(f"  ✅ 获取 {len(df)} 条股权激励记录")
    return df
