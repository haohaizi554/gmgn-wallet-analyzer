from __future__ import annotations

import threading
import time
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from app.api.credential_pool import CredentialPool, CredentialState
from app.api.exceptions import AnalysisCancelledError
from app.api.gmgn_client import GMGNClient
from app.api.parsers import parse_activity_item, parse_activity_page
from app.api.rate_limiter import Clock, WeightedRateLimiter
from app.api.singleflight import SingleFlight
from app.domain.enums import EventType
from app.domain.fingerprint import activity_fingerprint
from app.domain.models import TradeRecord
from app.jobs.event_bus import AnalysisEventBus
from app.services.activity_collector import ActivityCollector
from app.services.pnl_service import apply_fifo
from app.storage.database import Database


class FakeClock(Clock):
    def __init__(self) -> None:
        self.mono = 0.0
        self.unix = 1_000_000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.mono

    def time(self) -> float:
        return self.unix

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.mono += seconds
        self.unix += seconds


def _trade(amount: str, cost: str, ts: int = 1, tx: str = "abc") -> dict:
    return {
        "event_type": "buy",
        "tx_hash": tx,
        "timestamp": ts,
        "token_amount": amount,
        "cost_usd": cost,
        "price_usd": "1",
        "token": {"address": "TOKENA", "symbol": "A"},
    }


class FingerprintTests(unittest.TestCase):
    def test_same_tx_hash_different_amount_kept(self):
        a = parse_activity_item(_trade("100", "100"), "W", "sol")
        b = parse_activity_item(_trade("50", "50"), "W", "sol")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual(a.tx_hash, b.tx_hash)
        self.assertEqual(a.token_address, b.token_address)
        self.assertEqual(a.event_type, b.event_type)
        self.assertNotEqual(a.activity_fingerprint, b.activity_fingerprint)
        self.assertNotEqual(activity_fingerprint("sol", "W", _trade("100", "100")), activity_fingerprint("sol", "W", _trade("50", "50")))

    def test_database_keeps_both_rows(self):
        import os
        import tempfile
        from pathlib import Path

        fd, name = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db = Database(path=Path(name))
        from app.storage.repositories import Repositories

        repos = Repositories(db)
        a = parse_activity_item(_trade("100", "100"), "W", "sol")
        b = parse_activity_item(_trade("50", "50"), "W", "sol")
        repos.upsert_trade("W", "sol", "TOKENA", "buy", "abc", 1, a.raw, a.activity_fingerprint)
        repos.upsert_trade("W", "sol", "TOKENA", "buy", "abc", 1, b.raw, b.activity_fingerprint)
        rows = repos.list_token_trades("W", "TOKENA")
        self.assertEqual(len(rows), 2)


class FifoMissingOnceTests(unittest.TestCase):
    def test_one_sell_counts_once(self):
        def t(ts, event, amount, cost):
            return TradeRecord(
                "W", "sol", "M", "S", "S", f"{event.value}{ts}", ts, event,
                Decimal(amount), Decimal("1"), Decimal(cost) if cost is not None else None,
                None, None, None, None, {},
            )

        trades = [
            t(1, EventType.BUY, "10", "10"),
            t(3, EventType.SELL, "20", "30"),
        ]
        result = apply_fifo(trades)
        self.assertEqual(result.missing_cost_count, 1)
        self.assertEqual(result.missing_cost_sell_count, 1)
        self.assertEqual(result.missing_cost_token_amount, Decimal("10"))


class RateLimiterUtilTests(unittest.TestCase):
    def test_target_80_percent_long_term(self):
        clock = FakeClock()
        limiter = WeightedRateLimiter(rate=5, capacity=5, target_utilization=0.8, clock=clock)
        granted = 0
        for _ in range(80):
            limiter.acquire(1)
            granted += 1
        elapsed = clock.unix - 1_000_000.0
        rate = granted / max(elapsed, 0.001)
        self.assertGreater(elapsed, 10)
        self.assertAlmostEqual(rate, 4.0, delta=0.8)

    def test_independent_key_limiters(self):
        clock = FakeClock()
        pool = CredentialPool(["k1aaaa", "k2bbbb"], clock=clock, rate=5, capacity=5, target_utilization=1.0, initial_utilization=1.0)
        a, b = pool.all()
        before = b.limiter.tokens
        a.limiter.acquire(3)
        self.assertAlmostEqual(b.limiter.tokens, before)

    def test_429_blocks_only_that_key(self):
        clock = FakeClock()
        limiter = WeightedRateLimiter(rate=5, capacity=5, target_utilization=0.8, clock=clock)
        reset = int(clock.unix) + 4
        limiter.set_server_cooldown(reset)
        limiter.acquire(1)
        self.assertGreaterEqual(sum(clock.sleeps), 4.0)

    def test_cancel_during_wait(self):
        event = threading.Event()
        event.set()
        limiter = WeightedRateLimiter(rate=0.01, capacity=1)
        limiter.tokens = 0
        with self.assertRaises(AnalysisCancelledError):
            limiter.acquire(3, event)


