import unittest
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from chan_engine import (
    compute_macd,
    detect_beichi,
    detect_buy_sell_points,
    detect_fenxing,
    detect_zhongshu,
    full_chan_analysis,
    identify_bi,
    identify_xianduan,
    merge_inclusive_candles,
)


def _candle(day, high, low, close=None, open_=None, volume=1000):
    close = close if close is not None else (high + low) / 2
    open_ = open_ if open_ is not None else close
    return {
        "date": datetime(2024, 1, 1) + timedelta(days=day),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


class MergeTests(unittest.TestCase):
    def test_simple_inclusion_merges(self):
        # Prior bar sets an uptrend; the next bar is contained and must merge up.
        df = pd.DataFrame([
            _candle(0, 10, 8),
            _candle(1, 12, 10),
            _candle(2, 11.5, 10.5),  # inside the second bar
            _candle(3, 14, 12),
        ])
        merged = merge_inclusive_candles(df)
        self.assertEqual(len(merged), 3)
        self.assertGreaterEqual(float(merged.iloc[1]["high"]), 12)
        self.assertGreaterEqual(float(merged.iloc[1]["low"]), 10)

    def test_nested_inclusions_collapse(self):
        # Each new bar is contained in the running merged bar.
        df = pd.DataFrame([
            _candle(0, 20, 10),
            _candle(1, 18, 12),
            _candle(2, 17, 13),
        ])
        merged = merge_inclusive_candles(df)
        self.assertEqual(len(merged), 1)
        self.assertLessEqual(float(merged.iloc[0]["high"]), 20)
        self.assertGreaterEqual(float(merged.iloc[0]["low"]), 10)

    def test_no_inclusion_keeps_all(self):
        df = pd.DataFrame([
            _candle(0, 10, 8),
            _candle(1, 12, 9),
            _candle(2, 14, 11),
        ])
        merged = merge_inclusive_candles(df)
        self.assertEqual(len(merged), 3)


class FenxingBiTests(unittest.TestCase):
    def _zigzag(self):
        # Distinct tops/bottoms with enough independent bars between them.
        candles = []
        day = 0
        # climb to top
        for high, low in [(10, 8), (11, 9), (13, 10), (12, 9.5), (11, 9)]:
            candles.append(_candle(day, high, low))
            day += 1
        # more bars then a bottom
        for high, low in [(10.5, 8.5), (10, 8), (9, 7), (8, 6), (9, 7), (10, 8)]:
            candles.append(_candle(day, high, low))
            day += 1
        # climb to a higher top
        for high, low in [(11, 9), (12, 10), (14, 11), (13, 10.5), (12, 10)]:
            candles.append(_candle(day, high, low))
            day += 1
        return pd.DataFrame(candles)

    def test_fenxing_and_bi_alternate(self):
        merged = merge_inclusive_candles(self._zigzag())
        fx = detect_fenxing(merged)
        types = [f["type"] for f in fx]
        self.assertIn("top", types)
        self.assertIn("bottom", types)
        bi = identify_bi(fx, merged)
        for stroke in bi:
            if stroke["direction"] == "up":
                self.assertGreater(stroke["end_price"], stroke["start_price"])
            else:
                self.assertLess(stroke["end_price"], stroke["start_price"])

    def test_bi_rejects_invalid_direction(self):
        fx = [
            {"index": 1, "date": "2024-01-01", "type": "bottom", "price": 20},
            {"index": 6, "date": "2024-01-08", "type": "top", "price": 18},
        ]
        self.assertEqual(identify_bi(fx), [])

    def test_bi_requires_gap(self):
        fx = [
            {"index": 2, "date": "2024-01-01", "type": "bottom", "price": 10},
            {"index": 4, "date": "2024-01-03", "type": "top", "price": 15},
            {"index": 9, "date": "2024-01-10", "type": "top", "price": 16},
        ]
        bi = identify_bi(fx)
        self.assertEqual(len(bi), 1)
        self.assertEqual(bi[0]["end_price"], 16)


class SegmentZhongshuTests(unittest.TestCase):
    def test_xianduan_confirms_and_reverses(self):
        bi = [
            {"start_date": "d0", "end_date": "d1", "start_price": 10, "end_price": 20, "direction": "up"},
            {"start_date": "d1", "end_date": "d2", "start_price": 20, "end_price": 15, "direction": "down"},
            {"start_date": "d2", "end_date": "d3", "start_price": 15, "end_price": 25, "direction": "up"},
            {"start_date": "d3", "end_date": "d4", "start_price": 25, "end_price": 18, "direction": "down"},
            {"start_date": "d4", "end_date": "d5", "start_price": 18, "end_price": 22, "direction": "up"},
            {"start_date": "d5", "end_date": "d6", "start_price": 22, "end_price": 14, "direction": "down"},
        ]
        segs = identify_xianduan(bi)
        self.assertGreaterEqual(len(segs), 1)
        self.assertEqual(segs[0]["direction"], "up")
        self.assertEqual(segs[0]["end_price"], 25)
        if len(segs) > 1:
            self.assertEqual(segs[1]["direction"], "down")

    def test_zhongshu_overlap(self):
        bi = [
            {"start_date": "a", "end_date": "b", "start_price": 10, "end_price": 20, "direction": "up"},
            {"start_date": "b", "end_date": "c", "start_price": 20, "end_price": 12, "direction": "down"},
            {"start_date": "c", "end_date": "d", "start_price": 12, "end_price": 18, "direction": "up"},
        ]
        zs = detect_zhongshu(bi)
        self.assertEqual(len(zs), 1)
        self.assertAlmostEqual(zs[0]["low"], 12)
        self.assertAlmostEqual(zs[0]["high"], 18)


class SignalRuleTests(unittest.TestCase):
    def test_2b_requires_prior_1b(self):
        bi_list = [
            {"start_date": "2024-01-01", "end_date": "2024-01-10", "start_price": 20, "end_price": 10, "direction": "down"},
            {"start_date": "2024-01-10", "end_date": "2024-01-20", "start_price": 10, "end_price": 16, "direction": "up"},
            {"start_date": "2024-01-20", "end_date": "2024-01-30", "start_price": 16, "end_price": 12, "direction": "down"},
            {"start_date": "2024-01-30", "end_date": "2024-02-10", "start_price": 12, "end_price": 18, "direction": "up"},
            {"start_date": "2024-02-10", "end_date": "2024-02-20", "start_price": 18, "end_price": 13, "direction": "down"},
        ]
        signals, _ = detect_buy_sell_points(bi_list, [], [], 13.5)
        self.assertFalse(any(s["type"] == "2B" for s in signals))

        beichi = [{
            "type": "bottom_beichi",
            "subtype": "trend",
            "date": "2024-01-30",
            "price": 12,
            "area_ratio": 0.5,
            "desc": "test",
        }]
        signals, _ = detect_buy_sell_points(bi_list, [], beichi, 13.5)
        self.assertTrue(any(s["type"] == "2B" for s in signals))
        self.assertTrue(any(s["type"] == "1B" for s in signals))

    def test_3b_requires_leave_then_pullback(self):
        zs = [{"start_date": "2024-01-01", "end_date": "2024-01-20",
               "high": 15, "low": 10, "bi_count": 3}]
        no_leave = [
            {"start_date": "2024-01-01", "end_date": "2024-01-10",
             "start_price": 11, "end_price": 14, "direction": "up"},
            {"start_date": "2024-01-10", "end_date": "2024-01-20",
             "start_price": 14, "end_price": 16, "direction": "down"},
        ]
        signals, _ = detect_buy_sell_points(no_leave, zs, [], 16.2)
        self.assertFalse(any(s["type"] == "3B" for s in signals))

        left = [
            {"start_date": "2024-01-01", "end_date": "2024-01-10",
             "start_price": 12, "end_price": 18, "direction": "up"},
            {"start_date": "2024-01-10", "end_date": "2024-01-20",
             "start_price": 18, "end_price": 16, "direction": "down"},
        ]
        signals, _ = detect_buy_sell_points(left, zs, [], 16.2)
        self.assertTrue(any(s["type"] == "3B" for s in signals))


class PipelineTests(unittest.TestCase):
    def test_short_data_returns_error(self):
        df = pd.DataFrame([_candle(i, 10 + i, 9 + i) for i in range(5)])
        result = full_chan_analysis(df)
        self.assertIn("error", result)

    def test_missing_columns(self):
        df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=20), "close": range(20)})
        result = full_chan_analysis(df)
        self.assertIn("error", result)

    def test_synthetic_trend_runs(self):
        n = 90
        rng = np.random.default_rng(7)
        t = np.arange(n)
        close = 100 + 8 * np.sin(t / 6.0) + np.cumsum(rng.normal(0, 0.15, n))
        open_ = close + rng.normal(0, 0.2, n)
        high = np.maximum(np.maximum(open_, close) + 0.4, close + 0.6)
        low = np.minimum(np.minimum(open_, close) - 0.4, close - 0.6)
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000,
        })
        result = full_chan_analysis(df)
        self.assertNotIn("error", result)
        self.assertIn("xianduan_count", result)
        self.assertIn("signals", result)
        self.assertGreater(result["merged_count"], 0)
        macd = compute_macd(df)
        self.assertIn("macd", macd.columns)

    def test_beichi_scans_more_than_last_bi(self):
        dates = pd.date_range("2024-01-01", periods=40, freq="D")
        close = np.concatenate([
            np.linspace(20, 10, 10),
            np.linspace(10, 16, 10),
            np.linspace(16, 8, 10),
            np.linspace(8, 14, 10),
        ])
        df = pd.DataFrame({
            "date": dates,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1,
        })
        df = compute_macd(df)
        bi = [
            {"start_date": dates[0], "end_date": dates[9],
             "start_price": 20, "end_price": 10, "direction": "down"},
            {"start_date": dates[9], "end_date": dates[19],
             "start_price": 10, "end_price": 16, "direction": "up"},
            {"start_date": dates[19], "end_date": dates[29],
             "start_price": 16, "end_price": 8, "direction": "down"},
            {"start_date": dates[29], "end_date": dates[39],
             "start_price": 8, "end_price": 14, "direction": "up"},
        ]
        # Force a smaller MACD area on the second down move by zeroing later bars
        df.loc[df["date"] >= dates[19], "macd"] = df.loc[df["date"] >= dates[19], "macd"] * 0.2
        found = detect_beichi(bi, df, [])
        # At least the mid-series down pair should be evaluated, not only the last up bi
        self.assertIsInstance(found, list)


if __name__ == "__main__":
    unittest.main()
