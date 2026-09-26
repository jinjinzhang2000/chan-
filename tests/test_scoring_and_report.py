import unittest
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup

from fetcher_hk import extract_stock_code, _parse_position_value, _parse_pct_value, _parse_price
from notifier import build_html_report, _build_shareholder_table, _build_executive_table
from scorer import _as_percent, score_shareholder_changes
from scorer_hk import _normalize_hk_code


class ScoringTests(unittest.TestCase):
    def test_change_rate_percent_not_multiplied(self):
        # 2.0 means 2%, should land in the 1-3% bucket (20 pts), not 40.
        df = pd.DataFrame({
            "SECURITY_CODE": ["000001"],
            "CHANGE_RATE": [2.0],
            "TRADE_AMOUNT": [0],
            "DIRECTION": ["减持"],
        })
        scored = score_shareholder_changes(df)
        self.assertEqual(int(scored.iloc[0]["SCORE"]), 20)

    def test_change_rate_fraction_normalized(self):
        df = pd.DataFrame({
            "SECURITY_CODE": ["000001", "000002"],
            "CHANGE_RATE": [0.02, 0.03],
            "TRADE_AMOUNT": [0, 0],
            "DIRECTION": ["减持", "减持"],
        })
        scored = score_shareholder_changes(df)
        self.assertEqual(int(scored.iloc[0]["SCORE"]), 20)
        self.assertEqual(int(_as_percent(df["CHANGE_RATE"]).iloc[0]), 2)

    def test_increase_bonus(self):
        df = pd.DataFrame({
            "SECURITY_CODE": ["000001"],
            "CHANGE_RATE": [2.0],
            "TRADE_AMOUNT": [0],
            "DIRECTION": ["增持"],
        })
        scored = score_shareholder_changes(df)
        self.assertEqual(int(scored.iloc[0]["SCORE"]), 30)


class ReportTests(unittest.TestCase):
    def test_shareholder_nan_does_not_crash(self):
        df = pd.DataFrame([{
            "SECURITY_CODE": "000001",
            "SECURITY_NAME_ABBR": "测试",
            "HOLDER_NAME": "张三",
            "DIRECTION": "增持",
            "TRADE_AMOUNT": float("nan"),
            "CHANGE_RATE": float("nan"),
            "END_DATE": datetime(2024, 1, 1),
            "SCORE": 10,
            "IS_PORTFOLIO": False,
        }])
        html = _build_shareholder_table(df)
        self.assertNotIn("nan", html.lower())
        self.assertIn("000001", html)

    def test_executive_nan_amount(self):
        df = pd.DataFrame([{
            "SECURITY_CODE": "000001",
            "SECURITY_NAME": "测试",
            "PERSON_NAME": "李四",
            "POSITION_NAME": "董事",
            "CHANGE_AMOUNT": float("nan"),
            "CHANGE_DATE": datetime(2024, 1, 1),
            "SCORE": 8,
        }])
        html = _build_executive_table(df)
        self.assertNotIn("nan", html.lower())

    def test_full_report_empty_sections(self):
        html = build_html_report(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
            hk_insider_df=pd.DataFrame(),
        )
        self.assertIn("内部交易监控", html)
        self.assertIn("无数据", html)


class HkHelperTests(unittest.TestCase):
    def test_normalize_codes(self):
        self.assertEqual(_normalize_hk_code("HK:700"), "00700")
        self.assertEqual(_normalize_hk_code("09979.HK"), "09979")
        self.assertEqual(_normalize_hk_code("00700"), "00700")

    def test_extract_stock_code_from_link_and_name(self):
        cell = BeautifulSoup(
            '<td><a href="NSForm.aspx?sc=700">TENCENT</a></td>',
            "html.parser",
        ).td
        self.assertEqual(extract_stock_code(cell, "TENCENT"), "00700")
        self.assertEqual(extract_stock_code(None, "GreenTown (09979)"), "09979")

    def test_parse_helpers(self):
        self.assertEqual(_parse_position_value("11,067,400(L)")["L"], 11067400)
        self.assertAlmostEqual(_parse_pct_value("7.91(L)2.1(S)")["S"], 2.1)
        self.assertAlmostEqual(_parse_price("HKD 20.0900"), 20.09)


class ImportSmokeTests(unittest.TestCase):
    def test_config_and_main_import(self):
        import config
        import main
        self.assertGreater(config.DEFAULT_FETCH_DAYS, 0)
        self.assertTrue(hasattr(main, "main"))


if __name__ == "__main__":
    unittest.main()
