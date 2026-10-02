#!/usr/bin/env python3
"""
缠论实时监控 (Chan Theory Real-Time Monitor)

动态监控白银(Silver)和恒生科技指数(HSTECH)的价格走势，
应用缠论分析框架，在出现买卖点信号时发出警报。

用法:
    python3 chan_monitor.py                    # 默认监控，每5分钟刷新
    python3 chan_monitor.py --interval 60      # 每60秒刷新
    python3 chan_monitor.py --once             # 只分析一次
    python3 chan_monitor.py --symbols SIL HST  # 只监控指定标的
"""

import argparse
import sys
import time
from datetime import datetime

import pandas as pd
import yfinance as yf

from chan_engine import full_chan_analysis

# ─────────────────────────────────────────────
# 监控标的配置
# ─────────────────────────────────────────────

SYMBOLS = {
    "SIL": {
        "ticker": "SI=F",
        "name": "白银期货 (Silver Futures)",
        "name_short": "白银",
    },
    "HST": {
        "ticker": "3032.HK",
        "name": "恒生科技ETF (HSTECH Tracker)",
        "name_short": "恒科",
    },
    "TME": {
        "ticker": "TME",
        "name": "腾讯音乐 (TME)",
        "name_short": "腾讯音乐",
    },
    "SF": {
        "ticker": "002352.SZ",
        "name": "顺丰控股",
        "name_short": "顺丰",
    },
    "GDX": {
        "ticker": "GDX",
        "name": "Gold Miners ETF",
        "name_short": "GDX",
    },
    "TL": {
        "ticker": "000630.SZ",
        "name": "铜陵有色",
        "name_short": "铜陵有色",
    },
    "GC": {
        "ticker": "9979.HK",
        "name": "绿城管理",
        "name_short": "绿城",
    },
    "GAME": {
        "ticker": "159869.SZ",
        "name": "游戏ETF",
        "name_short": "游戏ETF",
    },
    "LQ": {
        "ticker": "688008.SS",
        "name": "澜起科技",
        "name_short": "澜起",
    },
    "CF": {
        "ticker": "600988.SS",
        "name": "赤峰黄金",
        "name_short": "赤峰黄金",
    },
    "PW": {
        "ticker": "002624.SZ",
        "name": "完美世界",
        "name_short": "完美世界",
    },
}

# 多级别分析配置: (yfinance period, yfinance interval, label)
TIMEFRAMES = [
    ("2y", "1wk", "周线"),
    ("6mo", "1d", "日线"),
    ("5d", "60m", "60分钟"),
]


# ─────────────────────────────────────────────
# 数据获取
# ─────────────────────────────────────────────

