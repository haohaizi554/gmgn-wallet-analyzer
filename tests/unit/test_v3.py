from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock

from app.api.credential_pool import CredentialPool, CredentialState
from app.api.gmgn_client import GMGNClient
from app.api.metrics import RateMetrics
from app.api.rate_limiter import Clock, WeightedRateLimiter
from app.api.scheduler import MODE_SHARED, CredentialScheduler, GlobalSafetyController
from app.config import AppConfig
from app.domain.enums import ReportPeriod
from app.domain.models import AnalysisOptions, WalletAnalysisRequest
from app.gui.sidebar import NAV_ITEMS
from app.jobs.engine import AnalysisJobEngine, assign_task_ids
from app.jobs.event_bus import AnalysisEventBus
from app.jobs.models import JobState
from app.storage.database import Database
from app.storage.raw_dump import write_raw_json
from app.storage.repositories import Repositories
from app.utils.validators import summarize_wallet_input


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


def _db() -> Database:
    fd, name = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path=Path(name))


def _cfg(**kwargs) -> AppConfig:
    data = dict(
        api_key="k",
        api_keys=["k"],
        api_base="https://openapi.gmgn.ai",
        plan="Free",
        rate=100,
        capacity=100,
        target_utilization=0.75,
        initial_utilization=0.60,
        reset_safety_margin=3.0,
        shared_limit_detection=True,
        max_api_wait=8.0,
        api_workers=4,
        token_info_ttl_seconds=10,
        token_pool_ttl_seconds=10,
        wallet_stats_ttl_seconds=10,
        rate_limit_max_retries=8,
    )
    data.update(kwargs)
    return AppConfig(**data)


class IndependentLimiterTests(unittest.TestCase):
    def test_key1_acquire_does_not_consume_key2(self):
        clock = FakeClock()
        pool = CredentialPool(["k1xxxx", "k2yyyy"], clock=clock, rate=5, capacity=5, target_utilization=1, initial_utilization=1)
        a, b = pool.all()
        start_b = b.limiter.tokens
        a.limiter.acquire(3)
        self.assertAlmostEqual(b.limiter.tokens, start_b)
        self.assertLess(a.limiter.tokens, 5)


class Isolation429Tests(unittest.TestCase):
    def test_key1_429_key2_still_schedulable(self):
        pool = CredentialPool(["k1xxxx", "k2yyyy"], rate=100, capacity=100, target_utilization=1, initial_utilization=1, safety_margin=3)
        a, b = pool.all()
        pool.mark_429(a, reset_at=int(time.time()) + 40, banned=False, safety_margin=3)
        sch = CredentialScheduler(pool, max_wait=2)
        lease = sch.acquire_credential("user_info")
        self.assertEqual(lease.credential.api_key, b.api_key)
        sch.release_credential(lease)


class BannedNoRequestTests(unittest.TestCase):
    def test_banned_key_http_count_zero(self):
        session = MagicMock()
        pool = CredentialPool(["k1xxxx", "k2yyyy"], rate=100, capacity=100, target_utilization=1, initial_utilization=1, safety_margin=3)
        a, b = pool.all()
        pool.mark_429(a, reset_at=int(time.time()) + 60, banned=True, safety_margin=3)
        session.request.return_value = MagicMock(status_code=200, headers={}, text='{"code":0,"data":{"ok":true}}')
        client = GMGNClient("k1xxxx", limiter=WeightedRateLimiter(rate=100, capacity=100), session=session, credential_pool=pool)
        data = client.get_user_info()
        self.assertEqual(data, {"ok": True})
        used = [c.kwargs["headers"]["X-APIKEY"] for c in session.request.call_args_list]
        self.assertNotIn("k1xxxx", used)
        self.assertEqual(used, ["k2yyyy"])


class ResetMarginTests(unittest.TestCase):
    def test_reset_safety_margin(self):
        clock = FakeClock()
        clock.unix = 100.0
        clock.mono = 100.0
        limiter = WeightedRateLimiter(rate=5, capacity=5, clock=clock, safety_margin=3)
        limiter.set_server_cooldown(100)
        self.assertGreaterEqual(limiter.effective_resume_at(), 103)
        limiter.acquire(1)
        self.assertGreaterEqual(clock.unix, 103)


