from __future__ import annotations

import queue
import threading
import uuid
from typing import Optional

from app.api.credential_pool import CredentialPool
from app.api.exceptions import AnalysisCancelledError
from app.api.rate_limiter import WeightedRateLimiter
from app.config import AppConfig
from app.domain.models import WalletAnalysisRequest, WalletReport
from app.jobs.engine import AnalysisJobEngine
from app.jobs.event_bus import AnalysisEventBus
from app.storage.database import Database
from app.utils.logger import get_logger

logger = get_logger("gmgn.worker")


class AnalysisWorker(threading.Thread):
    def __init__(
        self,
        requests: list[WalletAnalysisRequest],
        config: AppConfig,
        message_queue: queue.Queue,
        cancel_event: threading.Event,
        db: Database,
        limiter: WeightedRateLimiter,
        page: str = "analysis",
        credentials: Optional[CredentialPool] = None,
    ) -> None:
        super().__init__(daemon=True, name="gmgn-analysis-worker")
        self.requests = requests
        self.config = config
        self.queue = message_queue
        self.cancel_event = cancel_event
        self.db = db
        self.limiter = limiter
        self.page = page
        self.job_id = str(uuid.uuid4())
        from app.jobs.engine import assign_task_ids

        assign_task_ids(requests, self.job_id)
        self.credentials = credentials or CredentialPool(config.api_keys or ([config.api_key] if config.api_key else []))
        self.reports: list[WalletReport] = []

    def run(self) -> None:
        bus = AnalysisEventBus(self.queue)
        engine = AnalysisJobEngine(self.config, self.db, self.limiter, self.credentials, bus)
        try:
            self.reports = engine.run_blocking(self.requests, self.cancel_event, page=self.page)
        except AnalysisCancelledError:
            logger.info("分析已取消")
            self.queue.put({"type": "cancelled", "reports": self.reports, "job_id": self.job_id, "page": self.page})
        except Exception as exc:
            logger.exception("分析线程失败")
            self.queue.put({"type": "error", "message": str(exc), "reports": self.reports, "job_id": self.job_id, "page": self.page})
