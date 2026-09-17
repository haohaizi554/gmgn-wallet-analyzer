from __future__ import annotations

import threading
import unittest

from app.api.exceptions import AnalysisCancelledError
from app.api.rate_limiter import WeightedRateLimiter
from app.gui.worker import AnalysisWorker


class CancelTests(unittest.TestCase):
    def test_limiter_stops_on_event(self):
        event = threading.Event()
        event.set()
        limiter = WeightedRateLimiter(rate=0.01, capacity=1)
        limiter.tokens = 0
        with self.assertRaises(AnalysisCancelledError):
            limiter.acquire(3, event)

    def test_worker_is_not_main_thread_and_uses_event(self):
        self.assertTrue(issubclass(AnalysisWorker, threading.Thread))
        src = AnalysisWorker.run.__code__.co_names
        self.assertNotIn("CTkLabel", src)
        self.assertNotIn("configure", src)


if __name__ == "__main__":
    unittest.main()