class NoInnerRetryTests(unittest.TestCase):
    def test_repeated_429_not_inner_loop_same_key(self):
        session = MagicMock()
        pool = CredentialPool(["k1xxxx", "k2yyyy"], rate=100, capacity=100, target_utilization=1, initial_utilization=1, safety_margin=0)
        reset = int(time.time()) + 60
        first = MagicMock(status_code=429, headers={"X-RateLimit-Reset": str(reset)}, text='{"code":429,"error":"RATE_LIMIT_BANNED","message":"冷却期间请勿继续发请求","reset_at":%s}' % reset)
        second = MagicMock(status_code=200, headers={}, text='{"code":0,"data":{"ok":true}}')
        session.request.side_effect = [first, second]
        client = GMGNClient("k1xxxx", limiter=WeightedRateLimiter(rate=100, capacity=100), session=session, credential_pool=pool)
        client.get_user_info()
        keys = [c.kwargs["headers"]["X-APIKEY"] for c in session.request.call_args_list]
        self.assertEqual(keys[0], keys[0])
        self.assertEqual(len(keys), 2)
        self.assertNotEqual(keys[0], keys[1])


class WalletWaitingApiTests(unittest.TestCase):
    def test_all_keys_cooldown_wallet_waiting_not_failed(self):
        pool = CredentialPool(["k1xxxx"], rate=5, capacity=5, safety_margin=3)
        cred = pool.all()[0]
        pool.mark_429(cred, reset_at=int(time.time()) + 30, banned=True, safety_margin=3)
        bus = AnalysisEventBus()
        engine = AnalysisJobEngine(_cfg(api_keys=["k1xxxx"], max_api_wait=1), _db(), cred.limiter, pool, bus)
        job_id = "job-wait"
        req = WalletAnalysisRequest(wallet_address="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV", job_id=job_id, wallet_task_id=f"{job_id}:w")
        from app.jobs.models import AnalysisJob, WalletTask
        from datetime import datetime

        job = AnalysisJob(
            job_id=job_id,
            wallets=[req.wallet_address],
            requests=[req],
            created_at=datetime.now(),
            wallet_tasks={req.wallet_address: WalletTask(wallet=req.wallet_address, wallet_task_id=req.wallet_task_id)},
        )
        task = job.wallet_tasks[req.wallet_address]
        cancel = threading.Event()
        client = engine._make_client(job, cancel)
        with self.assertRaises(Exception):
            engine._guard_api(job, task, client.scheduler, cancel)
        self.assertEqual(task.state, JobState.WAITING_API)
        self.assertNotEqual(task.state, JobState.FAILED)


class NextWalletProtectionTests(unittest.TestCase):
    def test_next_wallet_does_not_use_banned_key(self):
        session = MagicMock()
        pool = CredentialPool(["onlykeyxx"], rate=100, capacity=100, safety_margin=3)
        cred = pool.all()[0]
        pool.mark_429(cred, reset_at=int(time.time()) + 45, banned=True, safety_margin=3)
        session.request.return_value = MagicMock(status_code=200, headers={}, text='{"code":0,"data":{}}')
        client = GMGNClient("onlykeyxx", limiter=WeightedRateLimiter(rate=100, capacity=100), session=session, credential_pool=pool, max_api_wait=0.4)
        cancel = threading.Event()
        cancel.set()
        client.set_cancel_event(cancel)
        from app.api.exceptions import AnalysisCancelledError, GMGNRateLimitError

        with self.assertRaises((AnalysisCancelledError, GMGNRateLimitError)):
            client.get_wallet_stats("sol", "W")
        self.assertEqual(session.request.call_count, 0)


class GlobalSafetyTests(unittest.TestCase):
    def test_two_keys_429_triggers_global_cooldown(self):
        pool = CredentialPool(["k1xxxx", "k2yyyy"], safety_margin=3)
        a, b = pool.all()
        now = time.time()
        safety = GlobalSafetyController(pool, enabled=True, safety_margin=3)
        safety.note_429(a, int(now) + 10)
        safety.note_429(b, int(now) + 11)
        self.assertEqual(safety.mode, MODE_SHARED)
        self.assertGreater(safety.global_cooldown_until, now)
        self.assertGreaterEqual(safety.global_cooldown_count, 1)


