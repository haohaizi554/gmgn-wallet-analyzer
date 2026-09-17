from __future__ import annotations

import unittest

from app.gui.viz_metrics import parse_number, parse_percent, snapshot_from_payload


class ParseNumberTests(unittest.TestCase):
    def test_compact_and_audit_values(self):
        self.assertEqual(parse_number("$14.20K"), 14200.0)
        self.assertEqual(parse_number("-$1.50M"), -1_500_000.0)
        self.assertAlmostEqual(parse_number("$50.83"), 50.83)
        self.assertEqual(parse_number({"value": "12.5", "status": "KNOWN"}), 12.5)
        self.assertIsNone(parse_number("未实现"))
        self.assertIsNone(parse_number("不适用（转入）"))

    def test_percent_strings(self):
        self.assertEqual(parse_percent("38.50%"), 38.5)
        self.assertEqual(parse_percent(1.5), 150.0)


class SnapshotTests(unittest.TestCase):
    def test_win_rate_and_daily_curve(self):
        payload = {
            "wallet": {"address": "QGRe9GTHJxG3zZUJaaaaaaaaaaaaaaaaaaaaaaa", "period": "7d"},
            "meta": {"status": "SUCCESS"},
            "summary": {
                "token_count": 3,
                "buy_count": 4,
                "sell_count": 3,
                "open_positions": 1,
                "gmgn_realized_profit": {"value": "100.5"},
                "gmgn_total_profit": {"value": "80"},
                "gas_total_usd": {"value": "1.2"},
            },
            "tokens": [
                {"币种": "AAA", "代币合约": "mintA", "本地FIFO已实现": "$80.0000", "总盈亏": "$80.0000", "总盈亏%": "120.00%", "买入总额": "$40.00", "卖出总额": "$120.00", "来源平台": "pump.fun", "获得方式": "BUY", "持仓状态": "已清仓"},
                {"币种": "BBB", "代币合约": "mintB", "已实现盈亏": "-$20.0000", "总盈亏": "-$20.0000", "总盈亏%": "-50.00%", "买入总额": "$40.00", "卖出总额": "$20.00", "来源平台": "Raydium", "获得方式": "BUY", "持仓状态": "已清仓"},
                {"币种": "CCC", "代币合约": "mintC", "本地FIFO已实现": "$0.0000", "总盈亏": "$12.0000", "总盈亏%": "10.00%", "买入总额": "$10.00", "卖出总额": "$0.00", "来源平台": "pump.fun", "获得方式": "TRANSFER_IN", "持仓状态": "仍持仓"},
            ],
            "trades": [
                {"时间": "2026-09-16 10:00:00", "类型": "buy", "USD金额": "$40.00", "单笔盈亏": "未实现"},
                {"时间": "2026-09-16 12:00:00", "类型": "sell", "USD金额": "$120.00", "单笔盈亏": "$80.0000"},
                {"时间": "2026-09-17 09:00:00", "类型": "sell", "USD金额": "$20.00", "单笔盈亏": "-$20.0000"},
            ],
        }
        snap = snapshot_from_payload(payload, source="test.json")
        self.assertEqual(snap.win_count, 1)
        self.assertEqual(snap.loss_count, 1)
        self.assertEqual(snap.flat_count, 1)
        self.assertAlmostEqual(snap.win_rate, 0.5)
        self.assertAlmostEqual(snap.profit_factor, 4.0)
        self.assertEqual(len(snap.daily), 2)
        self.assertAlmostEqual(snap.daily[0].realized, 80.0)
        self.assertAlmostEqual(snap.daily[1].cumulative, 60.0)
        self.assertEqual(snap.platforms[0].name, "pump.fun")
        self.assertEqual(snap.platforms[0].count, 2)
        self.assertIn("胜率 50%", snap.insight)
        self.assertIn("AAA", snap.insight)
        self.assertIn("BBB", snap.insight)
