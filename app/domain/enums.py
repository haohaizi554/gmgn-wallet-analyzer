from __future__ import annotations

from enum import Enum


class ReportPeriod(str, Enum):
    D7 = "7d"
    D30 = "30d"
    D90 = "90d"
    ALL = "all"
    CUSTOM = "custom"


class EventType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    TRANSFER_IN = "transferIn"
    TRANSFER_OUT = "transferOut"
    ADD = "add"
    REMOVE = "remove"
    UNKNOWN = "unknown"


class AcquisitionType(str, Enum):
    BUY = "BUY"
    TRANSFER_IN = "TRANSFER_IN"
    BRIDGE = "BRIDGE"
    WRAPPED = "WRAPPED"
    AIRDROP = "AIRDROP"
    MINT = "MINT"
    UNKNOWN = "UNKNOWN"


class AcquisitionStatus(str, Enum):
    VERIFIED = "VERIFIED"
    INFERRED = "INFERRED"
    NO_BUY_HISTORY = "NO_BUY_HISTORY"
    API_UNAVAILABLE = "API_UNAVAILABLE"


class FieldStatus(str, Enum):
    KNOWN = "KNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    ESTIMATED = "ESTIMATED"
    API_MISSING = "API_MISSING"
    ERROR = "ERROR"


class TaskStatus(str, Enum):
    WAITING = "WAITING"
    WAITING_API = "WAITING_API"
    RETRYING = "RETRYING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    WARNING = "WARNING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ApiHealth(str, Enum):
    OK = "API 正常"
    WAITING = "等待限频"
    COOLDOWN = "429 冷却"


class TokenPositionStatus(str, Enum):
    OPEN = "仍持仓"
    CLOSED = "已清仓"
    UNKNOWN = "持仓未知"
