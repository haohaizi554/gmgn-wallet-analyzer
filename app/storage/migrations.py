from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.domain.fingerprint import activity_fingerprint
from app.utils.logger import get_logger

logger = get_logger("gmgn.migrate")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return str(row[0]) if row and row[0] else ""


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=8000")
    _migrate_trades(conn)
    _migrate_history_meta(conn)
    _migrate_jobs(conn)
    _migrate_wallet_identity(conn)
    _migrate_v4_provider_tables(conn)
    _migrate_v5_helius_tables(conn)
    _migrate_v52_history_events(conn)
    conn.commit()


def _migrate_trades(conn: sqlite3.Connection) -> None:
    cols = _columns(conn, "trades")
    if not cols:
        return
    sql = _table_sql(conn, "trades")
    if "activity_fingerprint" in sql and "UNIQUE" in sql.upper() and "activity_fingerprint" in sql:
        return
    logger.info("迁移 trades 表：UNIQUE(activity_fingerprint)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trades_v2 (
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
        )
        """
    )
    rows = conn.execute(
        "SELECT wallet_address, chain, token_address, event_type, tx_hash, timestamp, payload_json FROM trades"
    ).fetchall()
    seen: set[str] = set()
    for row in rows:
        try:
            payload = json.loads(row[6]) if row[6] else {}
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        fp = payload.get("activity_fingerprint") or activity_fingerprint(str(row[1]), str(row[0]), payload)
        if not fp or fp in seen:
            fp = f"{fp}:{row[4]}:{row[3]}:{row[5]}"
        seen.add(fp)
        conn.execute(
            """
            INSERT OR IGNORE INTO trades_v2(wallet_address, chain, token_address, event_type, tx_hash, timestamp, payload_json, activity_fingerprint)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (row[0], row[1], row[2], row[3], row[4], row[5], row[6], fp),
        )
    conn.execute("DROP TABLE trades")
    conn.execute("ALTER TABLE trades_v2 RENAME TO trades")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_wallet_token ON trades(wallet_address, token_address, timestamp)")


def _migrate_history_meta(conn: sqlite3.Connection) -> None:
    cols = _columns(conn, "token_history_meta")
    if not cols:
        return
    additions = {
        "chain": "TEXT NOT NULL DEFAULT 'sol'",
        "bottom_complete": "INTEGER NOT NULL DEFAULT 0",
        "oldest_timestamp": "INTEGER",
        "newest_timestamp": "INTEGER",
        "last_sync_at": "INTEGER",
        "last_success_at": "INTEGER",
        "known_head_fingerprint": "TEXT",
        "page_count_total": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, decl in additions.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE token_history_meta ADD COLUMN {name} {decl}")
    if "history_complete" in _columns(conn, "token_history_meta"):
        conn.execute("UPDATE token_history_meta SET bottom_complete = history_complete WHERE bottom_complete=0 AND history_complete=1")
        conn.execute("UPDATE token_history_meta SET page_count_total = page_count WHERE page_count_total=0 AND page_count>0")


def _migrate_jobs(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )


def _migrate_wallet_identity(conn: sqlite3.Connection) -> None:
    cols = _columns(conn, "wallet_reports")
    if cols:
        if "job_id" not in cols:
            conn.execute("ALTER TABLE wallet_reports ADD COLUMN job_id TEXT")
        if "wallet_task_id" not in cols:
            conn.execute("ALTER TABLE wallet_reports ADD COLUMN wallet_task_id TEXT")
        conn.execute("UPDATE wallet_reports SET job_id = id WHERE job_id IS NULL OR job_id=''")
        conn.execute("UPDATE wallet_reports SET wallet_task_id = id WHERE wallet_task_id IS NULL OR wallet_task_id=''")
    task_cols = _columns(conn, "task_runs")
    if task_cols and "job_id" not in task_cols:
        conn.execute("ALTER TABLE task_runs ADD COLUMN job_id TEXT")
    if task_cols and "wallet_task_id" not in task_cols:
        conn.execute("ALTER TABLE task_runs ADD COLUMN wallet_task_id TEXT")
        conn.execute("UPDATE task_runs SET wallet_task_id = task_id WHERE wallet_task_id IS NULL OR wallet_task_id=''")


def _migrate_v4_provider_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_cache (
            cache_key TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            capability TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
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
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS token_metadata_cache (
            mint TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            fetched_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS token_market_cache (
            mint TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            fetched_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mint_creation_cache (
            mint TEXT PRIMARY KEY,
            creation_signature TEXT,
            creation_time INTEGER,
            slot INTEGER,
            source TEXT,
            verified INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT,
            fetched_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pool_cache (
            mint TEXT NOT NULL,
            pair_address TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            fetched_at INTEGER NOT NULL,
            PRIMARY KEY(mint, pair_address)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_metrics (
            job_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            PRIMARY KEY(job_id, provider)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS verified_transactions (
            signature TEXT PRIMARY KEY,
            wallet_address TEXT,
            token_address TEXT,
            payload_json TEXT NOT NULL,
            fetched_at INTEGER NOT NULL
        )
        """
    )


def _migrate_v5_helius_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS helius_capabilities (
            provider TEXT NOT NULL,
            capability TEXT NOT NULL,
            status TEXT NOT NULL,
            checked_at INTEGER NOT NULL,
            message TEXT,
            PRIMARY KEY(provider, capability)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_history_state (
            wallet TEXT NOT NULL,
            provider TEXT NOT NULL,
            bottom_complete INTEGER NOT NULL DEFAULT 0,
            oldest_signature TEXT,
            oldest_block_time INTEGER,
            newest_signature TEXT,
            newest_block_time INTEGER,
            last_sync_at INTEGER NOT NULL,
            PRIMARY KEY(wallet, provider)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS first_buy_cache (
            wallet TEXT NOT NULL,
            mint TEXT NOT NULL,
            signature TEXT,
            block_time INTEGER,
            amount TEXT,
            verified INTEGER NOT NULL DEFAULT 0,
            source TEXT,
            fetched_at INTEGER NOT NULL,
            PRIMARY KEY(wallet, mint)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS helius_credit_usage (
            month TEXT PRIMARY KEY,
            estimated_credits INTEGER NOT NULL DEFAULT 0,
            unpriced_requests INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT,
            updated_at INTEGER NOT NULL
        )
        """
    )


def _migrate_v52_history_events(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wallet_history_events (
            wallet TEXT NOT NULL,
            signature TEXT NOT NULL,
            event_index INTEGER NOT NULL DEFAULT 0,
            timestamp INTEGER,
            event_type TEXT,
            mint TEXT,
            token_amount TEXT,
            quote_mint TEXT,
            quote_symbol TEXT,
            quote_amount TEXT,
            usd_amount TEXT,
            usd_price TEXT,
            provider TEXT NOT NULL,
            fingerprint TEXT,
            raw_reference TEXT,
            payload_json TEXT,
            PRIMARY KEY(wallet, signature, event_index, provider)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wallet_history_events_wallet ON wallet_history_events(wallet, provider, timestamp)"
    )
