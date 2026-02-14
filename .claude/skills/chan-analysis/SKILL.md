---
name: chan-analysis
description: Run Chan Theory (缠论) multi-timeframe analysis on stocks/ETFs. Analyzes weekly and daily levels for bi, zhongshu, beichi, and buy/sell points with MACD area comparison.
argument-hint: "[ticker(s)] e.g. TME, 600988.SS, SI=F, 赤峰黄金"
---

## Task

Run a complete 缠论 (Chan Theory) analysis on the given ticker(s): $ARGUMENTS

## Steps

1. Locate `chan_engine.py` in the current project root directory (same directory as this .claude folder).

2. For each ticker, run multi-timeframe analysis at **周线 (weekly: period=2y, interval=1wk)** and **日线 (daily: period=6mo, interval=1d)** levels using the following Python pattern:

```python
import pandas as pd, sys, os
import yfinance as yf

# Auto-detect project root (where chan_engine.py lives)
project_root = os.path.dirname(os.path.abspath('chan_engine.py'))
sys.path.insert(0, project_root)
from chan_engine import full_chan_analysis, compute_macd

def fetch(ticker, period, interval):
    data = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        data = data.droplevel('Ticker', axis=1)
    df = data.reset_index()
    col_map = {}
    for c in df.columns:
        cl = str(c).lower().strip()
        if cl in ('date','datetime'): col_map[c] = 'date'
        elif cl == 'open': col_map[c] = 'open'
        elif cl == 'high': col_map[c] = 'high'
        elif cl == 'low': col_map[c] = 'low'
        elif cl == 'close': col_map[c] = 'close'
        elif cl == 'volume': col_map[c] = 'volume'
    df = df.rename(columns=col_map)
    if 'volume' not in df.columns: df['volume'] = 0
    df = df[['date','open','high','low','close','volume']].copy()
    df = df.dropna()
    for col in ['open','high','low','close','volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna()
    return df
```

3. For each level, output:
   - All 笔 (bi/strokes) with dates, prices, direction, percentage change
   - All 中枢 (zhongshu/hubs) with range, time span, bi count
   - 趋势 (trend) determination
   - MACD status (DIF, DEA, MACD histogram)
   - 背驰 (beichi/divergence) details: MACD area ratio, DIF peak ratio, DIF zero-axis crossback
   - 买卖点 (buy/sell points): type (1B/2B/3B/1S/2S/3S), price, status (active/historical)
   - Forming info (incomplete stroke direction and progress %)
   - MACD area comparison for same-direction bi segments

## Output Format

Present results in Chinese:

### [Ticker Name] — 当前价: ¥XX.XX

#### 周线级别
- ASCII chart showing bi structure
- Table of all bi with dates and prices
- Zhongshu details
- MACD status and beichi analysis
- Signals

#### 日线级别
(Same structure)

#### 多级别总结
- 周线定方向，日线定入场
- Highlight 多级别共振 (multi-level resonance) if present
- Support/resistance levels from zhongshu boundaries

#### 操作参考
- Entry point, stop loss, target prices
- Key confirmation signals to watch (e.g. MACD golden cross)

## Ticker Mapping (Common Chinese Names)

- 白银 / Silver → SI=F
- 恒生科技 / HSTECH → 3032.HK
- 游戏ETF → 159869.SZ
- 澜起科技 → 688008.SS
- 赤峰黄金 → 600988.SS
- 完美世界 → 002624.SZ
- 顺丰控股 → 002352.SZ
- 铜陵有色 → 000630.SZ
- 腾讯音乐 → TME
- 绿城管理 → 9979.HK
- A股 tickers: .SS (Shanghai) or .SZ (Shenzhen)
- HK tickers: .HK
- US tickers: use directly

## Key 缠论 Rules

- **1买 (1B)**: Requires 背驰. 趋势背驰 (DIF crossed zero) > 盘整背驰.
- **2买 (2B)**: Pullback after 1B does not create new low.
- **3买 (3B)**: Pullback stays above zhongshu upper boundary.
- **1卖 (1S)**: Requires top 背驰.
- **2卖 (2S)**: Bounce does not create new high.
- **3卖 (3S)**: Bounce stays below zhongshu lower boundary.
- **Signal freshness**: Active (within 5% of current price) vs Historical (>5% away).
- **MACD面积**: Sum of |MACD histogram| bars within a bi = total energy of that move.
- **趋势背驰 vs 盘整背驰**: DIF crossed zero between compared segments → 趋势背驰 (stronger).
