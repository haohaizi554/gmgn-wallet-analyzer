from __future__ import annotations

import json
import time
from pathlib import Path

from app.api.credential_pool import CredentialPool
from app.api.gmgn_client import GMGNClient
from app.api.rate_limiter import WeightedRateLimiter
from app.config import load_config
from app.domain.enums import ReportPeriod
from app.domain.models import AnalysisOptions, WalletAnalysisRequest
from app.services.wallet_analysis_service import WalletAnalysisService
from app.storage.database import Database
from app.utils.paths import LOG_DIR, ensure_runtime_dirs
from app.utils.time_utils import period_window

WALLET = "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV"


def main() -> None:
    ensure_runtime_dirs()
    cfg = load_config()
    if not cfg.has_api_key:
        raise SystemExit("缺少 GMGN_API_KEY")
    limiter = WeightedRateLimiter(
        cfg.rate,
        cfg.capacity,
        target_utilization=cfg.target_utilization,
        initial_utilization=getattr(cfg, "initial_utilization", 0.60),
        safety_margin=getattr(cfg, "reset_safety_margin", 3.0),
    )
    pool = CredentialPool(
        cfg.api_keys,
        rate=cfg.rate,
        capacity=cfg.capacity,
        target_utilization=cfg.target_utilization,
        initial_utilization=getattr(cfg, "initial_utilization", 0.60),
        safety_margin=getattr(cfg, "reset_safety_margin", 3.0),
    )
    client = GMGNClient(
        cfg.api_key,
        cfg.api_base,
        limiter=limiter,
        credential_pool=pool,
        max_429_retries=cfg.rate_limit_max_retries,
        safety_margin=getattr(cfg, "reset_safety_margin", 3.0),
        shared_limit_detection=getattr(cfg, "shared_limit_detection", True),
    )
    print("smoke user_info...", flush=True)
    info = client.get_user_info()
    print("user_info keys:", list(info)[:12] if isinstance(info, dict) else type(info), flush=True)
    start_ts, end_ts = period_window(ReportPeriod.D7)
    req = WalletAnalysisRequest(
        wallet_address=WALLET,
        period=ReportPeriod.D7,
        start_time=start_ts,
        end_time=end_ts,
        max_transactions=2500,
        options=AnalysisOptions(save_raw_json=False),
    )
    db = Database()
    svc = WalletAnalysisService(
        client,
        db=db,
        token_ttl=cfg.token_info_ttl_seconds,
        pool_ttl=cfg.token_pool_ttl_seconds,
        token_workers=cfg.api_workers,
    )
    print("analyze cold/warm depending on sqlite cache...", flush=True)
    t0 = time.time()
    report = svc.analyze(req)
    elapsed = time.time() - t0
    snap = limiter.snapshot()
    payload = {
        "wallet": WALLET,
        "elapsed_seconds": round(elapsed, 2),
        "tokens": len(report.tokens),
        "trades": len(report.trades),
        "buy_count": report.summary.buy_count,
        "sell_count": report.summary.sell_count,
        "missing_cost": report.summary.missing_cost_count,
        "special": report.summary.special_acquisition_count,
        "api_requests": report.api_stats.requests,
        "cache_hit_rate": report.api_stats.cache_hit_rate,
        "429": report.api_stats.retries_429,
        "excel": report.excel_path,
        "utilization_1m": snap.utilization_1m,
        "effective_rate": snap.effective_rate,
        "target": snap.target_utilization,
        "first_buys": [
            {
                "symbol": t.symbol,
                "token": t.token_address,
                "ts": t.acquisition.timestamp,
                "platform": str(t.source_platform.export("text")),
            }
            for t in report.tokens[:10]
        ],
    }
    out = LOG_DIR / "real_api_benchmark.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
