from __future__ import annotations

import threading
from typing import Callable, Optional

from app.api.exceptions import AnalysisCancelledError, GMGNError
from app.api.gmgn_client import GMGNClient
from app.api.parsers import parse_activity_item, parse_activity_page
from app.domain.models import TradeRecord
from app.storage.repositories import Repositories
from app.utils.logger import get_logger

logger = get_logger("gmgn.collector")

ProgressFn = Callable[[str], None]


class ActivityCollector:
    def __init__(self, client: GMGNClient, repos: Optional[Repositories] = None, cancel_event: Optional[threading.Event] = None):
        self.client = client
        self.repos = repos
        self.cancel_event = cancel_event
        self.page_count = 0
        self._page_lock = threading.Lock()

    def _check(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise AnalysisCancelledError()

    def _bump_pages(self) -> None:
        with self._page_lock:
            self.page_count += 1

    def collect_report_window(
        self,
        chain: str,
        wallet: str,
        start_ts: int,
        end_ts: int,
        max_transactions: int,
        on_progress: Optional[ProgressFn] = None,
    ) -> tuple[list[TradeRecord], int, bool]:
        """分页直到时间早于 start_ts 或 next 为空。max_transactions 只限制报告范围交易。"""
        trades: list[TradeRecord] = []
        cursor = None
        pages = 0
        truncated = False
        seen: set[str] = set()
        while True:
            self._check()
            if on_progress:
                on_progress(f"采集钱包流水 第 {pages + 1} 页")
            payload = self.client.get_wallet_activity(chain, wallet, cursor=cursor, limit=50)
            page_trades, nxt = parse_activity_page(payload, wallet, chain)
            pages += 1
            self._bump_pages()
            if not page_trades:
                break
            stop = False
            for trade in page_trades:
                key = trade.activity_fingerprint or f"{trade.tx_hash}:{trade.token_address}:{trade.event_type.value}:{trade.token_amount}"
                if key in seen:
                    continue
                seen.add(key)
                if start_ts and trade.timestamp and trade.timestamp < start_ts:
                    stop = True
                    continue
                if end_ts and trade.timestamp and trade.timestamp > end_ts:
                    continue
                trade.in_report_range = True
                trades.append(trade)
                self._persist(trade)
                if 0 < max_transactions <= len(trades):
                    truncated = True
                    stop = True
                    break
            if stop or not nxt:
                break
            cursor = nxt
        return trades, pages, truncated

    def collect_token_history(
        self,
        chain: str,
        wallet: str,
        token_address: str,
        on_progress: Optional[ProgressFn] = None,
        use_cache: bool = True,
    ) -> tuple[list[TradeRecord], int, bool]:
        state = self.repos.get_history_sync(wallet, token_address, chain) if (use_cache and self.repos) else None
        bottom_complete = bool(state and state.get("bottom_complete"))
        known_fps = self.repos.known_fingerprints(wallet, token_address) if (use_cache and self.repos) else set()

        if bottom_complete:
            new_trades, pages, hit_known = self._incremental_head(
                chain, wallet, token_address, known_fps, on_progress
            )
            cached = self._load_cached(wallet, token_address, chain)
            merged = self._merge(cached, new_trades)
            newest = max((t.timestamp for t in merged if t.timestamp), default=None)
            oldest = min((t.timestamp for t in merged if t.timestamp), default=None)
            head = ""
            if merged:
                head_trade = max(merged, key=lambda t: (t.timestamp, t.activity_fingerprint))
                head = head_trade.activity_fingerprint
            if self.repos:
                self.repos.save_history_sync(
                    wallet,
                    token_address,
                    chain=chain,
                    bottom_complete=True,
                    oldest_timestamp=oldest,
                    newest_timestamp=newest,
                    known_head_fingerprint=head,
                    page_count=pages,
                )
            logger.info("增量同步 token=%s new=%s pages=%s cached=%s hit_known=%s", token_address[:8], len(new_trades), pages, len(cached), hit_known)
            return merged, pages, True

        trades, pages, complete = self._full_history(chain, wallet, token_address, on_progress)
        newest = max((t.timestamp for t in trades if t.timestamp), default=None)
        oldest = min((t.timestamp for t in trades if t.timestamp), default=None)
        head = ""
        if trades:
            head_trade = max(trades, key=lambda t: (t.timestamp, t.activity_fingerprint))
            head = head_trade.activity_fingerprint
        if self.repos and complete:
            self.repos.save_history_sync(
                wallet,
                token_address,
                chain=chain,
                bottom_complete=True,
                oldest_timestamp=oldest,
                newest_timestamp=newest,
                known_head_fingerprint=head,
                page_count=pages,
            )
        return trades, pages, complete

    def _full_history(
        self,
        chain: str,
        wallet: str,
        token_address: str,
        on_progress: Optional[ProgressFn],
    ) -> tuple[list[TradeRecord], int, bool]:
        trades: list[TradeRecord] = []
        cursor = None
        pages = 0
        seen: set[str] = set()
        while True:
            self._check()
            if on_progress:
                on_progress(f"追溯 {token_address[:6]} 完整历史 第 {pages + 1} 页")
            payload = self.client.get_wallet_activity(
                chain,
                wallet,
                token_address=token_address,
                cursor=cursor,
                limit=50,
            )
            page_trades, nxt = parse_activity_page(payload, wallet, chain)
            pages += 1
            self._bump_pages()
            for trade in page_trades:
                key = trade.activity_fingerprint
                if key in seen:
                    continue
                seen.add(key)
                trade.history_only = True
                trades.append(trade)
                self._persist(trade)
            if not nxt:
                break
            cursor = nxt
        return trades, pages, True

    def _incremental_head(
        self,
        chain: str,
        wallet: str,
        token_address: str,
        known_fps: set[str],
        on_progress: Optional[ProgressFn],
    ) -> tuple[list[TradeRecord], int, bool]:
        """从最新页向后扫到已知交易 / next=null。不重翻历史底部。"""
        trades: list[TradeRecord] = []
        cursor = None
        pages = 0
        hit_known = False
        seen: set[str] = set()
        while True:
            self._check()
            if on_progress:
                on_progress(f"增量同步 {token_address[:6]} 第 {pages + 1} 页")
            payload = self.client.get_wallet_activity(
                chain,
                wallet,
                token_address=token_address,
                cursor=cursor,
                limit=50,
            )
            page_trades, nxt = parse_activity_page(payload, wallet, chain)
            pages += 1
            self._bump_pages()
            if not page_trades and not nxt:
                break
            for trade in page_trades:
                key = trade.activity_fingerprint
                if key in seen:
                    continue
                seen.add(key)
                if key in known_fps:
                    hit_known = True
                    continue
                trade.history_only = True
                trades.append(trade)
                self._persist(trade)
            if hit_known or not nxt:
                break
            cursor = nxt
        return trades, pages, hit_known

    def _load_cached(self, wallet: str, token_address: str, chain: str) -> list[TradeRecord]:
        if not self.repos:
            return []
        cached = self.repos.list_token_trades(wallet, token_address)
        trades: list[TradeRecord] = []
        for item in cached:
            parsed = parse_activity_item(item, wallet, chain)
            if parsed:
                parsed.history_only = True
                trades.append(parsed)
        return trades

    def _merge(self, cached: list[TradeRecord], incoming: list[TradeRecord]) -> list[TradeRecord]:
        by_fp: dict[str, TradeRecord] = {}
        for trade in cached + incoming:
            by_fp[trade.activity_fingerprint] = trade
        return list(by_fp.values())

    def _persist(self, trade: TradeRecord) -> None:
        if not self.repos:
            return
        payload = dict(trade.raw or {})
        payload["activity_fingerprint"] = trade.activity_fingerprint
        self.repos.upsert_trade(
            trade.wallet_address,
            trade.chain,
            trade.token_address,
            trade.event_type.value,
            trade.tx_hash,
            trade.timestamp,
            payload,
            fingerprint=trade.activity_fingerprint,
        )
