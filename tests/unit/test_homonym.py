from __future__ import annotations

import unittest
from decimal import Decimal

from app.domain.enums import EventType
from app.domain.models import TradeRecord
from app.services.pnl_service import apply_fifo


def t(token: str, symbol: str, ts: int, event: EventType, amount: str, cost: str) -> TradeRecord:
    return TradeRecord("W", "sol", token, symbol, symbol, f"{token}-{ts}", ts, event, Decimal(amount), Decimal("1"), Decimal(cost), None, None, None, None, {})


class HomonymTests(unittest.TestCase):
    def test_same_symbol_different_mints_are_isolated(self):
        a = "MintZEC_A"
        b = "MintZEC_B"
        trades_a = [t(a, "ZEC", 1, EventType.BUY, "10", "10"), t(a, "ZEC", 2, EventType.SELL, "10", "20")]
        trades_b = [t(b, "ZEC", 1, EventType.BUY, "10", "100"), t(b, "ZEC", 2, EventType.SELL, "10", "90")]
        fa = apply_fifo(trades_a)
        fb = apply_fifo(trades_b)
        self.assertEqual(fa.realized_profit, Decimal("10"))
        self.assertEqual(fb.realized_profit, Decimal("-10"))
        keyed = {}
        keyed[a] = fa
        keyed[b] = fb
        self.assertNotEqual(keyed[a].realized_profit, keyed[b].realized_profit)
        self.assertNotIn("ZEC", keyed)


if __name__ == "__main__":
    unittest.main()
