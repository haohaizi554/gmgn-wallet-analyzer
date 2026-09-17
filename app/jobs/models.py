from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from app.domain.models import AnalysisOptions, WalletAnalysisRequest, WalletReport


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_API = "WAITING_API"
    PAUSED = "PAUSED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    PARTIAL = "PARTIAL"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRYING = "RETRYING"


@dataclass
class WalletTask:
    wallet: str
    wallet_task_id: str = ""
    state: JobState = JobState.QUEUED
    progress: int = 0
    current_stage: str = "WAITING"
    token_total: int = 0
    token_completed: int = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: str = ""
    api_requests: int = 0
    cache_hits: int = 0
    count_429: int = 0
    used_key: str = ""


@dataclass
class AnalysisJob:
    job_id: str
    wallets: list[str]
    requests: list[WalletAnalysisRequest]
    created_at: datetime
    state: JobState = JobState.QUEUED
    page: str = "analysis"
    options: AnalysisOptions = field(default_factory=AnalysisOptions)
    wallet_tasks: dict[str, WalletTask] = field(default_factory=dict)
    reports: list[WalletReport] = field(default_factory=list)
    error: str = ""
