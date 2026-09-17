from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.utils.paths import RAW_DIR, ensure_runtime_dirs


def write_raw_json(job_id: str, wallet: str, route: str, payload: Any) -> Path:
    ensure_runtime_dirs()
    safe_job = (job_id or "job").replace("/", "_")
    safe_wallet = (wallet or "wallet")[:16]
    safe_route = (route or "api").strip("/").replace("/", "_") or "api"
    folder = RAW_DIR / safe_job / safe_wallet
    folder.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = folder / f"{ts}_{safe_route}_{uuid.uuid4().hex[:6]}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path