def fetch_ohlcv(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """从yfinance获取OHLCV数据并标准化列名"""
    try:
        data = yf.download(ticker, period=period, interval=interval,
                           progress=False, auto_adjust=True)
        if data.empty:
            return pd.DataFrame()

        # yfinance >= 1.0 often returns MultiIndex columns (Price, Ticker)
        if isinstance(data.columns, pd.MultiIndex):
            names = list(data.columns.names)
            if "Ticker" in names:
                data = data.droplevel("Ticker", axis=1)
            elif data.columns.nlevels > 1:
                data = data.droplevel(-1, axis=1)

        df = data.reset_index()

        # 统一列名 (case-insensitive mapping)
        col_map = {}
        for c in df.columns:
            cl = str(c).lower().strip()
            if cl in ("date", "datetime"):
                col_map[c] = "date"
            elif cl == "open":
                col_map[c] = "open"
            elif cl == "high":
                col_map[c] = "high"
            elif cl == "low":
                col_map[c] = "low"
            elif cl == "close":
                col_map[c] = "close"
            elif cl == "volume":
                col_map[c] = "volume"
        df = df.rename(columns=col_map)

        needed = ["date", "open", "high", "low", "close"]
        for col in needed:
            if col not in df.columns:
                return pd.DataFrame()

        if "volume" not in df.columns:
            df["volume"] = 0

        df = df[["date", "open", "high", "low", "close", "volume"]].copy()
        df = df.dropna(subset=["open", "high", "low", "close"])

        # 确保数值类型
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna()

        return df
    except Exception as e:
        print(f"  ⚠ 获取数据失败 ({ticker}, {period}, {interval}): {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# 输出格式化
# ─────────────────────────────────────────────

def format_signal(sig: dict) -> str:
    """格式化单个买卖点信号，包含状态标记"""
    emoji = "🟢" if "B" in sig["type"] else "🔴"
    status = sig.get("status", "unknown")
    if status == "active":
        tag = "⚡当前有效"
    elif status == "historical":
        tag = "📜已过(历史信号)"
    else:
        tag = ""
    return f"  {emoji} [{sig['type']}] {sig['name']} | 价格: {sig['price']:.2f} | {tag} | {sig['desc']}"


def format_zhongshu(zs: dict) -> str:
    """格式化中枢信息"""
    return f"  📦 中枢区间: [{zs['low']:.2f} — {zs['high']:.2f}] | 笔数: {zs['bi_count']} | {str(zs['start_date'])[:10]} ~ {str(zs['end_date'])[:10]}"


def trend_label(trend: str) -> str:
    labels = {
        "uptrend": "📈 上涨趋势",
        "downtrend": "📉 下跌趋势",
        "consolidation": "📊 中枢震荡/盘整",
    }
    return labels.get(trend, trend)


def print_analysis(symbol_key: str, cfg: dict, results: dict):
    """打印单个标的多级别分析结果"""
    print(f"\n{'='*60}")
    print(f"  {cfg['name']}")
    print(f"{'='*60}")

    has_signal = False

    for tf_label, result in results.items():
        if "error" in result:
            print(f"\n  【{tf_label}】数据不足，跳过")
            continue

        print(f"\n  ─── {tf_label}级别 ───")
        print(f"  当前价: {result['current_price']:.2f} | 最新: {str(result['last_date'])[:16]}")
        print(f"  趋势: {trend_label(result['trend'])}")
        xd_count = result.get("xianduan_count", 0)
        print(
            f"  结构: {result['bi_count']}笔 | {xd_count}线段 | "
            f"{result['fenxing_count']}分型 | {result['zhongshu_count']}中枢"
        )

        # MACD状态
        m = result["macd_latest"]
        macd_state = "金叉" if m["dif"] > m["dea"] else "死叉"
        macd_dir = "↑" if m["macd"] > 0 else "↓"
        print(f"  MACD: DIF={m['dif']:.4f} DEA={m['dea']:.4f} MACD={m['macd']:.4f} ({macd_state}{macd_dir})")

        # 中枢
        if result["zhongshu"]:
            for zs in result["zhongshu"][-2:]:  # 最近2个中枢
                print(format_zhongshu(zs))

        # 背驰
        if result["beichi"]:
            for bc in result["beichi"]:
                emoji = "⚡"
                bc_type = "顶背驰" if bc["type"] == "top_beichi" else "底背驰"
                subtype = bc.get("subtype", "")
                sub_label = "(趋势)" if subtype == "trend" else "(盘整)" if subtype == "consolidation" else ""
                desc = bc.get("desc", f"面积比={bc.get('area_ratio', bc.get('strength_ratio', 0)):.2f}")
                print(f"  {emoji} {bc_type}{sub_label} @ {bc['price']:.2f} | {desc}")

        # 当前走势状态（未完成的笔）
        forming = result.get("forming")
        if forming:
            print(f"  🔄 {forming['name']}: {forming['desc']}")

        # 买卖点信号（区分活跃和历史）
        if result["signals"]:
            active_signals = [s for s in result["signals"] if s.get("status") == "active"]
            hist_signals = [s for s in result["signals"] if s.get("status") == "historical"]

            if active_signals:
                has_signal = True
                print(f"  *** 当前有效买卖点 ***")
                for sig in active_signals:
                    print(format_signal(sig))

            if hist_signals:
                print(f"  --- 历史信号(已过) ---")
                for sig in hist_signals:
                    print(format_signal(sig))

    if not has_signal:
        print(f"\n  ℹ️  当前无可操作的买卖点信号，继续观察")

    return has_signal


# ─────────────────────────────────────────────
# 监控主循环
# ─────────────────────────────────────────────

def run_analysis(symbol_keys: list) -> dict:
    """运行一轮完整分析"""
    all_signals = {}

    for key in symbol_keys:
        cfg = SYMBOLS[key]
        results = {}

        for period, interval, label in TIMEFRAMES:
            df = fetch_ohlcv(cfg["ticker"], period, interval)
            if df.empty:
                results[label] = {"error": "no data"}
                continue
            result = full_chan_analysis(df)
            results[label] = result

        has_signal = print_analysis(key, cfg, results)
        all_signals[key] = {
            "has_signal": has_signal,
            "results": results,
        }

    return all_signals


def monitor_loop(symbol_keys: list, interval_sec: int):
    """持续监控循环"""
    print(f"\n🔍 缠论实时监控启动")
    print(f"   标的: {', '.join(SYMBOLS[k]['name_short'] for k in symbol_keys)}")
    print(f"   级别: {', '.join(tf[2] for tf in TIMEFRAMES)}")
    print(f"   刷新: 每{interval_sec}秒")
    print(f"   按 Ctrl+C 停止\n")

    cycle = 0
    while True:
        cycle += 1
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'#'*60}")
        print(f"  监控周期 #{cycle} | {ts}")
        print(f"{'#'*60}")

        try:
            all_signals = run_analysis(symbol_keys)

            # 汇总
            print(f"\n{'─'*60}")
            print(f"  📋 本轮汇总 ({ts})")
            print(f"{'─'*60}")
            for key in symbol_keys:
                name = SYMBOLS[key]["name_short"]
                info = all_signals.get(key, {})
                if info.get("has_signal"):
                    print(f"  🚨 {name}: 发现买卖点信号！请查看上方详情")
                else:
                    print(f"  ✅ {name}: 暂无信号")

        except Exception as e:
            print(f"  ❌ 分析出错: {e}")

        print(f"\n  ⏳ 下次刷新: {interval_sec}秒后...")
        try:
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            print("\n\n👋 监控已停止")
            sys.exit(0)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="缠论实时监控 - 白银 & 恒生科技")
    parser.add_argument("--interval", type=int, default=300,
                        help="刷新间隔(秒), 默认300")
    parser.add_argument("--once", action="store_true",
                        help="只分析一次，不循环")
    parser.add_argument("--symbols", nargs="+", default=["SIL", "HST"],
                        choices=sorted(SYMBOLS.keys()),
                        help="监控标的，默认 SIL HST。可选: " + ", ".join(sorted(SYMBOLS)))
    args = parser.parse_args()

    if args.once:
        print(f"\n🔍 缠论单次分析 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        run_analysis(args.symbols)
    else:
        monitor_loop(args.symbols, args.interval)


if __name__ == "__main__":
    main()
