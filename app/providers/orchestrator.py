from __future__ import annotations

from typing import Any, Callable, Optional

from app.api.gmgn_client import GMGNClient
from app.domain.enums import CircuitState, DataSource, HeliusCapStatus, ProviderCapability, ProviderHealth, VerificationMode
from app.providers.base import DataProvider, ProviderMetrics, ProviderStatus
from app.providers.cache import ProviderCache
from app.providers.dexscreener.client import DexScreenerProvider
from app.providers.exceptions import ProviderError, ProviderPlanError, ProviderRateLimitError
from app.providers.gmgn.adapter import GMGNVerifierProvider
from app.providers.helius.client import HeliusProvider, OFFICIAL_RPC
from app.providers.helius.history import collect_rpc_fallback
from app.providers.helius.parsers import history_to_swaps
from app.providers.moralis.client import MoralisProvider
from app.providers.moralis.models import TokenMetadata, TokenSwapIndex, WalletSwap, WalletSwapIndex
from app.providers.history_cache import merge_history_state, merge_swaps, row_to_swap, swap_to_row
from app.providers.priority import ProviderPriorityRegistry
from app.providers.result import HistoryCoverage, coverage_from_swaps
from app.providers.solana.rpc_client import SolanaRpcProvider
from app.providers.solana.transaction_parser import parse_verified_transaction
from app.storage.database import Database
from app.storage.repositories import Repositories
from app.utils.logger import get_logger

logger = get_logger("gmgn.orchestrator")
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def resolve_solana_rpc_url(config) -> str:
    explicit = (getattr(config, "solana_rpc_url", "") or "").strip().rstrip("/")
    helius_key = (getattr(config, "helius_api_key", "") or "").strip()
    helius_rpc = (getattr(config, "helius_rpc_url", "") or "").strip()
    if helius_key and not helius_rpc:
        helius_rpc = f"{OFFICIAL_RPC}/?api-key={helius_key}"
    if explicit and explicit != PUBLIC_RPC:
        return explicit
    if helius_rpc:
        return helius_rpc
    return explicit or PUBLIC_RPC


