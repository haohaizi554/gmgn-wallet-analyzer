from __future__ import annotations

import unittest
from decimal import Decimal

from app.domain.enums import AcquisitionStatus, AcquisitionType, EventType, FieldStatus, TaskStatus
from app.domain.models import AcquisitionInfo, AuditedValue, TokenAnalysisResult, TradeRecord, known
from app.services.completeness_service import CompletenessService, assert_no_empty_export_cells


class EmptyExportTests(unittest.TestCase):
    def test_token_and_trade_rows_have_no_empty_cells(self):
        acq = AcquisitionInfo(
            acquisition_type=AcquisitionType.TRANSFER_IN,
            timestamp=100,
            price_usd=None,
            amount=Decimal("1"),
            cost_usd=None,
            cost_sol=None,
            gas_usd=None,
            gas_sol=None,
            market_cap=None,
            status=AcquisitionStatus.NO_BUY_HISTORY,
            reason="未发现 Buy，存在 TransferIn",
            source="wallet_activity",
        )
        token = TokenAnalysisResult(
            wallet_address="Wallet",
            token_address="Mint",
            chain="sol",
            symbol="ZZ",
            name="ZZ",
            source_platform=known("Raydium", "token_info.pool.exchange"),
            acquisition=acq,
            created_at=known(50, "token_info.creation_timestamp"),
            open_at=AuditedValue(None, "token_info.open_timestamp", FieldStatus.API_MISSING, reason="GMGN 未提供"),
            pool_created_at=AuditedValue(None, "pool", FieldStatus.API_MISSING, reason="GMGN 未提供"),
            time_diff_seconds=known(50, "calc"),
            buy_count=0,
            buy_total_usd=None,
            sell_count=1,
            sell_total_usd=Decimal("10"),
            realized_profit=AuditedValue(None, "fifo", FieldStatus.NOT_APPLICABLE, reason="无法验证历史成本"),
            unrealized_profit=AuditedValue(None, "holdings", FieldStatus.API_MISSING, reason="未使用 holdings"),
            total_profit=AuditedValue(None, "profits", FieldStatus.API_MISSING, reason="无单 Token 拆分"),
            total_profit_pnl=AuditedValue(None, "profits", FieldStatus.API_MISSING, reason="无单 Token 拆分"),
            fifo_realized_profit=AuditedValue(None, "fifo", FieldStatus.NOT_APPLICABLE, reason="无法验证历史成本"),
            current_balance=Decimal("0"),
            holding_duration_seconds=known(20, "calc"),
            missing_cost_count=1,
            status=TaskStatus.WARNING,
            first_buy_display=AuditedValue(None, "activity", FieldStatus.NOT_APPLICABLE, reason="不适用（转入获得）"),
            first_buy_amount=known(Decimal("1"), "activity"),
            first_buy_time=known(100, "activity"),
            market_cap=AuditedValue(None, "activity", FieldStatus.NOT_APPLICABLE, reason="无可验证历史市值"),
        )
        svc = CompletenessService()
        svc.apply_time_fields(token, last_sell_ts=120)
        row = svc.token_export_row(token)
        trade = TradeRecord("Wallet", "sol", "Mint", "ZZ", "ZZ", "hash", 120, EventType.SELL, Decimal("1"), Decimal("10"), Decimal("10"), None, None, None, None, {}, single_pnl_display="无法验证历史成本")
        trow = svc.trade_export_row(trade, "Raydium")
        assert_no_empty_export_cells([row, trow])
        self.assertEqual(row["首笔买入"], "不适用（转入获得）")
        self.assertNotIn(None, row.values())
        self.assertNotIn("", row.values())

    def test_zero_sells_export_zero_not_unresolved(self):
        acq = AcquisitionInfo(
            acquisition_type=AcquisitionType.BUY,
            timestamp=100,
            price_usd=Decimal("1"),
            amount=Decimal("1"),
            cost_usd=Decimal("10"),
            cost_sol=None,
            gas_usd=None,
            gas_sol=None,
            market_cap=Decimal("1000"),
            status=AcquisitionStatus.INFERRED,
            reason="",
            source="wallet_activity",
        )
        token = TokenAnalysisResult(
            wallet_address="Wallet",
            token_address="Mint",
            chain="sol",
            symbol="AA",
            name="AA",
            source_platform=known("Pump.fun", "dex"),
            acquisition=acq,
            created_at=known(50, "token_info.creation_timestamp"),
            open_at=known(50, "dexscreener.pairCreatedAt", estimated=True),
            pool_created_at=known(50, "dexscreener.pairCreatedAt"),
            time_diff_seconds=known(50, "calc"),
            buy_count=1,
            buy_total_usd=Decimal("10"),
            sell_count=0,
            sell_total_usd=Decimal("0"),
            realized_profit=known(Decimal("0"), "local_fifo", reason="无已实现卖出"),
            unrealized_profit=known(Decimal("5"), "local_fifo", estimated=True),
            total_profit=known(Decimal("5"), "local_fifo", estimated=True),
            total_profit_pnl=known(Decimal("0.5"), "local_fifo", estimated=True),
            fifo_realized_profit=known(Decimal("0"), "local_fifo"),
            current_balance=Decimal("1"),
            holding_duration_seconds=known(20, "calc"),
            missing_cost_count=0,
            status=TaskStatus.SUCCESS,
            first_buy_display=known(Decimal("10"), "activity"),
            first_buy_amount=known(Decimal("1"), "activity"),
            first_buy_time=known(100, "activity"),
            market_cap=known(Decimal("1000"), "activity", estimated=True),
        )
        row = CompletenessService().token_export_row(token)
        self.assertEqual(row["卖出总额"], "$0.0000")
        self.assertEqual(row["已实现盈亏"], "$0.0000")
        self.assertNotIn("GMGN 利润接口", row["已实现盈亏"])
        self.assertNotIn("无法验证卖出总额", row["卖出总额"])
        self.assertNotEqual(row["开盘时间"], "GMGN 未提供")


if __name__ == "__main__":
    unittest.main()
