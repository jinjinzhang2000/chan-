"""
港股内部交易监控 - 评分引擎
对港股权益披露数据进行多维度打分

评分维度：
- 交易金额（HKD）：最高40分
- 投票权百分比：最高25分
- 披露人身份（董事 vs 大股东）：最高15分
- 密集交易：最高10分
- 方向加分（成为大股东等）：最高10分
"""
import os
import re

import pandas as pd

from config import PORTFOLIO_BONUS, PORTFOLIO_FILE


def load_hk_portfolio() -> set:
    """加载港股持仓代码集合（从portfolio.txt中读取HK:开头的行）"""
    if not os.path.exists(PORTFOLIO_FILE):
        return set()
    codes = set()
    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                token = line.split()[0]
                if token.upper().startswith("HK:"):
                    # HK:00700 -> 00700
                    code = token[3:]
                    codes.add(code)
    return codes


def _apply_hk_portfolio_bonus(df: pd.DataFrame) -> pd.DataFrame:
    """给港股持仓股票加分并标记（通过公司名匹配）"""
    hk_codes = load_hk_portfolio()
    if not hk_codes or df.empty:
        if not df.empty:
            df["IS_PORTFOLIO"] = False
        return df

    # 港股权益披露数据中没有直接的股票代码列
    # 通过CORP_NAME匹配（用户需要在portfolio.txt中配置公司名）
    # 或者用HK_PORTFOLIO_NAMES进行辅助匹配
    df["IS_PORTFOLIO"] = False

    # 尝试通过STOCK_CODE列匹配（如果后续添加了此列）
    if "STOCK_CODE" in df.columns:
        df["IS_PORTFOLIO"] = df["STOCK_CODE"].isin(hk_codes)

    df.loc[df["IS_PORTFOLIO"], "SCORE"] = (
        df.loc[df["IS_PORTFOLIO"], "SCORE"] + PORTFOLIO_BONUS
    ).clip(upper=130)

    df = df.sort_values(["IS_PORTFOLIO", "SCORE"], ascending=[False, False])
    return df


def _calc_hk_frequency_bonus(df: pd.DataFrame) -> pd.Series:
    """
    计算密集交易加分：同一公司+同一人在数据范围内交易次数越多，加分越高
    """
    bonus = pd.Series(0, index=df.index, dtype=float)
    if df.empty or "EVENT_DATE" not in df.columns:
        return bonus

    group_cols = [c for c in ["CORP_NAME", "PERSON_NAME"] if c in df.columns]
    if not group_cols:
        return bonus

    counts = df.groupby(group_cols)["EVENT_DATE"].transform("count")
    bonus += ((counts >= 2) & (counts <= 3)).astype(int) * 3
    bonus += ((counts >= 4) & (counts <= 6)).astype(int) * 6
    bonus += ((counts >= 7) & (counts <= 10)).astype(int) * 8
    bonus += (counts > 10).astype(int) * 10
    return bonus


def score_hk_insider_changes(df: pd.DataFrame) -> pd.DataFrame:
    """
    港股权益披露评分（满分100）
    维度：交易金额、投票权百分比、披露人身份、密集交易、方向
    """
    if df.empty:
        return df

    scores = pd.Series(0, index=df.index, dtype=float)

    # 1. 交易金额评分（最高40分）- HKD
    if "TRADE_AMOUNT" in df.columns:
        amt = df["TRADE_AMOUNT"].fillna(0).abs()
        scores += (amt >= 1e8).astype(int) * 40     # >= 1亿HKD
        scores += ((amt >= 5e7) & (amt < 1e8)).astype(int) * 25   # >= 5000万
        scores += ((amt >= 1e7) & (amt < 5e7)).astype(int) * 10   # >= 1000万

    # 2. 投票权百分比评分（最高25分）
    if "VOTING_PCT_L" in df.columns:
        pct = df["VOTING_PCT_L"].fillna(0).abs()
        scores += (pct >= 5).astype(int) * 25
        scores += ((pct >= 3) & (pct < 5)).astype(int) * 20
        scores += ((pct >= 1) & (pct < 3)).astype(int) * 15
        scores += ((pct >= 0.5) & (pct < 1)).astype(int) * 10

    # 3. 披露人身份评分（最高15分）
    if "FILER_TYPE" in df.columns:
        ftype = df["FILER_TYPE"].fillna("")
        scores += ftype.str.contains("董事|高管", na=False, regex=True).astype(int) * 15
        scores += (ftype == "大股东").astype(int) * 8

    # 4. 密集交易加分（最高10分）
    freq_bonus = _calc_hk_frequency_bonus(df)
    scores += freq_bonus

    # 5. 特殊原因代码加分（最高10分）
    if "REASON_CODE" in df.columns:
        reason = df["REASON_CODE"].fillna("")
        # 成为/不再是大股东 - 重要信号
        scores += reason.str.startswith("08").astype(int) * 10
        # 董事权益变动
        scores += reason.str.startswith("11").astype(int) * 5

    df = df.copy()
    df["SCORE"] = scores.clip(upper=100).astype(int)
    df = _apply_hk_portfolio_bonus(df)
    return df
