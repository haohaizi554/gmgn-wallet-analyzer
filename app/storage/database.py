from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from app.storage.migrations import migrate
from app.utils.paths import DB_PATH, ensure_runtime_dirs

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=8000;
CREATE TABLE IF NOT EXISTS wallet_reports (
    id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    chain TEXT NOT NULL,
    period TEXT NOT NULL,
    start_time INTEGER,
    end_time INTEGER,
    status TEXT NOT NULL,
    summary_json TEXT,
    excel_path TEXT,
    json_path TEXT,
    created_at INTEGER NOT NULL,
    elapsed_seconds REAL
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    chain TEXT NOT NULL,
    token_address TEXT NOT NULL,
    event_type TEXT NOT NULL,
    tx_hash TEXT NOT NULL,
    timestamp INTEGER,
    payload_json TEXT NOT NULL,
    activity_fingerprint TEXT NOT NULL,
    UNIQUE(activity_fingerprint)
);
CREATE TABLE IF NOT EXISTS token_info_cache (
    chain TEXT NOT NULL,
    token_address TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY(chain, token_address)
);
CREATE TABLE IF NOT EXISTS token_pool_cache (
    chain TEXT NOT NULL,
    token_address TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY(chain, token_address)
);
CREATE TABLE IF NOT EXISTS analysis_results (
    task_id TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    token_address TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(task_id, wallet_address, token_address)
);
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    ttl_seconds INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_runs (
    task_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    status TEXT NOT NULL,
    current_token TEXT,
    progress_done INTEGER DEFAULT 0,
    progress_total INTEGER DEFAULT 0,
    error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS token_history_meta (
    wallet_address TEXT NOT NULL,
    token_address TEXT NOT NULL,
    history_complete INTEGER NOT NULL DEFAULT 0,
    page_count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    chain TEXT NOT NULL DEFAULT 'sol',
    bottom_complete INTEGER NOT NULL DEFAULT 0,
    oldest_timestamp INTEGER,
    newest_timestamp INTEGER,
    last_sync_at INTEGER,
    last_success_at INTEGER,
    known_head_fingerprint TEXT,
    page_count_total INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(wallet_address, token_address)
);
        CREATE TABLE IF NOT EXISTS analysis_jobs (
    job_id TEXT PRIMARY KEY,
    wallets_json TEXT NOT NULL,
    wallet_count INTEGER NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    summary_json TEXT,
    excel_path TEXT,
    created_at INTEGER NOT NULL,
    elapsed_seconds REAL,
    api_requests INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    state TEXT NOT NULL,
    wallet_count INTEGER NOT NULL,
    job_type TEXT,
    summary_json TEXT,
    excel_path TEXT,
    elapsed_seconds REAL,
    api_requests INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS wallet_tasks (
    wallet_task_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    state TEXT NOT NULL,
    progress INTEGER DEFAULT 0,
    current_stage TEXT,
    token_total INTEGER DEFAULT 0,
    token_completed INTEGER DEFAULT 0,
    started_at REAL,
    finished_at REAL,
    error TEXT,
    api_requests INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_wallet_token ON trades(wallet_address, token_address, timestamp);
CREATE INDEX IF NOT EXISTS idx_wallet_tasks_job ON wallet_tasks(job_id);
CREATE TABLE IF NOT EXISTS provider_cache (
    cache_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    capability TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    wallet_address TEXT,
    token_address TEXT,
    field_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    raw_value TEXT,
    normalized_value TEXT,
    reference TEXT,
    confidence REAL,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS resolved_fields (
    job_id TEXT NOT NULL,
    wallet TEXT NOT NULL,
    token TEXT NOT NULL,
    field_name TEXT NOT NULL,
    value TEXT,
    status TEXT NOT NULL,
    primary_source TEXT NOT NULL,
    confidence REAL,
    estimated INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    PRIMARY KEY(job_id, wallet, token, field_name)
);
CREATE TABLE IF NOT EXISTS mint_creation_cache (
    mint TEXT PRIMARY KEY,
    creation_signature TEXT,
    creation_time INTEGER,
    slot INTEGER,
    source TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT,
    fetched_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_metrics (
    job_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(job_id, provider)
);
CREATE TABLE IF NOT EXISTS verified_transactions (
    signature TEXT PRIMARY KEY,
    wallet_address TEXT,
    token_address TEXT,
    payload_json TEXT NOT NULL,
    fetched_at INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: Path | None = None) -> None:
        ensure_runtime_dirs()
        self.path = path or DB_PATH
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=8000")
            self._local.conn = conn
        return conn

    def _init(self) -> None:
        conn = self.connect()
        conn.executescript(SCHEMA)
        migrate(conn)
        conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._write_lock:
            cur = self.connect().execute(sql, params)
            self.connect().commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.connect().execute(sql, params).fetchall()

    def dumps(self, payload: object) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)
