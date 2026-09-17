from __future__ import annotations

import json
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

from app.api.exceptions import AnalysisCancelledError, GMGNError, GMGNRateLimitError
from app.api.gmgn_client import GMGNClient
from app.api.parsers import parse_wallet_profits, parse_wallet_stats
from app.domain.enums import (
    AcquisitionType,
    EventType,
    FieldStatus,
    ReportPeriod,
    TaskStatus,
    TokenPositionStatus,
)
from app.domain.models import (
    AnalysisSummary,
    ApiStats,
    CollectionScope,
    GmgnProfit,
    GmgnWalletStats,
    TokenAnalysisResult,
    TradeRecord,
    WalletAnalysisRequest,
    WalletReport,
    error_value,
    known,
    missing,
    not_applicable,
)
from app.services.acquisition_resolver import resolve_acquisition
from app.services.activity_collector import ActivityCollector
from app.services.completeness_service import CompletenessService
from app.services.export_service import ExportService
from app.services.platform_resolver import resolve_platforms, resolve_source_platform
from app.services.pnl_service import apply_fifo
from app.services.token_enricher import TokenEnricher
from app.storage.cache import CacheService
from app.storage.database import Database
from app.storage.repositories import Repositories
from app.utils.logger import get_logger
from app.utils.money import to_decimal
from app.utils.paths import RAW_DIR
from app.utils.time_utils import format_datetime, gmgn_profit_period, gmgn_stats_period, now_ts
from app.version import __version__
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

logger = get_logger("gmgn.analysis")
ProgressCb = Callable[[dict], None]


