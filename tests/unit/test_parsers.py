from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.api.parsers import parse_activity_page, parse_event_type, parse_token_info
from app.domain.enums import EventType
from app.services.activity_collector import ActivityCollector


class ParserTests(unittest.TestCase):
    def test_activity_fixture_and_event_alias(self):
        path = Path(__file__).resolve().parents[1] / "fixtures" / "activity_page.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        trades, nxt = parse_activity_page(payload, "Wallet", "sol")
        self.assertIsNone(nxt)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].token_address, "TokenAAA")
        self.assertEqual(trades[0].event_type, EventType.SELL)
        self.assertEqual(parse_event_type("buy"), EventType.BUY)
        self.assertEqual(parse_event_type("transferIn"), EventType.TRANSFER_IN)

    def test_token_info_keeps_created_and_open_separate(self):
        info = parse_token_info(
            {
                "address": "Mint",
                "symbol": "AAA",
                "creation_timestamp": 10,
                "open_timestamp": 20,
                "pool": {"exchange": "pump_amm", "creation_timestamp": 30},
            },
            "Mint",
        )
        self.assertEqual(info.creation_timestamp, 10)
        self.assertEqual(info.open_timestamp, 20)
        self.assertEqual(info.pool_created_at, 30)
        self.assertEqual(info.pool_exchange, "pump_amm")


class CollectorCursorTests(unittest.TestCase):
    def test_token_history_follows_cursor_until_null(self):
        pages = {
            None: {"activities": [{"event_type": "buy", "tx_hash": "t1", "timestamp": 300, "token": {"address": "M", "symbol": "S"}, "token_amount": "1", "cost_usd": "1"}], "next": "c1"},
            "c1": {"activities": [{"event_type": "buy", "tx_hash": "t0", "timestamp": 100, "token": {"address": "M", "symbol": "S"}, "token_amount": "2", "cost_usd": "2"}], "next": None},
        }

        class FakeClient:
            def __init__(self):
                self.calls = []

            def get_wallet_activity(self, chain, wallet, token_address=None, cursor=None, limit=50, types=None):
                self.calls.append(cursor)
                return pages[cursor]

        client = FakeClient()
        collector = ActivityCollector(client)  # type: ignore
        trades, page_count, complete = collector.collect_token_history("sol", "W", "M", use_cache=False)
        self.assertEqual(page_count, 2)
        self.assertTrue(complete)
        self.assertEqual({t.tx_hash for t in trades}, {"t1", "t0"})
        self.assertEqual(min(t.timestamp for t in trades if t.event_type.value == "buy"), 100)


if __name__ == "__main__":
    unittest.main()
