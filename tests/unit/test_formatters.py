from __future__ import annotations

import unittest

from app.domain.formatters import format_duration_zh, format_hms_unbounded, safe_export_value
from app.domain.enums import FieldStatus
from app.utils.validators import parse_wallet_lines, validate_solana_address


class FormatterTests(unittest.TestCase):
    def test_duration_and_hms(self):
        self.assertEqual(format_duration_zh(54), "54秒")
        self.assertEqual(format_duration_zh(12 * 60), "12分钟")
        self.assertIn("小时", format_duration_zh(5 * 3600 + 32 * 60))
        self.assertEqual(format_duration_zh(668 * 86400 + 5 * 3600), "668天5小时")
        self.assertEqual(format_hms_unbounded(6 * 60 + 14), "00:06:14")
        self.assertTrue(format_hms_unbounded(25 * 3600).startswith("25:"))
        self.assertEqual(format_duration_zh(-23), "-23秒")
        self.assertEqual(format_duration_zh(-100), "-1分钟")
        self.assertEqual(format_duration_zh(-(83 * 86400 + 3600)), "-83天1小时")
        self.assertEqual(format_hms_unbounded(-100), "-00:01:40")
        self.assertNotIn("时间异常", format_duration_zh(-100))

    def test_safe_export_never_none_or_zero_for_missing(self):
        self.assertEqual(safe_export_value(None, FieldStatus.API_MISSING), "GMGN 未提供")
        self.assertEqual(safe_export_value(None, FieldStatus.NOT_APPLICABLE, reason="不适用（转入）"), "不适用（转入）")
        self.assertNotEqual(safe_export_value(None, FieldStatus.API_MISSING, kind="usd"), 0)
        self.assertNotEqual(safe_export_value("", FieldStatus.KNOWN), "")

    def test_invisible_ticker_falls_back_to_mint(self):
        from app.utils.text import excel_cell, token_display_labels, visible_text

        self.assertEqual(visible_text("ㅤㅤ"), "")
        self.assertEqual(visible_text("  "), "")
        self.assertEqual(visible_text("未知"), "")
        symbol, name = token_display_labels("ㅤ", "ㅤㅤ", fallback="7X2A5U")
        self.assertEqual(symbol, "7X2A5U")
        self.assertEqual(name, "7X2A5U")
        symbol, name = token_display_labels("🔮", "1000x Oracle", fallback="zzzz")
        self.assertEqual(symbol, "🔮")
        self.assertEqual(name, "1000x Oracle")
        self.assertEqual(excel_cell("=HYPER"), "'=HYPER")
        self.assertEqual(excel_cell("-00:01:40"), "-00:01:40")
        self.assertEqual(excel_cell("'-00:09:45"), "-00:09:45")
        self.assertEqual(excel_cell("-35.918045918630881647100249"), "-35.918045918630881647100249")
        self.assertEqual(excel_cell("-$35.9180"), "-$35.9180")
        self.assertEqual(excel_cell("'-$53.8847"), "-$53.8847")
        self.assertEqual(excel_cell("ㅤ"), "未知")


class ValidatorTests(unittest.TestCase):
    def test_solana_address(self):
        sample = "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV"
        self.assertTrue(validate_solana_address(sample).valid)
        self.assertFalse(validate_solana_address("0xabc").valid)
        wallets, errors = parse_wallet_lines(sample + "\nbad\n" + sample)
        self.assertEqual(wallets, [sample])
        self.assertEqual(len(errors), 1)


if __name__ == "__main__":
    unittest.main()
