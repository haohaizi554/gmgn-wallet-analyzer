from __future__ import annotations

import unittest
from decimal import Decimal

from app.domain.enums import AcquisitionType, EventType
from app.domain.models import TradeRecord
from app.services.acquisition_resolver import resolve_acquisition


class TransferTests(unittest.TestCase):
    def test_transfer_in_is_not_fake_buy(self):
        trades = [
            TradeRecord("W", "sol", "cbBTC", "cbBTC", "cbBTC", "in1", 100, EventType.TRANSFER_IN, Decimal("1"), Decimal("60000"), None, None, None, None, None, {}),
            TradeRecord("W", "sol", "cbBTC", "cbBTC", "cbBTC", "s1", 200, EventType.SELL, Decimal("0.2"), Decimal("61000"), Decimal("12200"), None, None, None, None, {}),
        ]
        acq = resolve_acquisition(trades)
        self.assertNotEqual(acq.acquisition_type, AcquisitionType.BUY)
        self.assertIn(acq.acquisition_type, (AcquisitionType.TRANSFER_IN, AcquisitionType.BRIDGE))
        self.assertEqual(acq.timestamp, 100)
        self.assertIn("TransferIn", acq.reason)


if __name__ == "__main__":
    unittest.main()
