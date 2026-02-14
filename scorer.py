"""
A股内部交易监控工具 - 综合评分引擎
对4类内部交易数据进行多维度打分，筛选出重要信号

评分改进 v2:
- 大股东：不论增减持，大比例变动都高分；增持额外加分
- 高管：新增密集交易检测（同一人多次交易聚合加分）
- 高管：不论增减持，大金额都高分；增持额外加分
"""
import os

import pandas as pd

from config import PORTFOLIO_FILE, PORTFOLIO_BONUS


def load_portfolio() -> set:
    """加载持仓股票代码集合"""
    if not os.path.exists(PORTFOLIO_FILE):
        return set()
    codes = set()
    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                codes.add(line.split()[0])  # 取第一列作为代码
    return codes


def _apply_portfolio_bonus(df: pd.DataFrame, code_col: str) -> pd.DataFrame:
    """给持仓股票加分并标记"""
    portfolio = load_portfolio()
    if not portfolio or df.empty or code_col not in df.columns:
        if not df.empty:
            df["IS_PORTFOLIO"] = False
        return df
    df["IS_PORTFOLIO"] = df[code_col].isin(portfolio)
    df.loc[df["IS_PORTFOLIO"], "SCORE"] = (
        df.loc[df["IS_PORTFOLIO"], "SCORE"] + PORTFOLIO_BONUS
    ).clip(upper=130)  # 持仓股可以超过100分，上限130
    # 持仓股优先排序：先按IS_PORTFOLIO降序，再按SCORE降序
    df = df.sort_values(["IS_PORTFOLIO", "SCORE"], ascending=[False, False])
    return df


def score_shareholder_changes(df: pd.DataFrame) -> pd.DataFrame:
    """
    大股东增减持评分（满分100）
    维度：交易金额、占总股本比例（不论方向）、增持加分
    """
    if df.empty:
        return df

    scores = pd.Series(0, index=df.index, dtype=float)

    # 1. 交易金额评分（最高40分）
    if "TRADE_AMOUNT" in df.columns:
        amt = df["TRADE_AMOUNT"].fillna(0)
        scores += (amt >= 1e8).astype(int) * 40   # >= 1亿
        scores += ((amt >= 5e7) & (amt < 1e8)).astype(int) * 25  # >= 5000万
        scores += ((amt >= 1e7) & (amt < 5e7)).astype(int) * 10  # >= 1000万

    # 2. 占总股本比例评分（最高40分）—— 不论增减持，大比例变动都重要
    if "CHANGE_RATE" in df.columns:
        rate = df["CHANGE_RATE"].fillna(0).abs() * 100  # 转为百分比
        scores += (rate >= 5).astype(int) * 40
        scores += ((rate >= 3) & (rate < 5)).astype(int) * 30
        scores += ((rate >= 1) & (rate < 3)).astype(int) * 20
        scores += ((rate >= 0.5) & (rate < 1)).astype(int) * 10

    # 3. 方向加分（增持额外+10，减持也有基础分不会被忽略）
    if "DIRECTION" in df.columns:
        scores += (df["DIRECTION"] == "增持").astype(int) * 10

    df = df.copy()
    df["SCORE"] = scores.clip(upper=100).astype(int)
    df = _apply_portfolio_bonus(df, "SECURITY_CODE")
    return df


def _calc_frequency_bonus(df: pd.DataFrame, group_cols: list,
                          date_col: str) -> pd.Series:
    """
    计算密集交易加分：同一人/股东在数据范围内交易次数越多，加分越高
    返回与df同index的加分Series
    """
    bonus = pd.Series(0, index=df.index, dtype=float)
    if df.empty or date_col not in df.columns:
        return bonus
    valid_cols = [c for c in group_cols if c in df.columns]
    if not valid_cols:
        return bonus

    counts = df.groupby(valid_cols)[date_col].transform("count")
    # 2-3笔 +5, 4-6笔 +10, 7-10笔 +15, >10笔 +20
    bonus += ((counts >= 2) & (counts <= 3)).astype(int) * 5
    bonus += ((counts >= 4) & (counts <= 6)).astype(int) * 10
    bonus += ((counts >= 7) & (counts <= 10)).astype(int) * 15
    bonus += (counts > 10).astype(int) * 20
    return bonus