class DataOrchestrator:
    def __init__(
        self,
        providers: list[DataProvider],
        db: Database | None = None,
        verification_mode: VerificationMode = VerificationMode.BALANCED,
        cancel_event=None,
        on_health: Callable[[list[ProviderStatus]], None] | None = None,
    ) -> None:
        self.providers = {p.name: p for p in providers}
        for p in providers:
            p.cancel_event = cancel_event
        self.priority = ProviderPriorityRegistry()
        self.db = db
        self.repos = Repositories(db) if db else None
        self.cache = ProviderCache(self.repos) if self.repos else None
        self.verification_mode = verification_mode
        self.on_health = on_health
        self.metadata_calls = 0
        self.dex_calls = 0
        self.last_history = None
        self.history_call_count = 0
        self.last_coverage: HistoryCoverage | None = None
        self.last_swap_index: WalletSwapIndex | None = None
        self._sol_usd = None
        self._sol_usd_loaded = False

    @classmethod
    def from_config(cls, config, gmgn_client: GMGNClient | None, db: Database | None, cancel_event=None, on_health=None) -> "DataOrchestrator":
        repos = Repositories(db) if db else None
        cache = ProviderCache(repos) if repos else None
        providers: list[DataProvider] = []
        enable_moralis = bool(getattr(config, "enable_moralis", False))
        moralis_keys = list(getattr(config, "moralis_api_keys", None) or [])
        if not moralis_keys:
            single = (getattr(config, "moralis_api_key", "") or "").strip()
            if single:
                moralis_keys = [single]
        providers.append(
            MoralisProvider(
                api_key=moralis_keys[0] if moralis_keys else "",
                api_keys=moralis_keys,
                base_url=getattr(config, "moralis_base", "https://solana-gateway.moralis.io"),
                cache=cache,
                enabled_flag=enable_moralis,
            )
        )
        rpc_url = resolve_solana_rpc_url(config)
        helius_keys = list(getattr(config, "helius_api_keys", None) or [])
        helius_key = (getattr(config, "helius_api_key", "") or "").strip()
        if helius_key and helius_key not in helius_keys:
            helius_keys.insert(0, helius_key)
        using_helius_rpc = "helius-rpc.com" in rpc_url
        providers.append(
            SolanaRpcProvider(
                rpc_url=rpc_url,
                cache=cache,
                rate=float(getattr(config, "solana_rpc_rate", 8.0 if using_helius_rpc else 2.0) or 2.0),
            )
        )
        providers.append(
            HeliusProvider(
                api_key=helius_keys[0] if helius_keys else "",
                api_keys=helius_keys,
                rpc_url=getattr(config, "helius_rpc_url", "") or "",
                cache=cache,
                target_rps=float(getattr(config, "helius_target_rps", 8.0) or 8.0),
                monthly_budget=int(getattr(config, "helius_monthly_credit_budget", 1_000_000) or 1_000_000),
            )
        )
        providers.append(DexScreenerProvider(cache=cache))
        enable_gmgn = bool(getattr(config, "enable_gmgn", True))
        deep = bool(getattr(config, "enable_gmgn_deep_history_fallback", False))
        gmgn = GMGNVerifierProvider(gmgn_client if enable_gmgn else None, deep_history=deep)
        if not enable_gmgn:
            gmgn.health = ProviderHealth.DISABLED
            gmgn.health_detail = "ENABLE_GMGN=false"
            gmgn.enabled = False
        providers.append(gmgn)
        mode_raw = str(getattr(config, "verification_mode", "BALANCED") or "BALANCED").upper()
        try:
            mode = VerificationMode[mode_raw]
        except KeyError:
            mode = VerificationMode.BALANCED
        orch = cls(providers, db=db, verification_mode=mode, cancel_event=cancel_event, on_health=on_health)
        from app.providers.http import build_http_session

        shared = build_http_session()
        for item in orch.providers.values():
            item._shared_session = shared
        helius = orch.providers.get("helius")
        rpc = orch.providers.get("solana_rpc")
        if using_helius_rpc and isinstance(helius, HeliusProvider) and helius.enabled and isinstance(rpc, SolanaRpcProvider):
            rpc.limiter = helius.rpc_limiter
        if isinstance(helius, HeliusProvider) and helius.enabled and orch.repos:
            helius.credits.load_month(orch.repos.get_helius_credit_usage())
        return orch

    @classmethod
    def gmgn_only(cls, client: GMGNClient, db: Database | None = None, cancel_event=None) -> "DataOrchestrator":
        return cls(
            [
                GMGNVerifierProvider(client, deep_history=True),
                DexScreenerProvider(),
                SolanaRpcProvider(),
                MoralisProvider(api_key="", enabled_flag=False),
                HeliusProvider(api_key=""),
            ],
            db=db,
            cancel_event=cancel_event,
        )

    def provider(self, name: str) -> Optional[DataProvider]:
        return self.providers.get(name)

    def health_snapshot(self) -> list[ProviderStatus]:
        rows = [p.status() for p in self.providers.values()]
        if self.on_health:
            try:
                self.on_health(rows)
            except Exception:
                pass
        return rows

    def metrics_snapshot(self) -> list[dict[str, Any]]:
        rows = []
        for p in self.providers.values():
            snap = p.metrics.snapshot()
            if isinstance(p, HeliusProvider):
                credits = p.credits.snapshot()
                snap["estimated_credits"] = credits.get("estimated_credits", 0)
                snap["unpriced_requests"] = credits.get("unpriced_requests", 0)
                snap["wallet_history_pages"] = p.history_pages
                snap["credit_note"] = "LOCAL ESTIMATE, not official remaining credits"
            else:
                snap["estimated_credits"] = "不适用"
            rows.append(snap)
        return rows

    def request_capability(self, capability: ProviderCapability) -> Optional[DataProvider]:
        for name in self.priority.order(capability):
            provider = self.providers.get(name)
            if provider is None:
                continue
            if not provider.has_capability(capability):
                continue
            if not provider.circuit.allow():
                provider.metrics.circuit_open += 1
                continue
            return provider
        return None

    def collect_wallet_swaps(self, wallet: str, start_ts: int = 0, end_ts: int = 0, max_transactions: int = 0) -> WalletSwapIndex:
        moralis = self.providers.get("moralis")
        rpc = self.providers.get("solana_rpc")
        helius = self.providers.get("helius")
        gmgn = self.gmgn()
        moralis_on = isinstance(moralis, MoralisProvider) and moralis.enabled and moralis.has_capability(ProviderCapability.WALLET_SWAPS)
        helius_on = isinstance(helius, HeliusProvider) and helius.enabled
        gmgn_deep = bool(gmgn and gmgn.enabled and getattr(gmgn, "deep_history", False))
        primary = "MORALIS" if moralis_on else ("HELIUS" if helius_on else "SOLANA_RPC")
        logger.info(
            "history.primary=%s history.fallback=SOLANA_RPC moralis.enabled=%s helius.optional=%s gmgn.deep_history=%s",
            primary,
            str(moralis_on).lower(),
            str(helius_on).lower(),
            str(gmgn_deep).lower(),
        )
        errors: list[str] = []
        fallback_used = False
        fallback_name = ""

        if moralis_on:
            circuit_blocked = False
            if moralis.circuit.state == CircuitState.OPEN:
                opened = float(getattr(moralis.circuit, "opened_at", 0) or 0)
                clock = getattr(moralis.circuit, "_clock", None)
                now = clock.monotonic() if clock else 0.0
                if now and now - opened < moralis.circuit.open_seconds:
                    circuit_blocked = True
            if circuit_blocked:
                logger.warning("moralis circuit OPEN, fallback=SOLANA_RPC")
                errors.append("CIRCUIT_OPEN")
                fallback_used = True
                fallback_name = "SOLANA_RPC"
            else:
                try:
                    index = self._collect_moralis_swaps(wallet, start_ts=start_ts, end_ts=end_ts, max_transactions=max_transactions)
                    if index.success:
                        return self._finish_index(index, fallback_used=False)
                    errors.append(index.coverage.termination_reason if index.coverage else "moralis_failed")
                    fallback_used = True
                    fallback_name = "SOLANA_RPC"
                    logger.warning("moralis failed after retries fallback=SOLANA_RPC")
                except ProviderError as exc:
                    errors.append(str(exc))
                    fallback_used = True
                    fallback_name = "SOLANA_RPC"
                    moralis.metrics.fallback_count += 1
                    logger.warning("moralis wallet swaps failed fallback=SOLANA_RPC: %s", exc)

        helius_index = self._try_helius_wallet_history(
            wallet,
            start_ts=start_ts,
            end_ts=end_ts,
            max_transactions=max_transactions,
            as_fallback=bool(moralis_on or fallback_used),
        )
        if helius_index is not None:
            return self._finish_index(helius_index, fallback_used=helius_index.fallback_used)

        if isinstance(rpc, SolanaRpcProvider):
            try:
                self.history_call_count += 1
                hist = collect_rpc_fallback(rpc, wallet, start_ts=start_ts, end_ts=end_ts)
                if hist.transactions:
                    index = _index_from_history(
                        wallet,
                        hist,
                        provider="solana_rpc",
                        source=DataSource.SOLANA_RPC,
                        sol_usd=self.sol_usd_price(),
                    )
                    cov = coverage_from_swaps(
                        provider=DataSource.SOLANA_RPC,
                        start_ts=start_ts,
                        end_ts=end_ts,
                        timestamps=[s.block_timestamp for s in index.swaps],
                        pages=hist.pages,
                        complete=bool(hist.bottom_complete),
                        success=True,
                    )
                    cov.fallback_used = True
                    cov.fallback_provider = fallback_name or "SOLANA_RPC"
                    index.coverage = cov
                    index.success = True
                    index.complete = cov.complete
                    index.fallback_used = True
                    index.provider = "solana_rpc"
                    logger.info("RPC wallet history fallback wallet=%s tokens=%s", wallet[:8], len(index.by_token))
                    return self._finish_index(index, fallback_used=True)
                errors.append("rpc_empty")
            except ProviderError as exc:
                errors.append(str(exc))
                logger.warning("RPC wallet history fallback 失败: %s", exc)

        if gmgn_deep:
            logger.info("GMGN deep history fallback enabled, still not treating empty as verified")
            errors.append("gmgn_deep_history_not_authoritative")

        cov = HistoryCoverage(
            requested_start_ts=start_ts,
            requested_end_ts=end_ts,
            complete=False,
            verified_empty=False,
            provider=DataSource.MORALIS,
            termination_reason="unknown_empty",
            errors=errors,
            fallback_used=fallback_used,
            fallback_provider=fallback_name,
        )
        empty = WalletSwapIndex(
            wallet=wallet,
            coverage=cov,
            success=False,
            complete=False,
            fallback_used=fallback_used,
            provider="none",
        )
        logger.warning("history unknown_empty wallet=%s errors=%s", wallet[:8], errors)
        return self._finish_index(empty, fallback_used=fallback_used)

    def sol_usd_price(self):
        if self._sol_usd_loaded:
            return self._sol_usd
        self._sol_usd_loaded = True
        dex = self.providers.get("dexscreener")
        if isinstance(dex, DexScreenerProvider) and dex.enabled:
            try:
                self._sol_usd = dex.get_sol_usd()
            except Exception as exc:
                logger.warning("DEX SOL/USD 获取失败: %s", exc)
                self._sol_usd = None
        return self._sol_usd

    def _try_helius_wallet_history(
        self,
        wallet: str,
        *,
        start_ts: int,
        end_ts: int,
        max_transactions: int,
        as_fallback: bool,
    ) -> WalletSwapIndex | None:
        helius = self.providers.get("helius")
        if not isinstance(helius, HeliusProvider) or not helius.enabled:
            return None
        try:
            helius.ensure_probed(self.repos)
        except Exception as exc:
            logger.warning("Helius capability probe 失败，跳过 wallet history: %s", exc)
            return None
        if not helius.cap_flags.get("WALLET_HISTORY"):
            return None
        try:
            until = None
            prev = self.repos.get_wallet_history_state(wallet, "helius") if self.repos else None
            if prev and prev.get("bottom_complete") and prev.get("newest_signature"):
                until = prev.get("newest_signature")
            self.history_call_count += 1
            hist = helius.collect_history(
                wallet,
                start_ts=start_ts,
                end_ts=end_ts,
                max_transactions=max_transactions,
                until_signature=until,
            )
            if not hist.transactions and not hist.bottom_complete:
                return None
            index = _index_from_history(
                wallet,
                hist,
                provider="helius",
                source=DataSource.HELIUS,
                sol_usd=self.sol_usd_price(),
            )
            cached = self._load_cached_swaps(wallet, "helius")
            if cached:
                index.swaps = merge_swaps(index.swaps, cached)
                index.by_token = _index_swaps(wallet, index.swaps)
                index.from_cache = True
            self._persist_swaps(wallet, "helius", index.swaps)
            self._persist_history_state(wallet, "helius", index.swaps, bottom_complete=bool(hist.bottom_complete))
            cov = coverage_from_swaps(
                provider=DataSource.HELIUS,
                start_ts=start_ts,
                end_ts=end_ts,
                timestamps=[s.block_timestamp for s in index.swaps],
                pages=hist.pages,
                complete=bool(hist.bottom_complete or cached),
                success=True,
            )
            cov.fallback_used = as_fallback
            cov.fallback_provider = "HELIUS" if as_fallback else ""
            index.coverage = cov
            index.success = True
            index.complete = cov.complete
            index.fallback_used = as_fallback
            index.provider = "helius"
            self.last_history = hist
            logger.info("Helius wallet history wallet=%s tokens=%s pages=%s", wallet[:8], len(index.by_token), hist.pages)
            return index
        except ProviderPlanError as exc:
            logger.warning("Helius Wallet History PLAN_UNAVAILABLE, skip: %s", exc)
            helius.cap_flags["WALLET_HISTORY"] = False
            helius.cap_status["WALLET_HISTORY"] = HeliusCapStatus.PLAN_UNAVAILABLE.value
            helius.metrics.fallback_count += 1
            return None
        except ProviderError as exc:
            logger.warning("Helius wallet history 失败: %s", exc)
            helius.metrics.fallback_count += 1
            return None

    def _collect_moralis_swaps(self, wallet: str, start_ts: int, end_ts: int, max_transactions: int) -> WalletSwapIndex:
        moralis: MoralisProvider = self.providers["moralis"]  # type: ignore[assignment]
        kwargs: dict[str, Any] = {"limit": 100, "order": "DESC", "transaction_types": "buy,sell"}
        if end_ts:
            kwargs["to_date"] = end_ts
        until = None
        prev = self.repos.get_wallet_history_state(wallet, "moralis") if self.repos else None
        cached = self._load_cached_swaps(wallet, "moralis")
        if prev and prev.get("bottom_complete") and prev.get("newest_signature"):
            until = str(prev.get("newest_signature") or "") or None
        self.history_call_count += 1
        before = moralis.metrics.request_count
        swaps, pages, complete = moralis.iter_wallet_swaps(wallet, until_signature=until, **kwargs)
        if max_transactions and len(swaps) > max_transactions:
            swaps = swaps[:max_transactions]
            complete = False
        merged = merge_swaps(swaps, cached)
        from_cache = bool(cached)
        if cached or swaps:
            self._persist_swaps(wallet, "moralis", merged)
            self._persist_history_state(wallet, "moralis", merged, bottom_complete=complete or bool(prev and prev.get("bottom_complete")))
        cov = coverage_from_swaps(
            provider=DataSource.MORALIS,
            start_ts=start_ts,
            end_ts=end_ts,
            timestamps=[s.block_timestamp for s in merged],
            pages=pages,
            complete=complete or (bool(prev and prev.get("bottom_complete")) and bool(until)),
            success=True,
        )
        index = WalletSwapIndex(
            wallet=wallet,
            swaps=merged,
            pages=pages,
            by_token=_index_swaps(wallet, merged),
            coverage=cov,
            provider="moralis",
            success=True,
            complete=cov.complete,
            from_cache=from_cache,
        )
        logger.info(
            "Moralis wallet swaps wallet=%s tokens=%s pages=%s complete=%s verified_empty=%s requests=%s",
            wallet[:8],
            len(index.by_token),
            pages,
            cov.complete,
            cov.verified_empty,
            moralis.metrics.request_count - before,
        )
        return index

    def _load_cached_swaps(self, wallet: str, provider: str) -> list[WalletSwap]:
        if not self.repos:
            return []
        rows = self.repos.load_wallet_history_events(wallet, provider)
        return [row_to_swap(row) for row in rows if row.get("signature")]

    def _persist_swaps(self, wallet: str, provider: str, swaps: list[WalletSwap]) -> None:
        if not self.repos:
            return
        events = [swap_to_row(wallet, provider, item, idx) for idx, item in enumerate(swaps)]
        try:
            self.repos.save_wallet_history_events(wallet, provider, events)
        except Exception as exc:
            logger.warning("persist wallet_history_events 失败: %s", exc)

    def _finish_index(self, index: WalletSwapIndex, fallback_used: bool) -> WalletSwapIndex:
        index.fallback_used = index.fallback_used or fallback_used
        sol_usd = self.sol_usd_price()
        if sol_usd is not None and index.swaps:
            from app.resolvers.historical_price import enrich_swap_usd

            for item in index.swaps:
                enrich_swap_usd(item, sol_usd)
            index.by_token = _index_swaps(index.wallet, index.swaps)
        self.last_swap_index = index
        self.last_coverage = index.coverage
        return index

    def earliest_buy(self, wallet: str, token: str, index: WalletSwapIndex | None = None) -> Optional[WalletSwap]:
        if index and token in index.by_token and index.by_token[token].earliest_buy:
            return index.by_token[token].earliest_buy
        if self.last_history and getattr(self.last_history, "token_events", None):
            bucket = self.last_history.token_events.get(token)
            if bucket and bucket.earliest_buy:
                swaps = history_to_swaps(wallet, [bucket.earliest_buy], sol_usd=self.sol_usd_price())
                return swaps[0] if swaps else None
        return None

    def batch_metadata(self, mints: list[str]) -> dict[str, TokenMetadata]:
        out: dict[str, TokenMetadata] = {}
        helius = self.providers.get("helius")
        if isinstance(helius, HeliusProvider) and helius.enabled:
            try:
                helius.ensure_probed(self.repos)
            except Exception:
                pass
            if helius.cap_flags.get("DAS"):
                before = helius.metrics.request_count
                try:
                    assets = helius.get_asset_batch(mints)
                    self.metadata_calls = helius.metrics.request_count - before
                    for asset in assets:
                        item = helius.parse_das_metadata(asset)
                        if item:
                            out[item.mint] = item
                    if out:
                        return out
                except ProviderError as exc:
                    logger.warning("Helius DAS metadata 失败: %s", exc)
                    helius.metrics.fallback_count += 1
        moralis = self.providers.get("moralis")
        if isinstance(moralis, MoralisProvider) and moralis.has_capability(ProviderCapability.TOKEN_METADATA):
            before = moralis.metrics.request_count
            try:
                items = moralis.get_metadata_batch(mints)
                self.metadata_calls = moralis.metrics.request_count - before
                for item in items:
                    out[item.mint] = item
            except ProviderError as exc:
                logger.warning("Moralis metadata batch 失败: %s", exc)
        return out

    def batch_pools(self, mints: list[str]) -> dict[str, list]:
        dex = self.providers.get("dexscreener")
        if isinstance(dex, DexScreenerProvider) and dex.has_capability(ProviderCapability.TOKEN_POOLS):
            before = dex.metrics.request_count
            try:
                grouped = dex.get_tokens_batch(mints)
                self.dex_calls = dex.metrics.request_count - before
                return grouped
            except ProviderError as exc:
                logger.warning("DEX Screener batch 失败: %s", exc)
        return {}

    def verify_tx(self, wallet: str, mint: str, signature: str):
        helius = self.providers.get("helius")
        if isinstance(helius, HeliusProvider) and helius.enabled:
            try:
                raw = helius.get_transaction(signature)
                if raw:
                    return parse_verified_transaction(raw, wallet, mint, signature)
            except ProviderError as exc:
                logger.warning("Helius verify 失败 %s: %s", signature[:8], exc)
        rpc = self.providers.get("solana_rpc")
        if isinstance(rpc, SolanaRpcProvider) and rpc.has_capability(ProviderCapability.TRANSACTION_DETAIL):
            try:
                return rpc.verify_transaction(wallet, signature, mint)
            except ProviderError as exc:
                logger.warning("RPC verify 失败 %s: %s", signature[:8], exc)
        return None

    def official_balance(self, wallet: str, mint: str):
        rpc = self.providers.get("solana_rpc")
        if isinstance(rpc, SolanaRpcProvider):
            try:
                return rpc.get_token_balance(wallet, mint)
            except ProviderError as exc:
                logger.warning("RPC balance 失败: %s", exc)
        helius = self.providers.get("helius")
        if isinstance(helius, HeliusProvider) and helius.cap_flags.get("WALLET_BALANCES"):
            try:
                payload = helius.get_wallet_balances(wallet)
                tokens = payload.get("tokens") if isinstance(payload, dict) else None
                if isinstance(tokens, list):
                    for row in tokens:
                        if str(row.get("mint") or "") == mint:
                            return row.get("amount") or row.get("uiAmount")
            except ProviderError:
                pass
        moralis = self.providers.get("moralis")
        if isinstance(moralis, MoralisProvider) and moralis.has_capability(ProviderCapability.WALLET_BALANCES):
            try:
                port = moralis.get_portfolio(wallet)
                return port.tokens.get(mint)
            except ProviderError:
                return None
        return None

    def token_supply(self, mint: str):
        rpc = self.providers.get("solana_rpc")
        if isinstance(rpc, SolanaRpcProvider):
            try:
                return rpc.get_token_supply(mint)
            except ProviderError:
                return None
        return None

    def gmgn(self) -> Optional[GMGNVerifierProvider]:
        p = self.providers.get("gmgn")
        return p if isinstance(p, GMGNVerifierProvider) else None

    def should_verify(self, kind: str, rng=None) -> bool:
        mode = self.verification_mode
        helius = self.providers.get("helius")
        if isinstance(helius, HeliusProvider) and not helius.credits.allow_optional() and kind == "sample":
            return False
        if mode == VerificationMode.STRICT:
            return True
        if kind in {"first_buy", "creation"}:
            return True
        if mode == VerificationMode.FAST:
            return False
        if kind == "transfer":
            return True
        if kind == "conflict":
            return True
        if kind == "sample":
            import random

            return (rng or random).random() < 0.05
        return False

    def persist_credits(self) -> None:
        helius = self.providers.get("helius")
        if isinstance(helius, HeliusProvider) and self.repos:
            try:
                self.repos.save_helius_credit_usage(helius.credits.snapshot())
            except Exception as exc:
                logger.warning("保存 Helius credit 估算失败: %s", exc)

    def _persist_history_state(self, wallet: str, provider: str, swaps: list[WalletSwap] | None = None, bottom_complete: bool = False, hist=None) -> None:
        if not self.repos:
            return
        rows: list[tuple[str, int]] = []
        if swaps:
            rows = [(s.transaction_hash, int(s.block_timestamp or 0)) for s in swaps if s.transaction_hash]
        elif hist is not None and getattr(hist, "transactions", None):
            rows = [(tx.signature, int(tx.timestamp or 0)) for tx in hist.transactions]
            bottom_complete = bool(getattr(hist, "bottom_complete", False))
            provider = provider or "helius"
        prev = self.repos.get_wallet_history_state(wallet, provider)
        merged = merge_history_state(prev, rows, bottom_complete)
        self.repos.save_wallet_history_state(
            wallet,
            provider,
            bottom_complete=bool(merged["bottom_complete"]),
            oldest_signature=str(merged["oldest_signature"] or ""),
            oldest_block_time=int(merged["oldest_block_time"] or 0),
            newest_signature=str(merged["newest_signature"] or ""),
            newest_block_time=int(merged["newest_block_time"] or 0),
        )


