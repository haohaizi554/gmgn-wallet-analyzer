from __future__ import annotations

import json
import time
from collections import Counter

from app.api.credential_pool import CredentialPool
from app.api.gmgn_client import GMGNClient
from app.api.rate_limiter import WeightedRateLimiter
from app.config import load_config
from app.utils.paths import LOG_DIR, ensure_runtime_dirs

WALLET = "9P9aAh3kdMK651CcDG4iCdoByYj1FJgKq3yVoPrXVCAu"
TARGET_PAGES = 50


def main() -> None:
    ensure_runtime_dirs()
    cfg = load_config()
    if not cfg.has_api_key:
        raise SystemExit("缺少 GMGN_API_KEY")
    pool = CredentialPool(
        cfg.api_keys,
        rate=cfg.rate,
        capacity=cfg.capacity,
        target_utilization=cfg.target_utilization,
        initial_utilization=getattr(cfg, "initial_utilization", 0.60),
        safety_margin=getattr(cfg, "reset_safety_margin", 3.0),
    )
    limiter = pool.all()[0].limiter
    client = GMGNClient(
        cfg.api_key,
        cfg.api_base,
        limiter=limiter,
        credential_pool=pool,
        max_429_retries=cfg.rate_limit_max_retries,
        safety_margin=getattr(cfg, "reset_safety_margin", 3.0),
        shared_limit_detection=getattr(cfg, "shared_limit_detection", True),
    )
    cursor = None
    pages = 0
    started = time.time()
    latencies: list[float] = []
    while pages < TARGET_PAGES:
        t0 = time.perf_counter()
        data = client.get_wallet_activity("sol", WALLET, cursor=cursor, limit=50)
        latencies.append(time.perf_counter() - t0)
        pages += 1
        next_cursor = None
        if isinstance(data, dict):
            next_cursor = data.get("next") or (data.get("data") or {}).get("next")
        print(f"page={pages} next={'yes' if next_cursor else 'null'} 429={client.retry_429_count}", flush=True)
        if not next_cursor:
            break
        cursor = next_cursor
    elapsed = time.time() - started
    key_counts = Counter(c.request_count for c in pool.all())
    payload = {
        "wallet": WALLET,
        "pages": pages,
        "elapsed_seconds": round(elapsed, 2),
        "pages_per_min": round(pages / max(elapsed / 60, 1e-6), 2),
        "api_requests": client.request_count,
        "429": client.retry_429_count,
        "metrics_429": client.metrics.total_429,
        "rate_limit_events": client.metrics.rate_limit_events,
        "avg_http_s": round(sum(latencies) / max(len(latencies), 1), 3),
        "local_rate_wait": round(client.metrics.local_rate_wait, 3),
        "credential_wait": round(client.metrics.credential_wait, 3),
        "global_safety_wait": round(client.metrics.global_safety_wait, 3),
        "keys": pool.snapshot(),
        "safety": client.scheduler.safety.snapshot(),
        "avg_utilization": [
            {"key": c.masked, "adaptive": c.limiter._adaptive_target, "requests": c.request_count, "429": c.count_429}
            for c in pool.all()
        ],
    }
    out = LOG_DIR / "stability_v3_benchmark.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    print("wrote", out, flush=True)


if __name__ == "__main__":
    main()
