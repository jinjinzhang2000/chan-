#!/usr/bin/env python3
"""
A股内部交易监控工具 - 主入口
用法:
    python main.py                    # 默认抓取3天数据，发送邮件
    python main.py --no-email         # 不发邮件，终端打印 + 生成HTML文件
    python main.py --days 7           # 抓取最近7天数据
    python main.py --min-score 50     # 只显示评分>=50的记录
    python main.py --save-html        # 保存HTML报告到本地
"""
import argparse
import os
from datetime import datetime

import pandas as pd

from config import DEFAULT_FETCH_DAYS, MIN_SCORE
from fetcher import (fetch_buybacks, fetch_equity_incentives,
                     fetch_executive_changes, fetch_shareholder_changes)
from fetcher_hk import fetch_hk_insider_changes
from notifier import build_html_report, send_email
from scorer import (score_buybacks, score_equity_incentives,
                    score_executive_changes, score_shareholder_changes)
from scorer_hk import score_hk_insider_changes


def print_section(title: str, df: pd.DataFrame, columns: list, min_score: int):
    """终端打印一个板块的筛选结果"""
    filtered = df[df["SCORE"] >= min_score] if not df.empty else df
    print(f"\n{'='*70}")
    print(f"  {title}  （共{len(df)}条，筛选后{len(filtered)}条，阈值>={min_score}分）")
    print(f"{'='*70}")

    if filtered.empty:
        print("  （无符合条件的记录）")
        return

    # 标记持仓
    display_cols = [c for c in columns if c in filtered.columns]
    display = filtered[display_cols].copy()

    # 添加持仓标记列
    if "IS_PORTFOLIO" in filtered.columns:
        display.insert(0, "★", filtered["IS_PORTFOLIO"].map({True: "★", False: ""}))

    pd.set_option("display.max_colwidth", 16)
    pd.set_option("display.unicode.east_asian_width", True)
    print(display.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="A股内部交易监控工具")
    parser.add_argument("--days", type=int, default=DEFAULT_FETCH_DAYS,
                        help=f"抓取最近N天数据（默认{DEFAULT_FETCH_DAYS}）")
    parser.add_argument("--min-score", type=int, default=MIN_SCORE,
                        help=f"最低评分阈值（默认{MIN_SCORE}）")
    parser.add_argument("--no-email", action="store_true",
                        help="不发送邮件，仅终端打印")
    parser.add_argument("--save-html", action="store_true",
                        help="保存HTML报告到本地文件")
    parser.add_argument("--no-hk", action="store_true",
                        help="不抓取港股数据")
    parser.add_argument("--hk-only", action="store_true",
                        help="只抓取港股数据")
    args = parser.parse_args()

    print(f"\n🔍 A股+港股内部交易监控 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   抓取范围：最近 {args.days} 天 | 评分阈值：>= {args.min_score}")
    print()

    # 1. 抓取A股数据
    sh_scored = pd.DataFrame()
    ex_scored = pd.DataFrame()
    bb_scored = pd.DataFrame()
    ei_scored = pd.DataFrame()

    if not args.hk_only:
        sh_df = fetch_shareholder_changes(days=args.days)
        ex_df = fetch_executive_changes(days=args.days)
        bb_df = fetch_buybacks(days=max(args.days, 30))  # 回购至少30天
        ei_df = fetch_equity_incentives(days=max(args.days, 30))

        # 2. A股评分
        print("\n📈 正在计算A股综合评分...")
        sh_scored = score_shareholder_changes(sh_df)
        ex_scored = score_executive_changes(ex_df)
        bb_scored = score_buybacks(bb_df)
        ei_scored = score_equity_incentives(ei_df)

    # 3. 抓取港股数据
    hk_scored = pd.DataFrame()

    if not args.no_hk:
        print()
        hk_df = fetch_hk_insider_changes(days=args.days)
        if not hk_df.empty:
            print("\n📈 正在计算港股综合评分...")
            hk_scored = score_hk_insider_changes(hk_df)

    # 4. 筛选
    sh_filtered = sh_scored[sh_scored["SCORE"] >= args.min_score] if not sh_scored.empty else sh_scored
    ex_filtered = ex_scored[ex_scored["SCORE"] >= args.min_score] if not ex_scored.empty else ex_scored
    bb_filtered = bb_scored[bb_scored["SCORE"] >= args.min_score] if not bb_scored.empty else bb_scored
    ei_filtered = ei_scored[ei_scored["SCORE"] >= args.min_score] if not ei_scored.empty else ei_scored
    hk_filtered = hk_scored[hk_scored["SCORE"] >= args.min_score] if not hk_scored.empty else hk_scored

    total = len(sh_filtered) + len(ex_filtered) + len(bb_filtered) + len(ei_filtered) + len(hk_filtered)
    print(f"\n  ✅ 筛选完成，共 {total} 条重要信号\n")

    # 5. 终端打印 - A股
    if not args.hk_only:
        print_section(
            "📊 大股东增减持", sh_scored,
            ["SECURITY_CODE", "SECURITY_NAME_ABBR", "HOLDER_NAME", "DIRECTION",
             "TRADE_AMOUNT", "CHANGE_RATE", "END_DATE", "SCORE"],
            args.min_score,
        )
        print_section(
            "👔 高管增减持", ex_scored,
            ["SECURITY_CODE", "SECURITY_NAME", "PERSON_NAME", "POSITION_NAME",
             "CHANGE_AMOUNT", "CHANGE_DATE", "SCORE"],
            args.min_score,
        )
        print_section(
            "🔄 股票回购", bb_scored,
            ["DIM_SCODE", "SECURITYSHORTNAME", "REPURAMOUNTLIMIT", "REPURAMOUNT",
             "PROGRESS_TEXT", "UPDATEDATE", "SCORE"],
            args.min_score,
        )
        print_section(
            "🎯 股权激励", ei_scored,
            ["SECURITY_CODE", "SECURITY_NAME_ABBR", "PLAN_PROCESS", "EI_TARGET",
             "INCENTIVE_SHARES", "EXERCISE_PRICE", "LASTEST_NOTICE_DATE", "SCORE"],
            args.min_score,
        )

    # 终端打印 - 港股
    if not args.no_hk:
        print_section(
            "🇭🇰 港股权益披露", hk_scored,
            ["CORP_NAME", "PERSON_NAME", "FILER_TYPE", "REASON_TEXT",
             "TRADE_AMOUNT", "VOTING_PCT_L", "EVENT_DATE", "SCORE"],
            args.min_score,
        )

    # 6. 生成HTML报告
    html = build_html_report(sh_filtered, ex_filtered, bb_filtered, ei_filtered,
                             hk_insider_df=hk_filtered)

    # 6. 保存HTML
    if args.save_html or args.no_email:
        report_dir = os.path.join(os.path.dirname(__file__), "reports")
        os.makedirs(report_dir, exist_ok=True)
        filename = f"insider_report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
        filepath = os.path.join(report_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n📄 HTML报告已保存: {filepath}")

    # 7. 发送邮件
    if not args.no_email:
        print("\n📧 正在发送邮件...")
        send_email(html)

    print(f"\n✅ 监控完成！")


if __name__ == "__main__":
    main()
