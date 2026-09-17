from __future__ import annotations

from decimal import Decimal
from typing import Optional

from app.domain.enums import AcquisitionType, DataSource, ResolutionStatus
from app.domain.evidence import Evidence, ResolvedField, not_applicable_field, resolved, unresolved
from app.providers.moralis.models import WalletSwap
from app.providers.solana.transaction_parser import VerifiedTransaction, WSOL_MINT


def resolve_first_buy(
    moralis_buy: Optional[WalletSwap],
    verified: Optional[VerifiedTransaction],
) -> dict[str, ResolvedField]:
    fields: dict[str, ResolvedField] = {}
    if moralis_buy is None:
        return fields
    src = getattr(moralis_buy, "source", DataSource.MORALIS) or DataSource.MORALIS
    if not isinstance(src, DataSource):
        try:
            src = DataSource(str(src))
        except ValueError:
            src = DataSource.HELIUS
    src_name = src.value.lower()
    evidence = [
        Evidence(
            provider=src_name,
            field="first_buy_time",
            raw_value=moralis_buy.block_timestamp,
            normalized_value=moralis_buy.block_timestamp,
            timestamp=moralis_buy.block_timestamp,
            reference=moralis_buy.transaction_hash,
            source=src,
            confidence=0.7,
        )
    ]
    if verified and verified.found and verified.block_time:
        evidence.append(
            Evidence(
                provider="solana_rpc",
                field="first_buy_time",
                raw_value=verified.block_time,
                normalized_value=verified.block_time,
                timestamp=verified.block_time,
                reference=verified.signature,
                source=DataSource.SOLANA_RPC,
                confidence=0.95,
            )
        )
        fields["first_buy_time"] = resolved(
            verified.block_time,
            ResolutionStatus.VERIFIED,
            DataSource.SOLANA_RPC,
            note="链上 blockTime 裁决",
            evidence=evidence,
            field_name="first_buy_time",
            source_values={src.value: moralis_buy.block_timestamp, "SOLANA_RPC": verified.block_time},
            confidence=0.95,
        )
        fields["first_buy_tx"] = resolved(verified.signature, ResolutionStatus.VERIFIED, DataSource.SOLANA_RPC, evidence=evidence, field_name="first_buy_tx")
        amount = verified.token_delta if verified.token_delta is not None else moralis_buy.bought.amount
        fields["first_buy_amount"] = resolved(
            amount.abs() if isinstance(amount, Decimal) and amount < 0 else amount,
            ResolutionStatus.VERIFIED if verified.token_delta is not None else ResolutionStatus.DIRECT,
            DataSource.SOLANA_RPC if verified.token_delta is not None else src,
            evidence=evidence,
            field_name="first_buy_amount",
        )
        if verified.fee_sol is not None:
            fields["gas_sol"] = resolved(verified.fee_sol, ResolutionStatus.VERIFIED, DataSource.SOLANA_RPC, field_name="gas_sol")
        quote = moralis_buy.sold
        quote_sym = (quote.symbol or "").upper()
        fields["actual_quote_asset"] = resolved(quote.symbol or quote.address or "未知", ResolutionStatus.DIRECT, src, field_name="actual_quote_asset")
        if quote.amount is not None:
            fields["actual_quote_amount"] = resolved(abs(quote.amount), ResolutionStatus.DIRECT, src, field_name="actual_quote_amount")
        usd = moralis_buy.bought.usd_amount if moralis_buy.bought.usd_amount is not None else moralis_buy.total_value_usd
        if usd is None and quote_sym in {"USDC", "USDT"} and quote.amount is not None:
            usd = abs(quote.amount)
        if quote.address == WSOL_MINT or quote_sym in {"SOL", "WSOL"}:
            sol_spent = None
            if verified.wallet_sol_delta is not None:
                delta = verified.wallet_sol_delta
                if verified.fee_sol is not None:
                    delta = delta + verified.fee_sol
                sol_spent = abs(delta)
            elif quote.amount is not None:
                sol_spent = abs(quote.amount)
            fields["first_buy_sol"] = resolved(sol_spent, ResolutionStatus.VERIFIED if verified.wallet_sol_delta is not None else ResolutionStatus.DIRECT, DataSource.SOLANA_RPC if verified.wallet_sol_delta is not None else src, field_name="first_buy_sol")
            if usd is not None:
                fields["first_buy_usd"] = resolved(abs(usd), ResolutionStatus.DIRECT, src, field_name="first_buy_usd")
            else:
                fields["first_buy_usd"] = unresolved(src, "无法验证历史美元成本", "first_buy_usd")
                fields["equivalent_sol_amount"] = unresolved(src, "无法验证SOL等值", "equivalent_sol_amount")
        else:
            fields["first_buy_sol"] = not_applicable_field(DataSource.LOCAL_CALCULATION, "首买不是直接 SOL 成交", "first_buy_sol")
            if usd is not None:
                fields["first_buy_usd"] = resolved(abs(usd), ResolutionStatus.DERIVED if quote_sym in {"USDC", "USDT"} else ResolutionStatus.DIRECT, src, field_name="first_buy_usd")
            else:
                fields["first_buy_usd"] = unresolved(src, "无法验证历史美元成本", "first_buy_usd")
            fields["equivalent_sol_amount"] = unresolved(src, "无法验证SOL等值", "equivalent_sol_amount")
        return fields

    fields["first_buy_time"] = resolved(moralis_buy.block_timestamp, ResolutionStatus.DIRECT, src, evidence=evidence, field_name="first_buy_time")
    fields["first_buy_tx"] = resolved(moralis_buy.transaction_hash, ResolutionStatus.DIRECT, src, field_name="first_buy_tx")
    fields["first_buy_amount"] = resolved(moralis_buy.bought.amount, ResolutionStatus.DIRECT, src, field_name="first_buy_amount")
    usd = moralis_buy.bought.usd_amount if moralis_buy.bought.usd_amount is not None else moralis_buy.total_value_usd
    if usd is not None:
        fields["first_buy_usd"] = resolved(abs(usd), ResolutionStatus.DIRECT, src, field_name="first_buy_usd")
    else:
        fields["first_buy_usd"] = unresolved(src, "无法验证历史美元成本", "first_buy_usd")
    return fields


def transfer_in_first_buy_fields() -> dict[str, ResolvedField]:
    return {
        "first_buy_time": not_applicable_field(DataSource.LOCAL_CALCULATION, "不适用（转入获得）", "first_buy_time"),
        "first_buy_usd": not_applicable_field(DataSource.LOCAL_CALCULATION, "不适用（转入获得）", "first_buy_usd"),
        "first_buy_amount": not_applicable_field(DataSource.LOCAL_CALCULATION, "不适用（转入获得）", "first_buy_amount"),
        "first_buy_sol": not_applicable_field(DataSource.LOCAL_CALCULATION, "不适用（转入获得）", "first_buy_sol"),
        "acquisition_type": resolved(AcquisitionType.TRANSFER_IN.value, ResolutionStatus.VERIFIED, DataSource.LOCAL_CALCULATION, note="未发现 Buy，存在转入", field_name="acquisition_type"),
    }