def _index_from_history(wallet: str, hist, provider: str = "helius", source: DataSource | None = None, sol_usd=None) -> WalletSwapIndex:
    swaps = history_to_swaps(wallet, hist.transactions, sol_usd=sol_usd)
    if source is not None:
        for item in swaps:
            item.source = source
    return WalletSwapIndex(wallet=wallet, swaps=swaps, pages=hist.pages, by_token=_index_swaps(wallet, swaps), provider=provider)


def _index_swaps(wallet: str, swaps: list[WalletSwap]) -> dict[str, TokenSwapIndex]:
    by_token: dict[str, TokenSwapIndex] = {}
    for swap in swaps:
        token = swap.token_address
        if not token:
            continue
        bucket = by_token.setdefault(token, TokenSwapIndex(token_address=token))
        kind = (swap.transaction_type or "").lower()
        if kind == "buy":
            bucket.buys.append(swap)
        elif kind == "sell":
            bucket.sells.append(swap)
        elif kind in {"transfer_in", "transferin"}:
            bucket.transfers_in.append(swap)
        elif kind in {"transfer_out", "transferout"}:
            bucket.transfers_out.append(swap)
        else:
            bucket.buys.append(swap)
    for bucket in by_token.values():
        if bucket.buys:
            bucket.earliest_buy = min(bucket.buys, key=lambda s: (s.block_timestamp or 0, s.transaction_hash))
            bucket.latest_buy = max(bucket.buys, key=lambda s: (s.block_timestamp or 0, s.transaction_hash))
        buy_usd = [s.bought.usd_amount or s.total_value_usd for s in bucket.buys]
        sell_usd = [s.sold.usd_amount or s.total_value_usd for s in bucket.sells]
        present_b = [v for v in buy_usd if v is not None]
        present_s = [v for v in sell_usd if v is not None]
        bucket.total_buy_usd = sum(present_b, start=present_b[0] * 0) if present_b else None
        bucket.total_sell_usd = sum((abs(v) for v in present_s), start=present_s[0] * 0) if present_s else None
    return by_token
