from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from app.domain.enums import AcquisitionType, EventType
from app.domain.models import TradeRecord
from app.services.acquisition_resolver import first_buy_in_range, resolve_acquisition


def trade(ts: int, event: EventType, token: str = "TokenAAA", symbol: str = "AAA", amount="10", cost="20") -> TradeRecord:
    return TradeRecord(
        wallet_address="Wallet1",
        chain="sol",
        token_address=token,
        token_symbol=symbol,
        token_name=symbol,
        tx_hash=f"{event.value}-{ts}",
        timestamp=ts,
        event_type=event,
        token_amount=Decimal(amount),
        price_usd=Decimal("2"),
        cost_usd=Decimal(cost),
        cost_sol=None,
        gas_usd=Decimal("0.01"),
        gas_sol=None,
        launchpad_platform=None,
        raw={},
    )


class FirstBuyTests(unittest.TestCase):
    def test_first_buy_uses_full_history_not_report_window(self):
        aug1 = int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp())
        sep5 = int(datetime(2026, 9, 5, tzinfo=timezone.utc).timestamp())
        sep10 = int(datetime(2026, 9, 10, tzinfo=timezone.utc).timestamp())
        start = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp())
        end = int(datetime(2026, 9, 17, tzinfo=timezone.utc).timestamp())
        trades = [
            trade(sep10, EventType.SELL, amount="5", cost="15"),
            trade(sep5, EventType.BUY, amount="5", cost="10"),
            trade(aug1, EventType.BUY, amount="10", cost="8"),
        ]
        acq = resolve_acquisition(trades)
        in_range = first_buy_in_range(trades, start, end)
        self.assertEqual(acq.acquisition_type, AcquisitionType.BUY)
        self.assertEqual(acq.timestamp, aug1)
        self.assertEqual(in_range.timestamp, sep5)
        self.assertNotEqual(acq.timestamp, in_range.timestamp)


if __name__ == "__main__":
    unittest.main()