class CredentialTests(unittest.TestCase):
    def test_401_failover_does_not_use_failed_key(self):
        session = MagicMock()
        limiter = WeightedRateLimiter(rate=100, capacity=100)
        pool = CredentialPool(["bad-key-aaaa", "good-key-bbbb"])
        client = GMGNClient("bad-key-aaaa", limiter=limiter, session=session, credential_pool=pool, max_429_retries=0)
        first = MagicMock(status_code=401, headers={}, text='{"code":401,"error":"UNAUTHORIZED"}')
        second = MagicMock(status_code=200, headers={}, text='{"code":0,"data":{"ok":true}}')
        session.request.side_effect = [first, second]
        data = client.get_token_info("sol", "Mint")
        self.assertEqual(data, {"ok": True})
        states = {c.api_key: c.state for c in pool.all()}
        self.assertEqual(states["bad-key-aaaa"], CredentialState.AUTH_FAILED)
        self.assertEqual(states["good-key-bbbb"], CredentialState.HEALTHY)

    def test_429_switches_to_healthy_key(self):
        session = MagicMock()
        limiter = WeightedRateLimiter(rate=100, capacity=100)
        pool = CredentialPool(["key-one-aaaa", "key-two-bbbb"], rate=100, capacity=100, target_utilization=1, initial_utilization=1, safety_margin=0)
        client = GMGNClient("key-one-aaaa", limiter=limiter, session=session, credential_pool=pool, max_429_retries=3)
        reset = int(time.time()) + 30
        first = MagicMock(status_code=429, headers={"X-RateLimit-Reset": str(reset)}, text='{"code":429,"error":"RATE_LIMIT_EXCEEDED","reset_at":%s}' % reset)
        second = MagicMock(status_code=200, headers={}, text='{"code":0,"data":{"ok":true}}')
        session.request.side_effect = [first, second]
        data = client.get_user_info()
        self.assertEqual(data, {"ok": True})
        self.assertEqual(session.request.call_count, 2)
        used = [c.kwargs.get("headers", {}).get("X-APIKEY") for c in session.request.call_args_list]
        self.assertEqual(len(set(used)), 2)
        states = {c.api_key: c.state for c in pool.all()}
        self.assertEqual(states["key-one-aaaa"], CredentialState.RATE_LIMITED)
        self.assertNotEqual(states["key-two-bbbb"], CredentialState.AUTH_FAILED)


