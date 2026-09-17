from __future__ import annotations

import json as json_mod
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from app.domain.enums import AcquisitionType, DataSource, HeliusCapStatus, ProviderHealth, ResolutionStatus
from app.providers.base import Clock, IndependentRateLimiter
from app.providers.dexscreener.client import DexScreenerProvider
from app.providers.exceptions import ProviderError, ProviderPlanError, ProviderRateLimitError
from app.providers.gmgn.adapter import GMGNVerifierProvider
from app.providers.helius.client import HeliusProvider
from app.providers.helius.credit_policy import credits_for
from app.providers.helius.credit_tracker import HeliusCreditTracker
from app.providers.helius.history import build_index
from app.providers.helius.models import BalanceChange, HistoryTx
from app.providers.helius.parsers import history_to_swaps, parse_history_page
from app.providers.moralis.client import MoralisProvider
from app.providers.orchestrator import DataOrchestrator
from app.providers.solana.rpc_client import SolanaRpcProvider
from app.resolvers.first_buy import resolve_first_buy, transfer_in_first_buy_fields
from app.resolvers.gas import resolve_gas
from app.providers.solana.transaction_parser import VerifiedTransaction


class FakeClock(Clock):
    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def time(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def _history_payload(items, cursor=None, more=False):
    return {"data": items, "pagination": {"hasMore": more, "nextCursor": cursor}}


def _hist_item(sig, ts, mint, amount, quote=-0.01, tx_type="SWAP"):
    return {
        "signature": sig,
        "timestamp": ts,
        "type": tx_type,
        "fee": 0.000005,
        "balanceChanges": [
            {"mint": mint, "amount": amount, "decimals": 6},
            {"mint": "SOL", "amount": quote, "decimals": 9},
        ],
    }


class HeliusHistoryTests(unittest.TestCase):
    def test_three_page_wallet_history_builds_index(self):
        session = MagicMock()
        pages = []

        def request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            before = (params or {}).get("before")
            pages.append(before)
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            if before is None:
                payload = _history_payload([_hist_item("s1", 300, "MintA", 1)], cursor="c2", more=True)
            elif before == "c2":
                payload = _history_payload([_hist_item("s2", 200, "MintB", 2)], cursor="c3", more=True)
            else:
                payload = _history_payload([_hist_item("s3", 100, "MintA", 3)], cursor=None, more=False)
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        session.request.side_effect = request
        helius = HeliusProvider("k", session=session)
        helius._shared_session = session
        helius.cap_flags["WALLET_HISTORY"] = True
        index = helius.collect_history("WalletX")
        self.assertEqual(index.pages, 3)
        self.assertEqual(len(index.transactions), 3)
        self.assertIn("MintA", index.token_events)
        self.assertIn("MintB", index.token_events)
        self.assertTrue(index.bottom_complete)

    def test_100_tokens_not_100_history_calls(self):
        session = MagicMock()
        calls = {"n": 0}

        def request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            calls["n"] += 1
            items = [_hist_item(f"s{i}", 1000 - i, f"Mint{i:03d}{'x'*28}", 1) for i in range(100)]
            payload = _history_payload(items, cursor=None, more=False)
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        session.request.side_effect = request
        helius = HeliusProvider("k", session=session)
        helius._shared_session = session
        helius.cap_flags["WALLET_HISTORY"] = True
        helius.probed = True
        helius.cap_flags["RPC"] = False
        rpc_session = MagicMock()

        def rpc_request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            payload = {"jsonrpc": "2.0", "result": {"value": []}}
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        rpc_session.request.side_effect = rpc_request
        rpc = SolanaRpcProvider(session=rpc_session)
        rpc._shared_session = rpc_session
        orch = DataOrchestrator([helius, rpc, MoralisProvider("", enabled_flag=False), DexScreenerProvider(), GMGNVerifierProvider(None)])
        index = orch.collect_wallet_swaps("WalletX")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(index.by_token), 100)
        self.assertGreaterEqual(orch.history_call_count, 1)


