from __future__ import annotations

from typing import Any, Optional

from app.storage.database import Database
from app.utils.time_utils import now_ts


class Repositories:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert_trade(
        self,
        wallet: str,
        chain: str,
        token: str,
        event_type: str,
        tx_hash: str,
        timestamp: int,
        payload: dict[str, Any],
        fingerprint: str = "",
    ) -> None:
        from app.domain.fingerprint import activity_fingerprint

        fp = fingerprint or payload.get("activity_fingerprint") or activity_fingerprint(chain, wallet, payload)
        self.db.execute(
            """
            INSERT INTO trades(wallet_address, chain, token_address, event_type, tx_hash, timestamp, payload_json, activity_fingerprint)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(activity_fingerprint)
            DO UPDATE SET timestamp=excluded.timestamp, payload_json=excluded.payload_json
            """,
            (wallet, chain, token, event_type, tx_hash, timestamp, self.db.dumps(payload), fp),
        )

    def known_fingerprints(self, wallet: str, token: str) -> set[str]:
        rows = self.db.query(
            "SELECT activity_fingerprint FROM trades WHERE wallet_address=? AND token_address=?",
            (wallet, token),
        )
        return {str(r["activity_fingerprint"]) for r in rows if r["activity_fingerprint"]}

    def list_token_trades(self, wallet: str, token: str) -> list[dict[str, Any]]:
        import json

        rows = self.db.query(
            "SELECT payload_json FROM trades WHERE wallet_address=? AND token_address=? ORDER BY timestamp ASC",
            (wallet, token),
        )
        return [json.loads(row["payload_json"]) for row in rows]

    def set_history_complete(self, wallet: str, token: str, page_count: int) -> None:
        self.save_history_sync(
            wallet,
            token,
            chain="sol",
            bottom_complete=True,
            page_count=page_count,
        )

    def is_history_complete(self, wallet: str, token: str) -> bool:
        state = self.get_history_sync(wallet, token)
        return bool(state and state.get("bottom_complete"))

    def get_history_sync(self, wallet: str, token: str, chain: str = "sol") -> Optional[dict[str, Any]]:
        rows = self.db.query(
            """
            SELECT wallet_address, token_address, chain, bottom_complete, history_complete,
                   oldest_timestamp, newest_timestamp, last_sync_at, last_success_at,
                   known_head_fingerprint, page_count, page_count_total
            FROM token_history_meta WHERE wallet_address=? AND token_address=?
            """,
            (wallet, token),
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["bottom_complete"] = bool(row.get("bottom_complete") or row.get("history_complete"))
        return row

    def save_history_sync(
        self,
        wallet: str,
        token: str,
        *,
        chain: str = "sol",
        bottom_complete: bool = False,
        oldest_timestamp: int | None = None,
        newest_timestamp: int | None = None,
        known_head_fingerprint: str | None = None,
        page_count: int = 0,
    ) -> None:
        now = now_ts()
        prev = self.get_history_sync(wallet, token, chain)
        old_pages = int((prev or {}).get("page_count_total") or (prev or {}).get("page_count") or 0)
        old_oldest = (prev or {}).get("oldest_timestamp")
        old_newest = (prev or {}).get("newest_timestamp")
        oldest = oldest_timestamp if old_oldest in (None, 0) else min(int(old_oldest), int(oldest_timestamp or old_oldest))
        newest = newest_timestamp if old_newest in (None, 0) else max(int(old_newest), int(newest_timestamp or old_newest))
        done = 1 if (bottom_complete or (prev or {}).get("bottom_complete")) else 0
        head = known_head_fingerprint or (prev or {}).get("known_head_fingerprint")
        total_pages = old_pages + int(page_count or 0)
        self.db.execute(
            """
            INSERT INTO token_history_meta(
                wallet_address, token_address, history_complete, page_count, updated_at, chain,
                bottom_complete, oldest_timestamp, newest_timestamp, last_sync_at, last_success_at,
                known_head_fingerprint, page_count_total
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(wallet_address, token_address) DO UPDATE SET
                history_complete=excluded.history_complete,
                page_count=excluded.page_count,
                page_count_total=excluded.page_count_total,
                updated_at=excluded.updated_at,
                chain=excluded.chain,
                bottom_complete=excluded.bottom_complete,
                oldest_timestamp=excluded.oldest_timestamp,
                newest_timestamp=excluded.newest_timestamp,
                last_sync_at=excluded.last_sync_at,
                last_success_at=excluded.last_success_at,
                known_head_fingerprint=excluded.known_head_fingerprint
            """,
            (
                wallet,
                token,
                done,
                total_pages,
                now,
                chain,
                done,
                oldest,
                newest,
                now,
                now,
                head,
                total_pages,
            ),
        )

    def save_job(
        self,
        job_id: str,
        wallets: list[str],
        job_type: str,
        status: str,
        summary: dict[str, Any],
        excel_path: str,
        elapsed: float,
        api_requests: int = 0,
        cache_hits: int = 0,
    ) -> None:
        import json as json_mod

        self.db.execute(
            """
            INSERT INTO analysis_jobs(job_id, wallets_json, wallet_count, job_type, status, summary_json, excel_path, created_at, elapsed_seconds, api_requests, cache_hits)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                status=excluded.status, summary_json=excluded.summary_json, excel_path=excluded.excel_path,
                elapsed_seconds=excluded.elapsed_seconds, api_requests=excluded.api_requests, cache_hits=excluded.cache_hits
            """,
            (
                job_id,
                json_mod.dumps(wallets, ensure_ascii=False),
                len(wallets),
                job_type,
                status,
                self.db.dumps(summary),
                excel_path,
                now_ts(),
                elapsed,
                api_requests,
                cache_hits,
            ),
        )
        self.db.execute(
            """
            INSERT INTO jobs(job_id, created_at, state, wallet_count, job_type, summary_json, excel_path, elapsed_seconds, api_requests, cache_hits)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
                state=excluded.state, summary_json=excluded.summary_json, excel_path=excluded.excel_path,
                elapsed_seconds=excluded.elapsed_seconds, api_requests=excluded.api_requests, cache_hits=excluded.cache_hits, wallet_count=excluded.wallet_count
            """,
            (
                job_id,
                now_ts(),
                status,
                len(wallets),
                job_type,
                self.db.dumps(summary),
                excel_path,
                elapsed,
                api_requests,
                cache_hits,
            ),
        )

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        import json as json_mod

        rows = self.db.query("SELECT * FROM analysis_jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        result = []
        for row in rows:
            item = dict(row)
            item["wallets"] = json_mod.loads(row["wallets_json"]) if row["wallets_json"] else []
            item["summary"] = json_mod.loads(row["summary_json"]) if row["summary_json"] else {}
            result.append(item)
        return result

    def delete_job(self, job_id: str) -> None:
        if not job_id:
            return
        self.db.execute("DELETE FROM analysis_jobs WHERE job_id=?", (job_id,))
        self.db.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
        self.db.execute("DELETE FROM wallet_tasks WHERE job_id=?", (job_id,))

    def save_token_info(self, chain: str, token: str, payload: dict[str, Any]) -> None:
        self.db.execute(
            """
            INSERT INTO token_info_cache(chain, token_address, payload_json, fetched_at)
            VALUES(?,?,?,?)
            ON CONFLICT(chain, token_address)
            DO UPDATE SET payload_json=excluded.payload_json, fetched_at=excluded.fetched_at
            """,
            (chain, token, self.db.dumps(payload), now_ts()),
        )

    def get_token_info(self, chain: str, token: str, ttl: int) -> Optional[dict[str, Any]]:
        import json

        rows = self.db.query(
            "SELECT payload_json, fetched_at FROM token_info_cache WHERE chain=? AND token_address=?",
            (chain, token),
        )
        if not rows:
            return None
        if now_ts() - int(rows[0]["fetched_at"]) > ttl:
            return None
        return json.loads(rows[0]["payload_json"])

    def save_pool(self, chain: str, token: str, payload: dict[str, Any]) -> None:
        self.db.execute(
            """
            INSERT INTO token_pool_cache(chain, token_address, payload_json, fetched_at)
            VALUES(?,?,?,?)
            ON CONFLICT(chain, token_address)
            DO UPDATE SET payload_json=excluded.payload_json, fetched_at=excluded.fetched_at
            """,
            (chain, token, self.db.dumps(payload), now_ts()),
        )

    def get_pool(self, chain: str, token: str, ttl: int) -> Optional[dict[str, Any]]:
        import json

        rows = self.db.query(
            "SELECT payload_json, fetched_at FROM token_pool_cache WHERE chain=? AND token_address=?",
            (chain, token),
        )
        if not rows:
            return None
        if now_ts() - int(rows[0]["fetched_at"]) > ttl:
            return None
        return json.loads(rows[0]["payload_json"])

    def save_api_cache(self, key: str, payload: Any, ttl: int) -> None:
        self.db.execute(
            """
            INSERT INTO api_cache(cache_key, payload_json, fetched_at, ttl_seconds)
            VALUES(?,?,?,?)
            ON CONFLICT(cache_key)
            DO UPDATE SET payload_json=excluded.payload_json, fetched_at=excluded.fetched_at, ttl_seconds=excluded.ttl_seconds
            """,
            (key, self.db.dumps(payload), now_ts(), ttl),
        )

    def get_api_cache(self, key: str) -> Optional[Any]:
        import json

        rows = self.db.query("SELECT payload_json, fetched_at, ttl_seconds FROM api_cache WHERE cache_key=?", (key,))
        if not rows:
            return None
        if now_ts() - int(rows[0]["fetched_at"]) > int(rows[0]["ttl_seconds"]):
            return None
        return json.loads(rows[0]["payload_json"]        )

    def save_wallet_task(
        self,
        wallet_task_id: str,
        job_id: str,
        wallet: str,
        state: str,
        **fields: Any,
    ) -> None:
        now = now_ts()
        existing = self.db.query("SELECT wallet_task_id FROM wallet_tasks WHERE wallet_task_id=?", (wallet_task_id,))
        if not existing:
            self.db.execute(
                """
                INSERT INTO wallet_tasks(
                    wallet_task_id, job_id, wallet_address, state, progress, current_stage,
                    token_total, token_completed, started_at, finished_at, error,
                    api_requests, cache_hits, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    wallet_task_id,
                    job_id,
                    wallet,
                    state,
                    fields.get("progress", 0),
                    fields.get("current_stage"),
                    fields.get("token_total", 0),
                    fields.get("token_completed", 0),
                    fields.get("started_at"),
                    fields.get("finished_at"),
                    fields.get("error"),
                    fields.get("api_requests", 0),
                    fields.get("cache_hits", 0),
                    now,
                    now,
                ),
            )
            return
        sets = ["state=?", "updated_at=?"]
        params: list[Any] = [state, now]
        for key in (
            "progress",
            "current_stage",
            "token_total",
            "token_completed",
            "started_at",
            "finished_at",
            "error",
            "api_requests",
            "cache_hits",
        ):
            if key in fields:
                sets.append(f"{key}=?")
                params.append(fields[key])
        params.append(wallet_task_id)
        self.db.execute(f"UPDATE wallet_tasks SET {', '.join(sets)} WHERE wallet_task_id=?", tuple(params))

    def list_wallet_tasks(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM wallet_tasks WHERE job_id=? ORDER BY created_at ASC", (job_id,))
        return [dict(r) for r in rows]

    def upsert_task(self, task_id: str, wallet: str, status: str, **fields: Any) -> None:
        now = now_ts()
        existing = self.db.query("SELECT task_id FROM task_runs WHERE task_id=?", (task_id,))
        if not existing:
            self.db.execute(
                """
                INSERT INTO task_runs(task_id, wallet_address, status, current_token, progress_done, progress_total, error, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    wallet,
                    status,
                    fields.get("current_token"),
                    fields.get("progress_done", 0),
                    fields.get("progress_total", 0),
                    fields.get("error"),
                    now,
                    now,
                ),
            )
            return
        sets = ["status=?", "updated_at=?"]
        params: list[Any] = [status, now]
        for key in ("current_token", "progress_done", "progress_total", "error"):
            if key in fields:
                sets.append(f"{key}=?")
                params.append(fields[key])
        params.append(task_id)
        self.db.execute(f"UPDATE task_runs SET {', '.join(sets)} WHERE task_id=?", tuple(params))

    def save_token_result(self, task_id: str, wallet: str, token: str, status: str, payload: dict[str, Any]) -> None:
        self.db.execute(
            """
            INSERT INTO analysis_results(task_id, wallet_address, token_address, status, payload_json, updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(task_id, wallet_address, token_address)
            DO UPDATE SET status=excluded.status, payload_json=excluded.payload_json, updated_at=excluded.updated_at
            """,
            (task_id, wallet, token, status, self.db.dumps(payload), now_ts()),
        )

    def list_token_results(self, task_id: str) -> list[dict[str, Any]]:
        import json

        rows = self.db.query(
            "SELECT token_address, status, payload_json FROM analysis_results WHERE task_id=?",
            (task_id,),
        )
        return [{"token_address": r["token_address"], "status": r["status"], "payload": json.loads(r["payload_json"])} for r in rows]

    def save_report(
        self,
        report_id: str,
        wallet: str,
        chain: str,
        period: str,
        start: int,
        end: int,
        status: str,
        summary: dict[str, Any],
        excel_path: str,
        json_path: str,
        elapsed: float,
        job_id: str = "",
        wallet_task_id: str = "",
    ) -> None:
        self.db.execute(
            """
            INSERT INTO wallet_reports(id, wallet_address, chain, period, start_time, end_time, status, summary_json, excel_path, json_path, created_at, elapsed_seconds, job_id, wallet_task_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET status=excluded.status, summary_json=excluded.summary_json, excel_path=excluded.excel_path, json_path=excluded.json_path, elapsed_seconds=excluded.elapsed_seconds, job_id=excluded.job_id, wallet_task_id=excluded.wallet_task_id
            """,
            (
                report_id,
                wallet,
                chain,
                period,
                start,
                end,
                status,
                self.db.dumps(summary),
                excel_path,
                json_path,
                now_ts(),
                elapsed,
                job_id or report_id,
                wallet_task_id or report_id,
            ),
        )

    def list_reports(self, limit: int = 100) -> list[dict[str, Any]]:
        import json

        rows = self.db.query("SELECT * FROM wallet_reports ORDER BY created_at DESC LIMIT ?", (limit,))
        result = []
        for row in rows:
            item = dict(row)
            item["summary"] = json.loads(row["summary_json"]) if row["summary_json"] else {}
            result.append(item)
        return result

    def delete_report(self, report_id: str) -> None:
        if not report_id:
            return
        self.db.execute("DELETE FROM wallet_reports WHERE id=?", (report_id,))

    def get_provider_cache(self, key: str) -> Optional[Any]:
        import json

        rows = self.db.query(
            "SELECT payload_json, expires_at FROM provider_cache WHERE cache_key=?",
            (key,),
        )
        if not rows:
            return None
        if int(rows[0]["expires_at"] or 0) < now_ts():
            return None
        raw = rows[0]["payload_json"]
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def save_provider_cache(self, provider: str, capability: str, key: str, payload: Any, ttl: int) -> None:
        now = now_ts()
        expires = now + max(1, int(ttl))
        if ttl >= 10 * 365 * 24 * 3600:
            expires = now + ttl
        self.db.execute(
            """
            INSERT INTO provider_cache(cache_key, provider, capability, payload_json, created_at, expires_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload_json=excluded.payload_json, created_at=excluded.created_at, expires_at=excluded.expires_at,
                provider=excluded.provider, capability=excluded.capability
            """,
            (key, provider, capability, self.db.dumps(payload), now, expires),
        )

    def save_evidence(
        self,
        job_id: str,
        wallet: str,
        token: str,
        field_name: str,
        provider: str,
        raw_value: Any,
        normalized_value: Any,
        reference: str,
        confidence: float,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO evidence(job_id, wallet_address, token_address, field_name, provider, raw_value, normalized_value, reference, confidence, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job_id,
                wallet,
                token,
                field_name,
                provider,
                self.db.dumps(raw_value),
                self.db.dumps(normalized_value),
                reference,
                confidence,
                now_ts(),
            ),
        )

    def save_resolved_field(
        self,
        job_id: str,
        wallet: str,
        token: str,
        field_name: str,
        value: Any,
        status: str,
        primary_source: str,
        confidence: float,
        estimated: bool,
        note: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO resolved_fields(job_id, wallet, token, field_name, value, status, primary_source, confidence, estimated, note)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id, wallet, token, field_name) DO UPDATE SET
                value=excluded.value, status=excluded.status, primary_source=excluded.primary_source,
                confidence=excluded.confidence, estimated=excluded.estimated, note=excluded.note
            """,
            (
                job_id,
                wallet,
                token,
                field_name,
                self.db.dumps(value),
                status,
                primary_source,
                confidence,
                1 if estimated else 0,
                note,
            ),
        )

    def get_helius_capabilities(self, ttl: int = 3600) -> dict[str, str] | None:
        rows = self.db.query("SELECT capability, status, checked_at FROM helius_capabilities WHERE provider=?", ("helius",))
        if not rows:
            return None
        newest = max(int(r["checked_at"] or 0) for r in rows)
        if newest and now_ts() - newest > ttl:
            return None
        return {str(r["capability"]): str(r["status"]) for r in rows}

    def save_helius_capabilities(self, result: dict[str, str], message: str = "") -> None:
        now = now_ts()
        for name, status in result.items():
            self.db.execute(
                """
                INSERT INTO helius_capabilities(provider, capability, status, checked_at, message)
                VALUES(?,?,?,?,?)
                ON CONFLICT(provider, capability) DO UPDATE SET
                    status=excluded.status, checked_at=excluded.checked_at, message=excluded.message
                """,
                ("helius", name, status, now, message),
            )

    def get_wallet_history_state(self, wallet: str, provider: str = "helius") -> dict[str, Any] | None:
        rows = self.db.query(
            "SELECT * FROM wallet_history_state WHERE wallet=? AND provider=?",
            (wallet, provider),
        )
        return dict(rows[0]) if rows else None

    def save_wallet_history_state(
        self,
        wallet: str,
        provider: str,
        *,
        bottom_complete: bool,
        oldest_signature: str,
        oldest_block_time: int,
        newest_signature: str,
        newest_block_time: int,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO wallet_history_state(wallet, provider, bottom_complete, oldest_signature, oldest_block_time, newest_signature, newest_block_time, last_sync_at)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(wallet, provider) DO UPDATE SET
                bottom_complete=excluded.bottom_complete,
                oldest_signature=excluded.oldest_signature,
                oldest_block_time=excluded.oldest_block_time,
                newest_signature=excluded.newest_signature,
                newest_block_time=excluded.newest_block_time,
                last_sync_at=excluded.last_sync_at
            """,
            (
                wallet,
                provider,
                1 if bottom_complete else 0,
                oldest_signature,
                oldest_block_time,
                newest_signature,
                newest_block_time,
                now_ts(),
            ),
        )

    def get_helius_credit_usage(self) -> dict[str, Any] | None:
        import json
        from datetime import datetime, timezone

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        rows = self.db.query("SELECT * FROM helius_credit_usage WHERE month=?", (month,))
        if not rows:
            return None
        payload = json.loads(rows[0]["payload_json"] or "{}") if rows[0]["payload_json"] else {}
        payload["estimated_credits"] = rows[0]["estimated_credits"]
        payload["unpriced_requests"] = rows[0]["unpriced_requests"]
        return payload

    def save_helius_credit_usage(self, snapshot: dict[str, Any]) -> None:
        from datetime import datetime, timezone

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        self.db.execute(
            """
            INSERT INTO helius_credit_usage(month, estimated_credits, unpriced_requests, payload_json, updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(month) DO UPDATE SET
                estimated_credits=excluded.estimated_credits,
                unpriced_requests=excluded.unpriced_requests,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
            """,
            (
                month,
                int(snapshot.get("estimated_credits") or 0),
                int(snapshot.get("unpriced_requests") or 0),
                self.db.dumps(snapshot),
                now_ts(),
            ),
        )

    def load_wallet_history_events(self, wallet: str, provider: str) -> list[dict[str, Any]]:
        try:
            rows = self.db.query(
                "SELECT * FROM wallet_history_events WHERE wallet=? AND provider=? ORDER BY timestamp DESC",
                (wallet, provider),
            )
        except Exception:
            return []
        out = []
        for row in rows:
            item = dict(row)
            raw = item.get("payload_json")
            if raw:
                try:
                    import json

                    payload = json.loads(raw)
                    if isinstance(payload, dict):
                        item["payload"] = payload
                except Exception:
                    item["payload"] = {}
            out.append(item)
        return out

    def save_wallet_history_events(self, wallet: str, provider: str, events: list[dict[str, Any]]) -> None:
        import json

        for event in events:
            payload = {k: v for k, v in event.items() if k.startswith("_") or k in {"event_type"}}
            self.db.execute(
                """
                INSERT INTO wallet_history_events(
                    wallet, signature, event_index, timestamp, event_type, mint, token_amount,
                    quote_mint, quote_symbol, quote_amount, usd_amount, usd_price, provider,
                    fingerprint, raw_reference, payload_json
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(wallet, signature, event_index, provider) DO UPDATE SET
                    timestamp=excluded.timestamp,
                    event_type=excluded.event_type,
                    mint=excluded.mint,
                    token_amount=excluded.token_amount,
                    quote_mint=excluded.quote_mint,
                    quote_symbol=excluded.quote_symbol,
                    quote_amount=excluded.quote_amount,
                    usd_amount=excluded.usd_amount,
                    usd_price=excluded.usd_price,
                    fingerprint=excluded.fingerprint,
                    payload_json=excluded.payload_json
                """,
                (
                    wallet,
                    event.get("signature") or "",
                    int(event.get("event_index") or 0),
                    int(event.get("timestamp") or 0),
                    event.get("event_type") or "",
                    event.get("mint") or "",
                    event.get("token_amount") or "",
                    event.get("quote_mint") or "",
                    event.get("quote_symbol") or "",
                    event.get("quote_amount") or "",
                    event.get("usd_amount") or "",
                    event.get("usd_price") or "",
                    provider,
                    event.get("fingerprint") or "",
                    event.get("raw_reference") or "",
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
            )
