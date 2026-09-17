from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

from app.domain.enums import CircuitState, DataSource, FieldStatus, ResolutionStatus
from app.providers.base import Clock, ProviderCircuitBreaker
from app.providers.dexscreener.client import DexScreenerProvider
from app.providers.moralis.client import MoralisProvider
from app.providers.moralis.parsers import parse_metadata_batch, parse_swaps_page, parse_wallet_swap
from app.providers.solana.transaction_parser import parse_verified_transaction
from app.resolvers.creation import resolve_creation_times
from app.resolvers.first_buy import resolve_first_buy, transfer_in_first_buy_fields
from app.resolvers.gas import resolve_gas
from app.resolvers.historical_mcap import resolve_entry_market_cap
from app.resolvers.market import resolve_numeric_consensus
from app.services.completeness_service import CompletenessService, assert_no_empty_export_cells

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "providers"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeClock(Clock):
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def time(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


class ParserFixtureTests(unittest.TestCase):
    def test_moralis_swaps_solana_shape(self):
        payload = _load("moralis_wallet_swaps.json")
        swaps, cursor = parse_swaps_page(payload, "wallet")
        self.assertEqual(len(swaps), 2)
        self.assertEqual(cursor, "cursor-page-2")
        self.assertTrue(swaps[0].transaction_hash.startswith("5"))
        self.assertFalse(swaps[0].bought.address.startswith("0x"))
        self.assertEqual(swaps[0].transaction_type, "buy")

    def test_metadata_batch_fields(self):
        items = parse_metadata_batch(_load("moralis_metadata_batch.json"))
        by_mint = {i.mint: i for i in items}
        self.assertIn("MintAAA1111111111111111111111111111111111111", by_mint)
        self.assertEqual(by_mint["MintAAA1111111111111111111111111111111111111"].market_cap, Decimal("1000000"))
        self.assertEqual(by_mint["MintAAA1111111111111111111111111111111111111"].fully_diluted_value, Decimal("1000000"))

    def test_rpc_gas_and_token_delta(self):
        raw = _load("solana_get_transaction.json")
        verified = parse_verified_transaction(raw, "9P9aAh3kdMK651Cc111111111111111111111111111", "MintAAA1111111111111111111111111111111111111")
        self.assertTrue(verified.found)
        self.assertEqual(verified.fee_lamports, 5000)
        self.assertEqual(verified.fee_sol, Decimal("0.000005"))
        self.assertEqual(verified.block_time, 102)
        self.assertEqual(verified.token_delta, Decimal("1000"))


class MoralisClientTests(unittest.TestCase):
    def test_cursor_three_pages_and_earliest_buy(self):
        session = MagicMock()
        pages = []

        def request(method, url, params=None, json=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            resp.content = b"{}"
            q = params or {}
            if "metadata" in url:
                resp.json.return_value = []
                resp.content = b"[]"
                return resp
            cursor = q.get("cursor")
            order = q.get("order")
            if q.get("tokenAddress") and order == "ASC":
                payload = {
                    "page": 1,
                    "pageSize": 1,
                    "cursor": None,
                    "result": [
                        {
                            "transactionHash": "earliest",
                            "transactionType": "buy",
                            "blockTimestamp": "2026-01-01T00:00:00.000Z",
                            "walletAddress": "W",
                            "bought": {"address": "MintA", "amount": "1", "usdAmount": 1},
                            "sold": {"address": "So11111111111111111111111111111111111111112", "amount": "0.01"},
                            "totalValueUsd": 1,
                        }
                    ],
                }
            elif cursor is None:
                payload = {"page": 1, "pageSize": 1, "cursor": "c2", "result": [{"transactionHash": "p1", "transactionType": "buy", "blockTimestamp": "2026-09-01T00:00:00.000Z", "bought": {"address": "MintA"}, "sold": {}}]}
            elif cursor == "c2":
                payload = {"page": 2, "pageSize": 1, "cursor": "c3", "result": [{"transactionHash": "p2", "transactionType": "sell", "blockTimestamp": "2026-08-01T00:00:00.000Z", "bought": {}, "sold": {"address": "MintA"}}]}
            else:
                payload = {"page": 3, "pageSize": 1, "cursor": None, "result": [{"transactionHash": "p3", "transactionType": "buy", "blockTimestamp": "2026-07-01T00:00:00.000Z", "bought": {"address": "MintA"}, "sold": {}}]}
            pages.append(cursor)
            resp.json.return_value = payload
            resp.content = __import__("json").dumps(payload).encode()
            return resp

        session.request.side_effect = request
        client = MoralisProvider("test-key", session=session)
        client._shared_session = session
        swaps, n, complete = client.iter_wallet_swaps("WalletX", limit=1)
        self.assertTrue(complete)
        self.assertEqual(n, 3)
        self.assertEqual([s.transaction_hash for s in swaps], ["p1", "p2", "p3"])
        earliest = client.earliest_buy("WalletX", "MintA")
        self.assertEqual(earliest.transaction_hash, "earliest")

    def test_metadata_batch_265_is_three_calls(self):
        session = MagicMock()
        calls = []

        def request(method, url, params=None, json=None, headers=None, timeout=None):
            calls.append(json["addresses"] if json else [])
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            payload = [{"mint": m, "standard": "metaplex", "name": "T", "symbol": "T", "decimals": "6", "totalSupply": "1", "totalSupplyFormatted": "1", "fullyDilutedValue": "1", "marketCap": "1", "circulatingSupply": "1", "metaplex": {}, "links": {}, "description": "", "isVerifiedContract": False, "possibleSpam": False, "logo": None, "tokenStandard": 1} for m in json["addresses"]]
            resp.json.return_value = payload
            resp.content = b"[]"
            return resp

        session.request.side_effect = request
        client = MoralisProvider("k", session=session)
        client._shared_session = session
        mints = [f"Mint{i:03d}{'x'*30}" for i in range(265)]
        items = client.get_metadata_batch(mints)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(calls[0]), 100)
        self.assertEqual(len(calls[1]), 100)
        self.assertEqual(len(calls[2]), 65)
        self.assertEqual(len(items), 265)


class DexBatchTests(unittest.TestCase):
    def test_61_tokens_three_calls(self):
        session = MagicMock()
        calls = []

        def request(method, url, params=None, json=None, headers=None, timeout=None):
            calls.append(url)
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            resp.json.return_value = []
            resp.content = b"[]"
            return resp

        session.request.side_effect = request
        client = DexScreenerProvider(session=session)
        client._shared_session = session
        mints = [f"Mint{i:02d}{'y'*32}" for i in range(61)]
        client.get_tokens_batch(mints)
        self.assertEqual(len(calls), 3)


class CrossValidationTests(unittest.TestCase):
    def test_consensus_two_percent(self):
        field = resolve_numeric_consensus(
            "market_cap",
            {DataSource.MORALIS: 1_000_000, DataSource.DEXSCREENER: 1_020_000},
        )
        self.assertEqual(field.status, ResolutionStatus.CONSENSUS)
        self.assertIn("2.0%", field.note or "")

    def test_conflict_double(self):
        field = resolve_numeric_consensus(
            "market_cap",
            {DataSource.MORALIS: 1_000_000, DataSource.DEXSCREENER: 2_000_000},
        )
        self.assertEqual(field.status, ResolutionStatus.CONFLICT)

    def test_pool_created_not_overwriting_mint(self):
        fields = resolve_creation_times(mint_created_at=100, pool_created_at=200)
        self.assertEqual(fields["token_created_at"].value, 100)
        self.assertEqual(fields["pool_created_at"].value, 200)

    def test_entry_mc_derived_vs_estimated(self):
        derived = resolve_entry_market_cap(Decimal("0.01"), Decimal("100000000"), None)
        self.assertEqual(derived.status, ResolutionStatus.DERIVED)
        self.assertEqual(derived.value, Decimal("1000000"))
        estimated = resolve_entry_market_cap(Decimal("0.01"), None, Decimal("100000000"))
        self.assertEqual(estimated.status, ResolutionStatus.ESTIMATED)
        self.assertIn("当前供应量", estimated.note or "")

    def test_rpc_overrides_moralis_timestamp(self):
        from app.providers.moralis.models import SwapLeg, WalletSwap
        from app.providers.solana.transaction_parser import VerifiedTransaction

        buy = WalletSwap(
            transaction_hash="ABC",
            transaction_type="buy",
            block_timestamp=100,
            wallet_address="W",
            bought=SwapLeg(address="M", amount=Decimal("1"), usd_amount=Decimal("10")),
        )
        verified = VerifiedTransaction(signature="ABC", block_time=102, found=True, success=True, token_delta=Decimal("1"), fee_sol=Decimal("0.000005"))
        fields = resolve_first_buy(buy, verified)
        self.assertEqual(fields["first_buy_time"].value, 102)
        self.assertEqual(fields["first_buy_time"].primary_source, DataSource.SOLANA_RPC)
        self.assertEqual(fields["first_buy_time"].status, ResolutionStatus.VERIFIED)
        self.assertEqual(fields["first_buy_time"].source_values["MORALIS"], 100)

    def test_transfer_in_not_buy(self):
        fields = transfer_in_first_buy_fields()
        self.assertEqual(fields["first_buy_usd"].status, ResolutionStatus.NOT_APPLICABLE)
        self.assertEqual(fields["first_buy_usd"].note, "不适用（转入获得）")
        self.assertEqual(fields["acquisition_type"].value, "TRANSFER_IN")

    def test_gas_from_lamports(self):
        raw = _load("solana_get_transaction.json")
        verified = parse_verified_transaction(raw, "9P9aAh3kdMK651Cc111111111111111111111111111", "MintAAA1111111111111111111111111111111111111")
        fields = resolve_gas(verified)
        self.assertEqual(fields["gas_sol"].value, Decimal("0.000005"))
        self.assertEqual(fields["gas_usd"].status, ResolutionStatus.UNRESOLVED)


class CircuitBreakerTests(unittest.TestCase):
    def test_three_429_open_then_half_open_probe(self):
        clock = FakeClock()
        br = ProviderCircuitBreaker(failure_threshold=3, open_seconds=60, clock=clock)
        self.assertTrue(br.allow())
        br.record_failure(429)
        br.record_failure(429)
        self.assertEqual(br.record_failure(429), CircuitState.OPEN)
        self.assertFalse(br.allow())
        clock.t += 60
        self.assertTrue(br.allow())
        self.assertEqual(br.state, CircuitState.HALF_OPEN)
        self.assertFalse(br.allow())
        br.record_success()
        self.assertEqual(br.state, CircuitState.CLOSED)


class CompletenessZeroFakeTests(unittest.TestCase):
    def test_unresolved_not_replaced_by_zero(self):
        from app.domain.models import AuditedValue

        exported = AuditedValue(None, "moralis", FieldStatus.UNRESOLVED, reason="无法验证历史美元成本").export("usd")
        self.assertNotEqual(exported, 0)
        self.assertNotEqual(exported, "0")
        self.assertIn("无法验证", str(exported))
        assert_no_empty_export_cells([{"字段": exported}])


if __name__ == "__main__":
    unittest.main()