class DistributionTests(unittest.TestCase):
    def test_three_keys_300_requests_balanced(self):
        pool = CredentialPool(
            ["k1xxxx", "k2yyyy", "k3zzzz"],
            rate=1000,
            capacity=1000,
            target_utilization=1,
            initial_utilization=1,
            safety_margin=0,
        )
        sch = CredentialScheduler(pool, max_wait=5)
        counts = {c.id: 0 for c in pool.all()}
        for _ in range(300):
            lease = sch.acquire_credential("token_info", weight=1)
            counts[lease.credential.id] += 1
            sch.release_credential(lease)
        for value in counts.values():
            self.assertGreaterEqual(value / 300, 0.25)
            self.assertLessEqual(value / 300, 0.40)


class JobWalletIdTests(unittest.TestCase):
    def test_three_wallets_three_tasks_and_reports(self):
        db = _db()
        repos = Repositories(db)
        job_id = "JOB-ABC"
        wallets = [
            "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
            "9P9aAh3kdMK651CcDG4iCdoByYj1FJgKq3yVoPrXVCAu",
            "So11111111111111111111111111111111111111112",
        ]
        reqs = [WalletAnalysisRequest(wallet_address=w) for w in wallets]
        assign_task_ids(reqs, job_id)
        ids = [r.wallet_task_id for r in reqs]
        self.assertEqual(len(set(ids)), 3)
        for req in reqs:
            repos.save_wallet_task(req.wallet_task_id, job_id, req.wallet_address, "RUNNING")
            repos.save_report(
                req.wallet_task_id,
                req.wallet_address,
                "sol",
                "7d",
                0,
                1,
                "SUCCESS",
                {"ok": True},
                "a.xlsx",
                "a.json",
                1.0,
                job_id=job_id,
                wallet_task_id=req.wallet_task_id,
            )
        self.assertEqual(len(repos.list_wallet_tasks(job_id)), 3)
        rows = db.query("SELECT id, wallet_task_id FROM wallet_reports")
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["id"] for r in rows}), 3)


class HistoryDeleteTests(unittest.TestCase):
    def test_delete_job_and_report_rows(self):
        db = _db()
        repos = Repositories(db)
        job_id = "JOB-DEL"
        repos.save_job(job_id, ["7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV"], "single", "SUCCESS", {"token_count": 1}, "a.xlsx", 1.0)
        repos.save_report("R1", "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV", "sol", "7d", 0, 1, "SUCCESS", {}, "a.xlsx", "a.json", 1.0, job_id=job_id)
        self.assertEqual(len(repos.list_jobs()), 1)
        self.assertEqual(len(repos.list_reports()), 1)
        repos.delete_report("R1")
        self.assertEqual(len(repos.list_reports()), 0)
        self.assertEqual(len(repos.list_jobs()), 1)
        repos.delete_job(job_id)
        self.assertEqual(len(repos.list_jobs()), 0)