class HeliusCapabilityTests(unittest.TestCase):
    def test_wallet_api_plan_unavailable_falls_back(self):
        helius = HeliusProvider("k")
        helius.enabled = True
        helius.probed = True
        helius.cap_flags["WALLET_HISTORY"] = False
        helius.cap_status["WALLET_HISTORY"] = HeliusCapStatus.PLAN_UNAVAILABLE.value
        helius.ensure_probed = lambda repos=None, force=False: helius.cap_status
        rpc_session = MagicMock()

        def rpc_request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            body = json or {}
            m = body.get("method")
            if m == "getSignaturesForAddress":
                payload = {"jsonrpc": "2.0", "result": [{"signature": "sig1", "blockTime": 100}]}
            elif m == "getTransaction":
                payload = {"jsonrpc": "2.0", "result": None}
            elif m == "getTokenAccountsByOwner":
                payload = {"jsonrpc": "2.0", "result": {"value": []}}
            else:
                payload = {"jsonrpc": "2.0", "result": []}
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        rpc_session.request.side_effect = rpc_request
        rpc = SolanaRpcProvider(session=rpc_session)
        rpc._shared_session = rpc_session
        orch = DataOrchestrator([helius, rpc, MoralisProvider("", enabled_flag=False)])
        index = orch.collect_wallet_swaps("WalletX")
        self.assertIsNotNone(index)
        self.assertFalse(helius.cap_flags["WALLET_HISTORY"])

    def test_probe_gtfa_method_not_found_is_plan_unavailable(self):
        session = MagicMock()

        def request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            body = json or {}
            if body.get("method") == "getHealth":
                payload = {"jsonrpc": "2.0", "result": "ok"}
            elif body.get("method") == "getTransactionsForAddress":
                payload = {"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}}
            elif body.get("method") == "getAsset":
                payload = {"jsonrpc": "2.0", "result": {"id": "x"}}
            else:
                payload = {"jsonrpc": "2.0", "result": {}}
            if "wallet" in (url or "") and "history" in (url or ""):
                resp.status_code = 200
                payload = {"data": [], "pagination": {"hasMore": False}}
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        session.request.side_effect = request
        helius = HeliusProvider("k", session=session)
        helius._shared_session = session
        result = helius.probe_capabilities()
        self.assertEqual(result["RPC"], HeliusCapStatus.AVAILABLE.value)
        self.assertEqual(result["GTFA"], HeliusCapStatus.PLAN_UNAVAILABLE.value)


class FirstBuyAndTransferTests(unittest.TestCase):
    def test_rpc_block_time_wins(self):
        from app.providers.moralis.models import SwapLeg, WalletSwap

        buy = WalletSwap(
            transaction_hash="X",
            transaction_type="buy",
            block_timestamp=100,
            wallet_address="W",
            bought=SwapLeg(address="MintA", amount=Decimal("10"), usd_amount=Decimal("1")),
            sold=SwapLeg(address="So11111111111111111111111111111111111111112", symbol="SOL", amount=Decimal("0.01")),
            source=DataSource.HELIUS,
        )
        verified = VerifiedTransaction(
            signature="X",
            found=True,
            success=True,
            block_time=102,
            slot=1,
            fee_lamports=5000,
            fee_sol=Decimal("0.000005"),
            token_delta=Decimal("10"),
            wallet_sol_delta=Decimal("-0.01"),
        )
        fields = resolve_first_buy(buy, verified)
        self.assertEqual(fields["first_buy_time"].value, 102)
        self.assertEqual(fields["first_buy_time"].status, ResolutionStatus.VERIFIED)
        self.assertEqual(fields["first_buy_time"].source_values[DataSource.HELIUS.value], 100)

    def test_transfer_in_not_buy(self):
        fields = transfer_in_first_buy_fields()
        self.assertEqual(fields["acquisition_type"].value, AcquisitionType.TRANSFER_IN.value)
        self.assertEqual(fields["first_buy_time"].status, ResolutionStatus.NOT_APPLICABLE)
        self.assertIn("转入", fields["first_buy_time"].note or "")

    def test_fee_5000_lamports(self):
        verified = VerifiedTransaction(
            signature="X",
            found=True,
            success=True,
            block_time=1,
            fee_lamports=5000,
            fee_sol=Decimal("0.000005"),
        )
        field = resolve_gas(verified)
        self.assertEqual(field["gas_sol"].value, Decimal("0.000005"))


class CreditAndRateTests(unittest.TestCase):
    def test_credit_tracker_unknown_not_zero(self):
        tracker = HeliusCreditTracker()
        self.assertEqual(tracker.record("wallet_history"), 100)
        self.assertEqual(tracker.record("getTransaction"), 1)
        self.assertIsNone(tracker.record("mystery_method"))
        self.assertEqual(tracker.unpriced_requests, 1)
        self.assertEqual(tracker.estimated_credits, 101)
        self.assertIsNone(credits_for("not_a_real_method"))

    def test_target_rps_stays_near_8(self):
        clock = FakeClock()
        limiter = IndependentRateLimiter(rate=8, capacity=8, clock=clock, min_spacing=0.0)
        grants = 0
        for _ in range(24):
            limiter.acquire()
            grants += 1
        self.assertEqual(grants, 24)
        self.assertGreaterEqual(clock.t, 1.0)
        self.assertLessEqual(clock.t, 4.0)

    def test_429_respects_retry_after(self):
        clock = FakeClock()
        limiter = IndependentRateLimiter(rate=8, capacity=8, clock=clock)
        limiter.set_cooldown(2.5)
        limiter.acquire()
        self.assertGreaterEqual(clock.t, 2.5)


class DexBatchV5Tests(unittest.TestCase):
    def test_61_tokens_three_calls(self):
        session = MagicMock()
        calls = []

        def request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            calls.append(url)
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            resp.json.return_value = []
            resp.content = b"[]"
            return resp

        session.request.side_effect = request
        dex = DexScreenerProvider(session=session)
        dex._shared_session = session
        mints = [f"Mint{i:03d}{'x'*30}" for i in range(61)]
        dex.get_tokens_batch(mints)
        self.assertEqual(len(calls), 3)


class MoralisOptionalTests(unittest.TestCase):
    def test_moralis_disabled_without_key(self):
        p = MoralisProvider("", enabled_flag=False)
        self.assertFalse(p.enabled)
        self.assertIn(p.health, {ProviderHealth.DISABLED, ProviderHealth.NOT_CONFIGURED})
        rpc_session = MagicMock()

        def rpc_request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            payload = {"jsonrpc": "2.0", "result": []}
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        rpc_session.request.side_effect = rpc_request
        rpc = SolanaRpcProvider(session=rpc_session)
        rpc._shared_session = rpc_session
        orch = DataOrchestrator([p, HeliusProvider(""), rpc, DexScreenerProvider(), GMGNVerifierProvider(None)])
        index = orch.collect_wallet_swaps("WalletX")
        self.assertEqual(index.swaps, [])

    def test_provider_cooldown_isolated(self):
        gmgn = GMGNVerifierProvider(None)
        gmgn.enabled = True
        gmgn.health = ProviderHealth.RATE_LIMITED
        gmgn.limiter.set_cooldown(60)
        helius = HeliusProvider("k")
        helius.enabled = True
        helius.probed = True
        helius.cap_flags["WALLET_HISTORY"] = True
        helius.collect_history = lambda *a, **k: build_index("W", [], pages=1, bottom_complete=True)
        orch = DataOrchestrator([helius, gmgn, DexScreenerProvider()])
        index = orch.collect_wallet_swaps("W")
        self.assertEqual(index.pages, 1)
        self.assertGreater(gmgn.limiter.cooldown_until, 0)
        self.assertEqual(helius.limiter.cooldown_until, 0)

    def test_sol_quote_gets_estimated_usd_and_gas(self):
        from decimal import Decimal

        from app.providers.helius.models import BalanceChange, HistoryTx
        from app.providers.helius.parsers import history_to_swaps
        from app.providers.moralis.convert import swap_to_trade
        from app.providers.solana.rpc_client import TX_READ_OPTIONS

        tx = HistoryTx(
            signature="sigBuy",
            timestamp=1,
            fee_sol=Decimal("0.000005"),
            balance_changes=[
                BalanceChange(mint="MintAAAA", amount=Decimal("100")),
                BalanceChange(mint="SOL", amount=Decimal("-0.5")),
            ],
        )
        swaps = history_to_swaps("WalletX", [tx], sol_usd=Decimal("150"))
        self.assertEqual(len(swaps), 1)
        self.assertEqual(swaps[0].total_value_usd, Decimal("75"))
        trade = swap_to_trade(swaps[0])
        self.assertEqual(trade.cost_usd, Decimal("75"))
        self.assertTrue(trade.cost_usd_estimated)
        self.assertEqual(trade.gas_sol, Decimal("0.000005"))
        self.assertEqual(trade.gas_usd, Decimal("0.000005") * Decimal("150"))
        self.assertEqual(TX_READ_OPTIONS["maxSupportedTransactionVersion"], 1)
        from app.services.completeness_service import CompletenessService

        row = CompletenessService().trade_export_row(trade, "Raydium")
        self.assertIn("$75", str(row["USD金额"]))
        self.assertIn("估", str(row["USD金额"]))
        self.assertNotIn("无法验证", str(row["USD金额"]))
        self.assertNotIn("GMGN 未提供", str(row["Gas USD"]))

    def test_helius_history_preferred_over_rpc(self):
        session = MagicMock()
        calls = {"rpc": 0, "helius": 0}

        def helius_request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            calls["helius"] += 1
            items = [_hist_item("s1", 1000, "MintA" + "x" * 28, 1)]
            payload = _history_payload(items, cursor=None, more=False)
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        session.request.side_effect = helius_request
        helius = HeliusProvider("k", session=session)
        helius._shared_session = session
        helius.cap_flags["WALLET_HISTORY"] = True
        helius.probed = True
        rpc_session = MagicMock()

        def rpc_request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            calls["rpc"] += 1
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            payload = {"jsonrpc": "2.0", "result": [{"signature": "should-not-use", "blockTime": 1}]}
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        rpc_session.request.side_effect = rpc_request
        rpc = SolanaRpcProvider(session=rpc_session)
        rpc._shared_session = rpc_session
        orch = DataOrchestrator([helius, rpc, MoralisProvider("", enabled_flag=False)])
        index = orch.collect_wallet_swaps("WalletX")
        self.assertGreaterEqual(calls["helius"], 1)
        self.assertEqual(calls["rpc"], 0)
        self.assertEqual(index.provider, "helius")

    def test_uuid_keys_are_moved_off_moralis(self):
        from app.config import _rehome_helius_keys

        moralis, helius = _rehome_helius_keys(
            ["aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", "eyJhbGciOi.jwt"],
            [],
        )
        self.assertEqual(moralis, ["eyJhbGciOi.jwt"])
        self.assertEqual(helius, ["aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"])

    def test_from_config_runs_without_moralis(self):
        from types import SimpleNamespace

        cfg = SimpleNamespace(
            enable_moralis=False,
            moralis_api_keys=[],
            moralis_api_key="",
            moralis_base="https://solana-gateway.moralis.io",
            solana_rpc_url="https://api.mainnet-beta.solana.com",
            helius_api_key="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            helius_api_keys=[
                "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                "11111111-2222-4333-8444-555555555555",
            ],
            helius_rpc_url="",
            helius_target_rps=8,
            helius_monthly_credit_budget=1_000_000,
            enable_gmgn=True,
            enable_gmgn_deep_history_fallback=False,
            verification_mode="BALANCED",
        )
        orch = DataOrchestrator.from_config(cfg, None, None)
        self.assertFalse(orch.provider("moralis").enabled)
        helius = orch.provider("helius")
        self.assertTrue(helius.enabled)
        self.assertEqual(len(helius.api_keys), 2)
        self.assertIn("helius-rpc.com", orch.provider("solana_rpc").rpc_url)