class SingleFlightTests(unittest.TestCase):
    def test_five_callers_one_execution(self):
        sf = SingleFlight()
        calls = []

        def work():
            time.sleep(0.05)
            calls.append(1)
            return "MintA"

        results = []

        def runner():
            results.append(sf.do("token_info|sol|MintA", work))

        threads = [threading.Thread(target=runner) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(calls, [1])
        self.assertEqual(results, ["MintA"] * 5)

    def test_client_token_info_singleflight(self):
        session = MagicMock()
        limiter = WeightedRateLimiter(rate=100, capacity=100)
        client = GMGNClient("k", limiter=limiter, session=session)
        started = threading.Event()
        release = threading.Event()

        def request(*args, **kwargs):
            started.set()
            release.wait(timeout=2)
            resp = MagicMock(status_code=200, headers={}, text='{"code":0,"data":{"address":"MintA"}}')
            return resp

        session.request.side_effect = request
        out = []

        def call():
            out.append(client.get_token_info("sol", "MintA"))

        threads = [threading.Thread(target=call) for _ in range(5)]
        for t in threads:
            t.start()
        self.assertTrue(started.wait(timeout=2))
        time.sleep(0.05)
        self.assertEqual(session.request.call_count, 1)
        release.set()
        for t in threads:
            t.join()
        self.assertEqual(len(out), 5)
        self.assertEqual(session.request.call_count, 1)


class StaleHistoryTests(unittest.TestCase):
    def test_incremental_sync_picks_new_buy(self):
        import os
        import tempfile
        from pathlib import Path

        fd, name = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        db = Database(path=Path(name))
        from app.storage.repositories import Repositories

        repos = Repositories(db)
        first_pages = {
            None: {
                "activities": [
                    {"event_type": "buy", "tx_hash": "old", "timestamp": 100, "token_amount": "1", "cost_usd": "1", "token": {"address": "M", "symbol": "S"}}
                ],
                "next": None,
            }
        }
        second_pages = {
            None: {
                "activities": [
                    {"event_type": "buy", "tx_hash": "new", "timestamp": 200, "token_amount": "2", "cost_usd": "2", "token": {"address": "M", "symbol": "S"}},
                    {"event_type": "buy", "tx_hash": "old", "timestamp": 100, "token_amount": "1", "cost_usd": "1", "token": {"address": "M", "symbol": "S"}},
                ],
                "next": None,
            }
        }

        class FakeClient:
            def __init__(self, pages):
                self.pages = pages
                self.calls = []

            def get_wallet_activity(self, chain, wallet, token_address=None, cursor=None, limit=50, types=None):
                self.calls.append(cursor)
                return self.pages[cursor]

        c1 = FakeClient(first_pages)
        collector = ActivityCollector(c1, repos)  # type: ignore
        trades, pages, complete = collector.collect_token_history("sol", "W", "M")
        self.assertTrue(complete)
        self.assertEqual({t.tx_hash for t in trades}, {"old"})
        self.assertEqual(pages, 1)

        c2 = FakeClient(second_pages)
        collector2 = ActivityCollector(c2, repos)  # type: ignore
        trades2, pages2, complete2 = collector2.collect_token_history("sol", "W", "M")
        self.assertTrue(complete2)
        self.assertEqual({t.tx_hash for t in trades2}, {"old", "new"})
        self.assertEqual(pages2, 1)
        self.assertEqual(len(c2.calls), 1)


class CursorSerialTests(unittest.TestCase):
    def test_cursor_pages_are_serial(self):
        order = []
        pages = {
            None: {"activities": [{"event_type": "buy", "tx_hash": "t1", "timestamp": 300, "token": {"address": "M"}, "token_amount": "1", "cost_usd": "1"}], "next": "c1"},
            "c1": {"activities": [{"event_type": "buy", "tx_hash": "t0", "timestamp": 100, "token": {"address": "M"}, "token_amount": "2", "cost_usd": "2"}], "next": None},
        }

        class FakeClient:
            def get_wallet_activity(self, chain, wallet, token_address=None, cursor=None, limit=50, types=None):
                order.append(cursor)
                return pages[cursor]

        trades, page_count, complete = ActivityCollector(FakeClient()).collect_token_history("sol", "W", "M", use_cache=False)  # type: ignore
        self.assertEqual(order, [None, "c1"])
        self.assertEqual(page_count, 2)
        self.assertTrue(complete)
        self.assertEqual({t.tx_hash for t in trades}, {"t1", "t0"})


class EventRoutingTests(unittest.TestCase):
    def test_job_a_event_not_consumed_as_job_b(self):
        class Dummy:
            def __init__(self, job_id):
                self.job_id = job_id
                self.received = []

            def handle_message(self, msg):
                jid = msg.get("job_id")
                if jid and self.job_id and jid != self.job_id:
                    return
                self.received.append(msg)

        a = Dummy("job-a")
        b = Dummy("job-b")
        bus = AnalysisEventBus()
        bus.emit({"type": "progress", "job_id": "job-a", "message": "A"})
        bus.emit({"type": "progress", "job_id": "job-b", "message": "B"})
        for event in bus.drain():
            a.handle_message(event)
            b.handle_message(event)
        self.assertEqual([e["message"] for e in a.received], ["A"])
        self.assertEqual([e["message"] for e in b.received], ["B"])


class ConcurrentTokenTests(unittest.TestCase):
    def test_four_tokens_complete(self):
        session = MagicMock()
        limiter = WeightedRateLimiter(rate=100, capacity=100)

        def request(method, url, params=None, json=None, headers=None, timeout=None):
            path = url.split("?")[0]
            q = {k: v for k, v in (params or [])}
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            if path.endswith("/v1/user/wallet_stats"):
                resp.text = '{"code":0,"data":{"realized_profit":"1"}}'
            elif path.endswith("/v1/user/wallet_profits"):
                resp.text = '{"code":0,"data":{"list":[]}}'
            elif path.endswith("/v1/user/wallet_activity"):
                token = q.get("token_address")
                if not token:
                    acts = [
                        {"event_type": "buy", "tx_hash": f"b{i}", "timestamp": 100 + i, "token_amount": "1", "cost_usd": "1", "token": {"address": f"Mint{i}", "symbol": f"T{i}"}}
                        for i in range(4)
                    ]
                    resp.text = '{"code":0,"data":{"activities":%s,"next":null}}' % __import__("json").dumps(acts)
                else:
                    resp.text = '{"code":0,"data":{"activities":[{"event_type":"buy","tx_hash":"h-%s","timestamp":50,"token_amount":"1","cost_usd":"1","token":{"address":"%s","symbol":"S"}}],"next":null}}' % (token, token)
            elif path.endswith("/v1/token/info"):
                addr = q.get("address")
                resp.text = '{"code":0,"data":{"address":"%s","symbol":"S","creation_timestamp":10}}' % addr
            elif path.endswith("/v1/token/pool_info"):
                resp.text = '{"code":0,"data":{"exchange":"raydium"}}'
            else:
                resp.text = '{"code":0,"data":{}}'
            return resp

        session.request.side_effect = request
        import os
        import tempfile
        from pathlib import Path

        from app.domain.enums import ReportPeriod
        from app.domain.models import AnalysisOptions, WalletAnalysisRequest
        from app.services.wallet_analysis_service import WalletAnalysisService

        fd, name = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        client = GMGNClient("k", limiter=limiter, session=session, max_429_retries=0)
        svc = WalletAnalysisService(client, db=Database(path=Path(name)), token_workers=4)
        req = WalletAnalysisRequest(
            wallet_address="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
            period=ReportPeriod.ALL,
            start_time=0,
            end_time=9999999999,
            options=AnalysisOptions(save_raw_json=False),
        )
        report = svc.analyze(req)
        self.assertEqual(len(report.tokens), 4)
        self.assertEqual(len({t.token_address for t in report.tokens}), 4)


if __name__ == "__main__":
    unittest.main()
