---
name: chan-monitor
description: Start real-time Chan Theory (缠论) monitoring for specified tickers. Continuously checks for new buy/sell points during market hours.
argument-hint: "[ticker(s)] [--interval seconds] e.g. TME 600988.SS --interval 300"
disable-model-invocation: true
---

## Task

Start the 缠论 real-time monitor for: $ARGUMENTS

## Steps

1. Parse arguments: extract ticker symbols and --interval value (default: 300s).

2. Map Chinese names to yfinance tickers (see mapping below).

3. Update the SYMBOLS dict in `chan_monitor.py` (in the project root) if new tickers are requested.

4. Run the monitor from the project root:

```bash
python3 chan_monitor.py --symbols <TICKER_KEYS> --interval <SECONDS>
```

For one-time check (or if market is closed):
```bash
python3 chan_monitor.py --once --symbols <TICKER_KEYS>
```

## Ticker Mapping

```python
SYMBOLS = {
    "SIL": "SI=F",        # 白银 Silver Futures
    "HST": "3032.HK",     # 恒生科技 HSTECH ETF
    "TME": "TME",         # 腾讯音乐
    "SF":  "002352.SZ",   # 顺丰控股
    "GDX": "GDX",         # Gold Miners ETF
    "TL":  "000630.SZ",   # 铜陵有色
    "GC":  "9979.HK",     # 绿城管理
    "GAME": "159869.SZ",  # 游戏ETF
    "LQ":  "688008.SS",   # 澜起科技
    "CF":  "600988.SS",   # 赤峰黄金
    "PW":  "002624.SZ",   # 完美世界
}
```

## Market Hours

- A股: 09:30-15:00 CST (Mon-Fri)
- HK: 09:30-16:00 HKT (Mon-Fri)
- US: 09:30-16:00 EST (Mon-Fri)
- Silver futures: ~24h Sun evening - Fri afternoon EST
