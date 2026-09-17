from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
LOG_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"
REPORT_DIR = OUTPUT_DIR / "reports"
DB_PATH = DATA_DIR / "gmgn_wallet.db"
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"


def ensure_runtime_dirs() -> None:
    for path in (DATA_DIR, RAW_DIR, LOG_DIR, OUTPUT_DIR, REPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)