class WalletAnalysisService:
    def __init__(
        self,
        client: GMGNClient,
        db: Optional[Database] = None,
        cancel_event: Optional[threading.Event] = None,
        on_progress: Optional[ProgressCb] = None,
        token_ttl: int = 43200,
        pool_ttl: int = 1800,
        token_workers: int = 4,
    ) -> None:
        self.client = client
        self.db = db or Database()
        self.repos = Repositories(self.db)
        self.cache = CacheService(self.repos, token_ttl, pool_ttl)
        self.cancel_event = cancel_event
        self.on_progress = on_progress
        self.collector = ActivityCollector(client, self.repos, cancel_event)
        self.enricher = TokenEnricher(client, self.cache)
        self.completeness = CompletenessService()
        self.exporter = ExportService()
        self.token_workers = max(1, min(8, int(token_workers)))
        self._progress_lock = threading.Lock()

    def analyze(self, request: WalletAnalysisRequest) -> WalletReport:
        started = time.time()
        job_id = request.job_id or request.task_id or str(uuid.uuid4())
        wallet_task_id = request.wallet_task_id or f"{job_id}:{request.wallet_address}"
        request.job_id = job_id
        request.wallet_task_id = wallet_task_id
        request.task_id = wallet_task_id
        task_id = wallet_task_id
        raw_dir = RAW_DIR / job_id / request.wallet_address[:16]
        raw_paths: list[str] = []
        raw_lock = threading.Lock()
        if request.options.save_raw_json:
            raw_dir.mkdir(parents=True, exist_ok=True)

            def on_raw(path: str, payload: dict) -> None:
                from app.storage.raw_dump import write_raw_json

                file = write_raw_json(job_id, request.wallet_address, path, payload)
                with raw_lock:
                    raw_paths.append(str(file))

            if self.client.on_raw is None:
                self.client.on_raw = on_raw

        self.repos.upsert_task(task_id, request.wallet_address, TaskStatus.RUNNING.value)
        self.repos.save_wallet_task(wallet_task_id, job_id, request.wallet_address, TaskStatus.RUNNING.value, current_stage="wallet_stats")
        self._progress("wallet_stats", "获取钱包统计", 0, 0, request.wallet_address, "")
        stats = self._load_stats(request)
        profit = self._load_profit(request)

        self._progress("activity", "采集报告周期交易", 0, 0, request.wallet_address, "")
        report_trades, pages, truncated = self.collector.collect_report_window(
            request.chain,
            request.wallet_address,
            request.start_time,
            request.end_time,
            request.max_transactions,
            on_progress=lambda msg: self._progress("activity", msg, 0, 0, request.wallet_address, ""),
        )
        token_ids = self._token_ids(report_trades)
        self.repos.upsert_task(task_id, request.wallet_address, TaskStatus.RUNNING.value, progress_total=len(token_ids))
        self.repos.save_wallet_task(
            wallet_task_id, job_id, request.wallet_address, TaskStatus.RUNNING.value, token_total=len(token_ids), current_stage="tokens"
        )
        logger.info("获取周期 Token：%s workers=%s", len(token_ids), self.token_workers)

        token_results: list[TokenAnalysisResult] = []
        all_trades: list[TradeRecord] = []
        warnings = []
        failed = 0
        done = 0
        result_map: dict[str, tuple[TokenAnalysisResult, list[TradeRecord]]] = {}
        max_pending = min(16, max(self.token_workers * 2, 4))
        with ThreadPoolExecutor(max_workers=self.token_workers, thread_name_prefix="gmgn-token") as pool:
            pending: set = set()
            fut_token: dict = {}
            iterator = iter(token_ids)

            def submit_one() -> bool:
                try:
                    token_address = next(iterator)
                except StopIteration:
                    return False
                fut = pool.submit(self._analyze_token, request, token_address, report_trades)
                pending.add(fut)
                fut_token[fut] = token_address
                return True

            for _ in range(min(max_pending, len(token_ids) or 0)):
                if not submit_one():
                    break
            while pending:
                self._check_cancel()
                finished, pending = wait(pending, timeout=0.15, return_when=FIRST_COMPLETED)
                if not finished:
                    continue
                for fut in finished:
                    token_address = fut_token.pop(fut, "")
                    done += 1
                    symbol_hint = next((t.token_symbol for t in report_trades if t.token_address == token_address), token_address[:6])
                    self._progress("token", f"Token {done}/{len(token_ids)} {symbol_hint}", done, len(token_ids), request.wallet_address, token_address)
                    self.repos.upsert_task(
                        task_id,
                        request.wallet_address,
                        TaskStatus.RUNNING.value,
                        current_token=token_address,
                        progress_done=done,
                        progress_total=len(token_ids),
                    )
                    self.repos.save_wallet_task(
                        wallet_task_id,
                        job_id,
                        request.wallet_address,
                        TaskStatus.RUNNING.value,
                        token_completed=done,
                        token_total=len(token_ids),
                        current_stage="First Buy",
                    )
                    try:
                        result, history = fut.result()
                        if request.options.pumpfun_only and str(result.source_platform.value) != "Pump.fun":
                            submit_one()
                            continue
                        result_map[token_address] = (result, history)
                        self.repos.save_token_result(task_id, request.wallet_address, token_address, result.status.value, {"symbol": result.symbol, "status": result.status.value})
                    except AnalysisCancelledError:
                        pool.shutdown(wait=False, cancel_futures=True)
                        raise
                    except Exception as exc:
                        failed += 1
                        logger.exception("Token 失败 %s: %s", token_address, exc)
                        token_results.append(self._failed_token(request, token_address, symbol_hint, str(exc)))
                        self.repos.save_token_result(task_id, request.wallet_address, token_address, TaskStatus.FAILED.value, {"error": str(exc)})
                    submit_one()

        for token_address in token_ids:
            pair = result_map.get(token_address)
            if not pair:
                continue
            result, history = pair
            token_results.append(result)
            all_trades.extend(history)
            warnings.extend(self.completeness.collect_warnings(result))

        seen_fp = {t.activity_fingerprint for t in all_trades}
        for trade in report_trades:
            if trade.activity_fingerprint not in seen_fp:
                trade.in_report_range = True
                all_trades.append(trade)
                seen_fp.add(trade.activity_fingerprint)

        in_range_keys = {t.activity_fingerprint for t in report_trades}
        for trade in all_trades:
            in_window = True
            if request.start_time and trade.timestamp and trade.timestamp < request.start_time:
                in_window = False
            if request.end_time and trade.timestamp and trade.timestamp > request.end_time:
                in_window = False
            trade.in_report_range = trade.activity_fingerprint in in_range_keys or in_window

        timestamps = [t.timestamp for t in all_trades if t.timestamp and t.in_report_range]
        summary = self._summary(token_results, all_trades, profit)
        scope = CollectionScope(
            wallet_address=request.wallet_address,
            chain=request.chain,
            period=request.period.value,
            start_time=request.start_time,
            end_time=request.end_time,
            earliest_trade_ts=min(timestamps) if timestamps else None,
            latest_trade_ts=max(timestamps) if timestamps else None,
            report_trade_count=sum(1 for t in all_trades if t.in_report_range),
            history_trade_count=len(all_trades),
            api_pages=self.collector.page_count,
            token_count=len(token_results),
            truncated_by_max=truncated,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            version=__version__,
        )
        status = TaskStatus.SUCCESS
        if failed and token_results:
            status = TaskStatus.PARTIAL
        elif failed and not token_results:
            status = TaskStatus.FAILED
        report = WalletReport(
            request=request,
            tokens=token_results,
            trades=sorted(all_trades, key=lambda t: t.timestamp, reverse=True),
            warnings=warnings,
            summary=summary,
            scope=scope,
            api_stats=ApiStats(
                requests=self.client.request_count,
                cache_hits=self.cache.hits,
                cache_misses=self.cache.misses,
                retries_429=self.client.retry_429_count,
                errors=self.client.error_count + failed,
            ),
            gmgn_profit=profit,
            gmgn_stats=stats,
            raw_paths=raw_paths,
            elapsed_seconds=time.time() - started,
            status=status,
            task_id=task_id,
            job_id=job_id,
            wallet_task_id=wallet_task_id,
        )
        self.exporter.export(report)
        self.repos.save_report(
            wallet_task_id,
            request.wallet_address,
            request.chain,
            request.period.value,
            request.start_time,
            request.end_time,
            status.value,
            {
                "token_count": summary.token_count,
                "buy_count": summary.buy_count,
                "sell_count": summary.sell_count,
                "excel_path": report.excel_path,
                "json_path": report.json_path,
            },
            report.excel_path,
            report.json_path,
            report.elapsed_seconds,
            job_id=job_id,
            wallet_task_id=wallet_task_id,
        )
        self.repos.upsert_task(task_id, request.wallet_address, status.value, progress_done=done, progress_total=len(token_ids))
        self.repos.save_wallet_task(
            wallet_task_id,
            job_id,
            request.wallet_address,
            status.value,
            token_completed=done,
            token_total=len(token_ids),
            finished_at=time.time(),
        )
        logger.info("SUCCESS 分析完成 tokens=%s elapsed=%.1fs", len(token_results), report.elapsed_seconds)
        return report

    def _analyze_token(self, request: WalletAnalysisRequest, token_address: str, report_trades: list[TradeRecord]) -> tuple[TokenAnalysisResult, list[TradeRecord]]:
        symbol = next((t.token_symbol for t in report_trades if t.token_address == token_address), token_address[:6])
        self._progress("first_buy", f"正在追溯 {symbol} 首次买入", 0, 0, request.wallet_address, token_address)
        history, pages, complete = self.collector.collect_token_history(
            request.chain,
            request.wallet_address,
            token_address,
            on_progress=lambda msg: self._progress("first_buy", msg, 0, 0, request.wallet_address, token_address),
        )
        merged = {t.activity_fingerprint for t in history}
        for trade in report_trades:
            if trade.token_address != token_address:
                continue
            if trade.activity_fingerprint not in merged:
                history.append(trade)
                merged.add(trade.activity_fingerprint)
        if not history:
            history = [t for t in report_trades if t.token_address == token_address]

        token_info = None
        pool_info = None
        if request.options.fetch_token_created_at or request.options.fetch_platform_pool:
            token_info = self.enricher.get_token_info(request.chain, token_address)
        if request.options.fetch_platform_pool:
            pool_info = self.enricher.get_pool_info(request.chain, token_address)

        acq = resolve_acquisition(
            history,
            token_info,
            detect_special=request.options.detect_transfer_bridge and request.options.autofill_missing,
        )
        activity_platform = next((t.launchpad_platform for t in history if t.launchpad_platform), None)
        platforms = resolve_platforms(token_info, pool_info, activity_platform, autofill=request.options.autofill_missing)
        platform = platforms.display
        fifo = apply_fifo(history)
        report_token_trades = [t for t in history if request.start_time <= t.timestamp <= request.end_time] if request.period != ReportPeriod.ALL else history
        if request.period == ReportPeriod.ALL:
            report_token_trades = history
        else:
            report_token_trades = [t for t in history if (not request.start_time or t.timestamp >= request.start_time) and (not request.end_time or t.timestamp <= request.end_time)]

        buys = [t for t in report_token_trades if t.event_type == EventType.BUY]
        sells = [t for t in report_token_trades if t.event_type == EventType.SELL]
        buy_total = _sum_optional([t.cost_usd for t in buys])
        sell_total = _sum_optional([t.cost_usd for t in sells])

        created = (
            known(token_info.creation_timestamp, "token_info.creation_timestamp")
            if token_info and token_info.creation_timestamp
            else missing("token_info.creation_timestamp", "GMGN 未提供")
        )
        open_at = (
            known(token_info.open_timestamp, "token_info.open_timestamp")
            if token_info and token_info.open_timestamp
            else missing("token_info.open_timestamp", "GMGN 未提供")
        )
        pool_created = missing("token_info.pool.creation_timestamp", "GMGN 未提供")
        if token_info and token_info.pool_created_at:
            pool_created = known(token_info.pool_created_at, "token_info.pool.creation_timestamp")
        elif pool_info and pool_info.creation_timestamp:
            pool_created = known(pool_info.creation_timestamp, "token_pool_info.creation_timestamp")

        if acq.acquisition_type == AcquisitionType.BUY:
            first_buy_display = known(acq.cost_usd, "wallet_activity.first_buy.cost_usd") if acq.cost_usd is not None else missing("wallet_activity", "GMGN 未提供买入金额")
            first_amount = known(acq.amount, "wallet_activity.first_buy.token_amount") if acq.amount is not None else missing("wallet_activity", "GMGN 未提供数量")
            first_time = known(acq.timestamp, "wallet_activity.first_buy.timestamp") if acq.timestamp else missing("wallet_activity", "GMGN 未提供时间")
        else:
            first_buy_display = not_applicable("wallet_activity", "不适用（转入获得）")
            first_amount = known(acq.amount, "wallet_activity.transferIn.token_amount") if acq.amount is not None else missing("wallet_activity", "GMGN 未提供转入数量")
            first_time = known(acq.timestamp, "wallet_activity.transferIn.timestamp") if acq.timestamp else missing("wallet_activity", "无首次获得时间")

        if acq.market_cap is not None:
            market_cap = known(
                acq.market_cap,
                acq.market_cap_source,
                estimated=acq.market_cap_is_estimated,
                reason="使用当前供给估算" if acq.market_cap_is_estimated else "",
            )
        elif acq.acquisition_type != AcquisitionType.BUY:
            market_cap = not_applicable("wallet_activity", "无可验证历史市值")
        else:
            market_cap = missing("wallet_activity", "GMGN 未提供入场市值")

        fifo_profit = (
            known(fifo.realized_profit, "local_fifo")
            if fifo.realized_profit is not None
            else not_applicable("local_fifo", "无法验证历史成本" if fifo.missing_cost_count else "无已实现卖出")
        )
        gmgn_realized = missing("wallet_profits", "GMGN 利润接口不提供单 Token 拆分，见钱包汇总")
        position = TokenPositionStatus.OPEN if fifo.current_balance > 0 else TokenPositionStatus.CLOSED
        status = TaskStatus.SUCCESS
        notes = []
        if not complete:
            notes.append("历史分页未标记完成")
            status = TaskStatus.WARNING
        if fifo.missing_cost_count:
            notes.append(f"缺失成本 {fifo.missing_cost_count} 笔")
            status = TaskStatus.WARNING
        if acq.acquisition_type != AcquisitionType.BUY:
            notes.append(acq.reason)
        if token_info and token_info.info_status == FieldStatus.ERROR:
            notes.append(token_info.info_error)
            status = TaskStatus.WARNING

        result = TokenAnalysisResult(
            wallet_address=request.wallet_address,
            token_address=token_address,
            chain=request.chain,
            symbol=((token_info.symbol if token_info else "") or symbol or "").strip() or "未知",
            name=((token_info.name if token_info else "") or symbol or "").strip() or "未知",
            source_platform=platform,
            launchpad_platform=platforms.launchpad_platform,
            asset_source=platforms.asset_source,
            liquidity_platform=platforms.liquidity_platform,
            primary_pool=platforms.primary_pool,
            acquisition=acq,
            created_at=created,
            open_at=open_at,
            pool_created_at=pool_created,
            time_diff_seconds=missing("local", "未计算"),
            buy_count=len(buys),
            buy_total_usd=buy_total,
            sell_count=len(sells),
            sell_total_usd=sell_total,
            realized_profit=gmgn_realized,
            unrealized_profit=missing("wallet_holdings", "未使用 holdings 接口，单 Token 未实现盈亏见 FIFO 余额"),
            total_profit=missing("wallet_profits", "GMGN 利润接口不提供单 Token 拆分，见钱包汇总"),
            total_profit_pnl=missing("wallet_profits", "GMGN 利润接口不提供单 Token 拆分，见钱包汇总"),
            fifo_realized_profit=fifo_profit,
            current_balance=fifo.current_balance,
            calculated_balance=fifo.current_balance,
            balance_authority="DERIVED_FROM_ACTIVITY",
            holding_duration_seconds=missing("local", "未计算"),
            missing_cost_count=fifo.missing_cost_count,
            missing_cost_sell_count=fifo.missing_cost_sell_count,
            missing_cost_token_amount=fifo.missing_cost_token_amount,
            status=status,
            warnings=notes or ["无"],
            position_status=position,
            first_buy_display=first_buy_display,
            first_buy_amount=first_amount,
            first_buy_time=first_time,
            market_cap=market_cap,
            report_trade_count=len(report_token_trades),
            history_page_count=pages,
            history_complete=complete,
        )
        self.completeness.apply_time_fields(result, fifo.last_sell_ts)
        if result.warnings == ["无"] and notes:
            result.warnings = notes
        return result, history

    def _failed_token(self, request: WalletAnalysisRequest, token_address: str, symbol: str, error: str) -> TokenAnalysisResult:
        from app.domain.enums import AcquisitionStatus
        from app.domain.models import AcquisitionInfo

        acq = AcquisitionInfo(
            acquisition_type=AcquisitionType.UNKNOWN,
            timestamp=None,
            price_usd=None,
            amount=None,
            cost_usd=None,
            cost_sol=None,
            gas_usd=None,
            gas_sol=None,
            market_cap=None,
            status=AcquisitionStatus.API_UNAVAILABLE,
            source="wallet_activity",
            reason=error,
        )
        result = TokenAnalysisResult(
            wallet_address=request.wallet_address,
            token_address=token_address,
            chain=request.chain,
            symbol=symbol or "未知",
            name=symbol or "未知",
            source_platform=error_value("token_info", "该 Token 分析失败，不影响其他 Token"),
            acquisition=acq,
            created_at=error_value("token_info", "该 Token 分析失败"),
            open_at=error_value("token_info", "该 Token 分析失败"),
            pool_created_at=error_value("token_info", "该 Token 分析失败"),
            time_diff_seconds=error_value("local", "该 Token 分析失败"),
            buy_count=0,
            buy_total_usd=None,
            sell_count=0,
            sell_total_usd=None,
            realized_profit=error_value("local", "该 Token 分析失败"),
            unrealized_profit=error_value("local", "该 Token 分析失败"),
            total_profit=error_value("local", "该 Token 分析失败"),
            total_profit_pnl=error_value("local", "该 Token 分析失败"),
            fifo_realized_profit=error_value("local", "该 Token 分析失败"),
            current_balance=None,
            holding_duration_seconds=error_value("local", "该 Token 分析失败"),
            missing_cost_count=0,
            status=TaskStatus.FAILED,
            warnings=[error],
            first_buy_display=error_value("wallet_activity", "该 Token 分析失败"),
            first_buy_amount=error_value("wallet_activity", "该 Token 分析失败"),
            first_buy_time=error_value("wallet_activity", "该 Token 分析失败"),
            market_cap=error_value("wallet_activity", "该 Token 分析失败"),
        )
        return result

    def _load_stats(self, request: WalletAnalysisRequest) -> GmgnWalletStats:
        period = gmgn_stats_period(request.period)
        try:
            payload = self.client.get_wallet_stats(request.chain, request.wallet_address, period)
            stats = parse_wallet_stats(payload, request.wallet_address, period)
            logger.info("获取 wallet_stats 成功")
            return stats
        except AnalysisCancelledError:
            raise
        except GMGNRateLimitError:
            raise
        except GMGNError as exc:
            logger.warning("wallet_stats 失败: %s", exc)
            return GmgnWalletStats(request.wallet_address, period, status=FieldStatus.ERROR, reason=str(exc))

    def _load_profit(self, request: WalletAnalysisRequest) -> GmgnProfit:
        native = gmgn_profit_period(request.period)
        if native is None:
            reason = "接口不支持该周期（仅 1d/7d/30d/all），官方利润见此说明，不使用伪造值"
            logger.warning(reason)
            return GmgnProfit(request.wallet_address, request.period.value, status=FieldStatus.API_MISSING, reason=reason)
        try:
            payload = self.client.get_wallet_profits(request.chain, [request.wallet_address], native)
            profit = parse_wallet_profits(payload, request.wallet_address, native)
            logger.info("获取 wallet_profits 成功 period=%s", native)
            return profit
        except AnalysisCancelledError:
            raise
        except GMGNRateLimitError:
            raise
        except GMGNError as exc:
            logger.warning("wallet_profits 失败: %s", exc)
            return GmgnProfit(request.wallet_address, native, status=FieldStatus.ERROR, reason=str(exc))

    def _token_ids(self, trades: list[TradeRecord]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for trade in trades:
            if trade.token_address in seen:
                continue
            seen.add(trade.token_address)
            ordered.append(trade.token_address)
        return ordered

    def _summary(self, tokens: list[TokenAnalysisResult], trades: list[TradeRecord], profit: GmgnProfit) -> AnalysisSummary:
        buy_count = sum(1 for t in trades if t.event_type == EventType.BUY and t.in_report_range)
        sell_count = sum(1 for t in trades if t.event_type == EventType.SELL and t.in_report_range)
        gas_values = [t.gas_usd for t in trades if t.in_report_range and t.gas_usd is not None]
        gas = known(sum(gas_values, Decimal("0")), "wallet_activity.gas_usd") if gas_values else missing("wallet_activity.gas_usd", "GMGN 未提供 Gas")
        special = sum(1 for t in tokens if t.acquisition.acquisition_type != AcquisitionType.BUY)
        missing_cost = sum(t.missing_cost_count for t in tokens)
        open_pos = sum(1 for t in tokens if t.position_status == TokenPositionStatus.OPEN)
        realized = known(profit.realized_profit, "wallet_profits.realized_profit") if profit.status == FieldStatus.KNOWN and profit.realized_profit is not None else (
            missing("wallet_profits", profit.reason or "GMGN 未提供") if profit.status != FieldStatus.ERROR else error_value("wallet_profits", profit.reason)
        )
        total = known(profit.total_profit, "wallet_profits.total_profit") if profit.status == FieldStatus.KNOWN and profit.total_profit is not None else (
            missing("wallet_profits", profit.reason or "GMGN 未提供") if profit.status != FieldStatus.ERROR else error_value("wallet_profits", profit.reason)
        )
        return AnalysisSummary(
            token_count=len(tokens),
            buy_count=buy_count,
            sell_count=sell_count,
            gmgn_realized_profit=realized,
            gmgn_total_profit=total,
            open_positions=open_pos,
            gas_total_usd=gas,
            special_acquisition_count=special,
            missing_cost_count=missing_cost,
        )

    def _progress(self, stage: str, message: str, done: int, total: int, wallet: str, token: str) -> None:
        logger.info("%s", message)
        if self.on_progress:
            with self._progress_lock:
                self.on_progress(
                    {
                        "stage": stage,
                        "message": message,
                        "done": done,
                        "total": total,
                        "wallet": wallet,
                        "token": token,
                    }
                )

    def _check_cancel(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise AnalysisCancelledError()


def _sum_optional(values: list[Optional[Decimal]]) -> Optional[Decimal]:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(present, Decimal("0"))