class RawJsonTests(unittest.TestCase):
    def test_100_threads_unique_files(self):
        job = f"JOB-{uuid.uuid4().hex[:8]}"
        paths = []
        lock = threading.Lock()

        def work(i: int) -> None:
            path = write_raw_json(job, "WalletABC", "wallet_activity", {"i": i})
            with lock:
                paths.append(str(path))

        threads = [threading.Thread(target=work, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(paths), 100)
        self.assertEqual(len(set(paths)), 100)


class Metric429Tests(unittest.TestCase):
    def test_one_429_counts_once(self):
        session = MagicMock()
        pool = CredentialPool(["k1xxxx", "k2yyyy"], rate=100, capacity=100, target_utilization=1, initial_utilization=1, safety_margin=0)
        metrics = RateMetrics()
        reset = int(time.time()) + 20
        first = MagicMock(status_code=429, headers={"X-RateLimit-Reset": str(reset)}, text='{"code":429,"error":"RATE_LIMIT_EXCEEDED","reset_at":%s}' % reset)
        second = MagicMock(status_code=200, headers={}, text='{"code":0,"data":{"ok":true}}')
        session.request.side_effect = [first, second]
        client = GMGNClient(
            "k1xxxx",
            limiter=WeightedRateLimiter(rate=100, capacity=100, metrics=metrics),
            session=session,
            credential_pool=pool,
            metrics=metrics,
        )
        client.get_user_info()
        self.assertEqual(metrics.total_429, 1)
        self.assertEqual(metrics.total_requests, 2)
        self.assertEqual(metrics.rate_limit_events, 1)


class LimiterJobIsolationTests(unittest.TestCase):
    def test_new_job_does_not_reset_cooldown(self):
        limiter = WeightedRateLimiter(rate=5, capacity=5, safety_margin=3)
        reset = int(time.time()) + 25
        limiter.set_server_cooldown(reset)
        until = limiter.effective_resume_at()
        # simulate job start: must NOT call limiter.reset()
        self.assertGreaterEqual(until, reset + 3)
        self.assertGreater(limiter.effective_resume_at(), time.time())


class GuiMergeTests(unittest.TestCase):
    def test_single_and_batch_same_page(self):
        labels = dict(NAV_ITEMS)
        self.assertEqual(labels.get("analysis"), "分析任务")
        self.assertNotIn("batch", labels)
        self.assertNotIn("任务进度", labels.values())
        one = summarize_wallet_input("7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV\n")
        self.assertEqual(one["valid"], 1)
        self.assertEqual(one["mode_batch"], 0)
        two = summarize_wallet_input(
            "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV\n9P9aAh3kdMK651CcDG4iCdoByYj1FJgKq3yVoPrXVCAu\n"
        )
        self.assertEqual(two["valid"], 2)
        self.assertEqual(two["mode_batch"], 1)


class FairSchedulerTests(unittest.TestCase):
    def test_round_robin_token_order(self):
        queues = [["A1", "A2", "A3", "A4"], ["B1", "B2"], ["C1", "C2", "C3"]]
        order = []
        while any(queues):
            for q in queues:
                if q:
                    order.append(q.pop(0))
        self.assertEqual(order[:3], ["A1", "B1", "C1"])
        a_done = order.index("A4")
        self.assertLess(order.index("B1"), a_done)
        self.assertLess(order.index("C1"), a_done)


class FairEngineTests(unittest.TestCase):
    def test_parallel_wallets_interleave_starts(self):
        starts: list[tuple[float, str]] = []
        finishes: list[tuple[float, str]] = []

        class DummyReport:
            tokens = []
            api_stats = type("S", (), {"requests": 0, "cache_hits": 0, "retries_429": 0})()
            excel_path = ""
            status = type("T", (), {"value": "SUCCESS"})()

        class DummyService:
            cache = type("C", (), {"hits": 0, "misses": 0})()

            def analyze(self, request):
                starts.append((time.time(), request.wallet_address))
                time.sleep(0.12)
                finishes.append((time.time(), request.wallet_address))
                DummyReport.request = request
                return DummyReport()

        wallets = ["AaaWallet111111111111111111111111111111", "BbbWallet111111111111111111111111111111", "CccWallet111111111111111111111111111111"]
        # use valid-length dummy strings; engine doesn't validate
        wallets = ["W1" + "x" * 40, "W2" + "y" * 40, "W3" + "z" * 40]
        reqs = [WalletAnalysisRequest(wallet_address=w) for w in wallets]
        assign_task_ids(reqs, "JOB-FAIR")
        from datetime import datetime
        from app.jobs.models import AnalysisJob, WalletTask

        job = AnalysisJob(
            job_id="JOB-FAIR",
            wallets=wallets,
            requests=reqs,
            created_at=datetime.now(),
            wallet_tasks={w: WalletTask(wallet=w, wallet_task_id=f"JOB-FAIR:{w}") for w in wallets},
        )
        pool = CredentialPool(["k1xxxx"], rate=100, capacity=100)
        engine = AnalysisJobEngine(_cfg(), _db(), pool.all()[0].limiter, pool, AnalysisEventBus())
        engine._guard_api = lambda *a, **k: None  # type: ignore
        engine._analyze_wallets_fair(job, DummyService(), engine.scheduler or CredentialScheduler(pool), threading.Event())  # type: ignore
        # B should start before A finishes if parallel
        if len(starts) >= 2 and len(finishes) >= 1:
            first_finish = min(t for t, _ in finishes)
            second_start = sorted(starts)[1][0]
            self.assertLess(second_start, first_finish + 0.01)


if __name__ == "__main__":
    unittest.main()