def score_executive_changes(df: pd.DataFrame) -> pd.DataFrame:
    """
    高管增减持评分（满分100）
    维度：交易金额（不论方向）、职位权重、关系人、增持加分、密集交易
    """
    if df.empty:
        return df

    scores = pd.Series(0, index=df.index, dtype=float)

    # 1. 交易金额评分（最高35分）—— 不论增减持，大金额都重要
    if "CHANGE_AMOUNT" in df.columns:
        amt = df["CHANGE_AMOUNT"].fillna(0).abs()
        scores += (amt >= 5e7).astype(int) * 35   # >= 5000万
        scores += ((amt >= 2e7) & (amt < 5e7)).astype(int) * 30  # >= 2000万
        scores += ((amt >= 5e6) & (amt < 2e7)).astype(int) * 20  # >= 500万
        scores += ((amt >= 1e6) & (amt < 5e6)).astype(int) * 10  # >= 100万

    # 2. 职位权重评分（最高25分）
    if "POSITION_NAME" in df.columns:
        pos = df["POSITION_NAME"].fillna("")
        top_exec = pos.str.contains("董事长|总经理|总裁|CEO", na=False, regex=True)
        scores += top_exec.astype(int) * 25
        mid_exec = pos.str.contains("副总|董事|监事|CFO|CTO", na=False, regex=True) & ~top_exec
        scores += mid_exec.astype(int) * 15
        other_exec = ~top_exec & ~mid_exec & (pos != "")
        scores += other_exec.astype(int) * 5

    # 3. 关系人评分（本人操作更重要）
    if "PERSON_DSE_RELATION" in df.columns:
        rel = df["PERSON_DSE_RELATION"].fillna("")
        scores += (rel == "本人").astype(int) * 15
        scores += rel.str.contains("配偶|子女", na=False, regex=True).astype(int) * 10

    # 4. 增持额外加分（增持比减持更积极的信号）
    if "CHANGE_SHARES" in df.columns:
        scores += (df["CHANGE_SHARES"].fillna(0) > 0).astype(int) * 5

    # 5. 密集交易加分（同一人多次交易，最高+20分）
    freq_bonus = _calc_frequency_bonus(
        df, ["SECURITY_CODE", "PERSON_NAME"], "CHANGE_DATE"
    )
    scores += freq_bonus

    df = df.copy()
    df["SCORE"] = scores.clip(upper=100).astype(int)
    df = _apply_portfolio_bonus(df, "SECURITY_CODE")
    return df


def score_buybacks(df: pd.DataFrame) -> pd.DataFrame:
    """
    股票回购评分（满分100）
    维度：回购金额上限、占总股本比例、实施进度
    """
    if df.empty:
        return df

    scores = pd.Series(0, index=df.index, dtype=float)

    # 1. 回购金额上限评分（最高50分）
    if "REPURAMOUNTLIMIT" in df.columns:
        amt = df["REPURAMOUNTLIMIT"].fillna(0)
        scores += (amt >= 5e8).astype(int) * 50   # >= 5亿
        scores += ((amt >= 1e8) & (amt < 5e8)).astype(int) * 30  # >= 1亿
        scores += ((amt >= 3e7) & (amt < 1e8)).astype(int) * 15  # >= 3000万

    # 2. 占总股本比例上限评分（最高30分）
    if "ZSZSX" in df.columns:
        pct = df["ZSZSX"].fillna(0)
        scores += (pct >= 5).astype(int) * 30
        scores += ((pct >= 2) & (pct < 5)).astype(int) * 20
        scores += ((pct >= 1) & (pct < 2)).astype(int) * 10

    # 3. 实施进度评分
    if "REPURPROGRESS" in df.columns:
        progress = df["REPURPROGRESS"].fillna("")
        scores += (progress == "004").astype(int) * 20  # 实施中
        scores += (progress == "001").astype(int) * 15  # 董事会预案
        scores += (progress == "002").astype(int) * 10  # 股东大会通过

    df = df.copy()
    df["SCORE"] = scores.clip(upper=100).astype(int)
    df = _apply_portfolio_bonus(df, "DIM_SCODE")
    return df


def score_equity_incentives(df: pd.DataFrame) -> pd.DataFrame:
    """
    股权激励评分（满分100）
    维度：激励股份数量、实施进度、行权价格折价率
    """
    if df.empty:
        return df

    scores = pd.Series(0, index=df.index, dtype=float)

    # 1. 激励股份数量评分（最高40分）- 单位：万股
    if "INCENTIVE_SHARES" in df.columns:
        shares = df["INCENTIVE_SHARES"].fillna(0)
        scores += (shares >= 5000).astype(int) * 40   # >= 5000万股
        scores += ((shares >= 1000) & (shares < 5000)).astype(int) * 25
        scores += ((shares >= 200) & (shares < 1000)).astype(int) * 10

    # 2. 实施进度评分（最高30分）
    if "PLAN_PROCESS" in df.columns:
        proc = df["PLAN_PROCESS"].fillna("")
        scores += proc.str.contains("实施", na=False).astype(int) * 30
        scores += proc.str.contains("董事会预案", na=False).astype(int) * 20
        scores += proc.str.contains("股东大会通过", na=False).astype(int) * 15

    # 3. 新公告加分（最近7天内的公告）
    if "LASTEST_NOTICE_DATE" in df.columns:
        try:
            notice = pd.to_datetime(df["LASTEST_NOTICE_DATE"], errors="coerce")
            recent = (pd.Timestamp.now() - notice).dt.days <= 7
            scores += recent.astype(int) * 20
        except Exception:
            pass

    df = df.copy()
    df["SCORE"] = scores.clip(upper=100).astype(int)
    df = _apply_portfolio_bonus(df, "SECURITY_CODE")
    return df
