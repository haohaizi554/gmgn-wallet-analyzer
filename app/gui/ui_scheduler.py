from __future__ import annotations

from typing import Any

CRITICAL_TYPES = frozenset(
    {
        "done",
        "cancelled",
        "error",
        "wallet_done",
        "WALLET_STARTED",
        "WALLET_FINISHED",
        "WALLET_WAITING_API",
        "RATE_LIMITED",
        "KEY_RECOVERED",
        "PROVIDER_HEALTH",
        "api_state",
        "JOB_STARTED",
    }
)
PROGRESS_TYPE = "progress"
LOG_TYPE = "log"
DRAIN_BUDGET = 120
LOG_FLUSH_LIMIT = 40


def row_identity(row: dict[str, Any], idx: int = 0) -> str:
    raw = row.get("_id") or row.get("_copy")
    if raw:
        return str(raw)
    return f"r{idx}"


def plan_tree_patch(existing_ids: list[str], wanted_ids: list[str]) -> dict[str, list]:
    existing_set = set(existing_ids)
    wanted_set = set(wanted_ids)
    return {
        "delete": [iid for iid in existing_ids if iid not in wanted_set],
        "insert": [iid for iid in wanted_ids if iid not in existing_set],
        "order": list(wanted_ids),
    }


def coalesce_messages(messages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Latest-state-wins for noisy progress; keep critical order; bound log flush."""
    logs: list[dict[str, Any]] = []
    progress: dict[str, dict[str, Any]] = {}
    critical: list[dict[str, Any]] = []
    finished: set[str] = set()
    for msg in messages:
        kind = msg.get("type")
        if kind == LOG_TYPE:
            logs.append(msg)
            continue
        if kind == PROGRESS_TYPE:
            wallet = str(msg.get("wallet") or "_")
            if wallet not in finished:
                progress[wallet] = msg
            continue
        if kind in ("wallet_done", "WALLET_FINISHED"):
            wallet = str(msg.get("wallet") or "_")
            finished.add(wallet)
            progress.pop(wallet, None)
        elif kind in ("done", "cancelled", "error"):
            progress.clear()
            finished.add("_")
        critical.append(msg)
    return {
        "logs": logs[-LOG_FLUSH_LIMIT:],
        "progress": list(progress.values()),
        "critical": critical,
    }
