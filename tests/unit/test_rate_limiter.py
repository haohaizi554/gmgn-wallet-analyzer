from __future__ import annotations

import unittest

from app.api.rate_limiter import Clock, WeightedRateLimiter


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


class RateLimiterTests(unittest.TestCase):
    def test_acquire_consumes_weight_and_refills(self):
        clock = FakeClock()
        limiter = WeightedRateLimiter(rate=5, capacity=5, clock=clock)
        limiter.acquire(3)
        self.assertAlmostEqual(limiter.tokens, 2.0)
        limiter.acquire(3)
        self.assertTrue(clock.sleeps)
        self.assertGreaterEqual(sum(clock.sleeps), 0.1)

    def test_429_header_sets_cooldown_and_waits(self):
        clock = FakeClock()
        limiter = WeightedRateLimiter(rate=5, capacity=5, clock=clock)
        reset = int(clock.unix) + 3
        got = limiter.update_from_headers({"X-RateLimit-Reset": str(reset)}, {"reset_at": reset})
        self.assertEqual(got, reset)
        limiter.acquire(1)
        self.assertGreaterEqual(sum(clock.sleeps), 3.0)


class Client429Tests(unittest.TestCase):
    def test_client_switches_key_instead_of_inner_sleep_retry(self):
        from unittest.mock import MagicMock

        from app.api.credential_pool import CredentialPool
        from app.api.gmgn_client import GMGNClient

        session = MagicMock()
        limiter = WeightedRateLimiter(rate=100, capacity=100)
        pool = CredentialPool(["aaaa1111", "bbbb2222"], rate=100, capacity=100, target_utilization=1, initial_utilization=1, safety_margin=0)
        client = GMGNClient("aaaa1111", limiter=limiter, session=session, credential_pool=pool, max_429_retries=3)
        import time as time_mod

        reset = int(time_mod.time()) + 30
        first = MagicMock(status_code=429, headers={"X-RateLimit-Reset": str(reset)}, text='{"code":429,"error":"RATE_LIMIT_EXCEEDED","reset_at":%s}' % reset)
        second = MagicMock(status_code=200, headers={}, text='{"code":0,"data":{"ok":true}}')
        session.request.side_effect = [first, second]
        data = client.get_token_info("sol", "Mint")
        self.assertEqual(data, {"ok": True})
        self.assertEqual(session.request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