class Gmgn429WithHeliusTests(unittest.TestCase):
    def test_gmgn_429_helius_ok(self):
        from app.api.exceptions import GMGNRateLimitError
        from app.domain.enums import ReportPeriod, TaskStatus
        from app.domain.models import AnalysisOptions, WalletAnalysisRequest
        from app.services.wallet_analysis_service import WalletAnalysisService
        from app.storage.database import Database
        import os
        import tempfile
        from pathlib import Path

        class DummyGMGN:
            api_key = "k"
            request_count = 0
            retry_429_count = 0
            error_count = 0
            on_raw = None

            def get_wallet_stats(self, *args, **kwargs):
                raise GMGNRateLimitError("GMGN 429")

            def get_wallet_profits(self, *args, **kwargs):
                raise GMGNRateLimitError("GMGN 429")

            def get_token_info(self, *args, **kwargs):
                raise GMGNRateLimitError("GMGN 429")

            def get_token_pool_info(self, *args, **kwargs):
                raise GMGNRateLimitError("GMGN 429")

            def get_wallet_activity(self, *args, **kwargs):
                raise GMGNRateLimitError("GMGN 429")

        helius = HeliusProvider("k")
        helius.enabled = True
        helius.probed = True
        helius.cap_flags["WALLET_HISTORY"] = True
        helius.cap_flags["DAS"] = False
        tx = HistoryTx(
            signature="BuySig",
            timestamp=100,
            fee_sol=Decimal("0.000005"),
            tx_type="SWAP",
            balance_changes=[
                BalanceChange(mint="MintAAA", amount=Decimal("1"), decimals=6),
                BalanceChange(mint="SOL", amount=Decimal("-0.01"), decimals=9),
            ],
        )
        helius.collect_history = lambda *a, **k: build_index("7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV", [tx], pages=1, bottom_complete=True)

        def verify(wallet, mint, signature):
            return VerifiedTransaction(
                signature=signature,
                found=True,
                success=True,
                block_time=102,
                fee_lamports=5000,
                fee_sol=Decimal("0.000005"),
                token_delta=Decimal("1"),
                wallet_sol_delta=Decimal("-0.01"),
            )

        dex_session = MagicMock()

        def dex_request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            payload = [
                {
                    "chainId": "solana",
                    "dexId": "raydium",
                    "pairAddress": "pool1",
                    "baseToken": {"address": "MintAAA", "symbol": "AAA"},
                    "quoteToken": {"address": "So11111111111111111111111111111111111111112", "symbol": "SOL"},
                    "priceUsd": "1",
                    "liquidity": {"usd": 1000},
                    "fdv": 1100,
                    "marketCap": 1000,
                    "pairCreatedAt": 200000,
                }
            ]
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        dex_session.request.side_effect = dex_request
        dex = DexScreenerProvider(session=dex_session)
        dex._shared_session = dex_session
        rpc_session = MagicMock()

        def rpc_request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            payload = {"jsonrpc": "2.0", "result": {"value": []}}
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        rpc_session.request.side_effect = rpc_request
        rpc = SolanaRpcProvider(session=rpc_session)
        rpc._shared_session = rpc_session
        orch = DataOrchestrator(
            [
                MoralisProvider("", enabled_flag=False),
                rpc,
                helius,
                dex,
                GMGNVerifierProvider(DummyGMGN(), deep_history=False),
            ]
        )
        orch.verify_tx = verify
        fd, name = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        svc = WalletAnalysisService(DummyGMGN(), db=Database(path=Path(name)), orchestrator=orch, deep_gmgn_history=False)
        req = WalletAnalysisRequest(
            wallet_address="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
            period=ReportPeriod.D7,
            start_time=1,
            end_time=2_000_000_000,
            options=AnalysisOptions(save_raw_json=False),
        )
        report = svc.analyze(req)
        self.assertIn(report.status, {TaskStatus.SUCCESS, TaskStatus.PARTIAL, TaskStatus.WARNING})
        self.assertTrue(report.excel_path.endswith(".xlsx"))
        self.assertEqual(len(report.tokens), 1)
        self.assertEqual(report.tokens[0].first_buy_time.value, 102)
        token = report.tokens[0]
        self.assertIsNotNone(token.buy_total_usd)
        self.assertIsNotNone(token.first_buy_display.value)
        self.assertNotIn("无法验证", str(token.first_buy_display.export("usd")))
        trades = [t for t in report.trades if t.token_address == "MintAAA"]
        self.assertTrue(trades)
        self.assertTrue(any(t.cost_usd is not None for t in trades))
        self.assertTrue(any(t.token_symbol and t.token_symbol != "未知" for t in trades))


if __name__ == "__main__":
    unittest.main()
