from __future__ import annotations

from app.domain.enums import DataSource, ResolutionStatus
from app.domain.evidence import ResolvedField, resolved, unresolved
from app.providers.solana.transaction_parser import VerifiedTransaction


def resolve_gas(verified: VerifiedTransaction | None, sol_usd_historical: object | None = None) -> dict[str, ResolvedField]:
    if not verified or verified.fee_sol is None:
        return {
            "gas_sol": unresolved(DataSource.SOLANA_RPC, "无法验证", "gas_sol"),
            "gas_usd": unresolved(DataSource.SOLANA_RPC, "无法验证历史SOL价格", "gas_usd"),
        }
    fields = {
        "gas_sol": resolved(verified.fee_sol, ResolutionStatus.VERIFIED, DataSource.SOLANA_RPC, field_name="gas_sol"),
    }
    if sol_usd_historical is None:
        fields["gas_usd"] = unresolved(DataSource.LOCAL_CALCULATION, "无法验证历史SOL价格", "gas_usd")
    else:
        from decimal import Decimal

        try:
            usd = verified.fee_sol * Decimal(str(sol_usd_historical))
            fields["gas_usd"] = resolved(usd, ResolutionStatus.DERIVED, DataSource.LOCAL_CALCULATION, field_name="gas_usd")
        except Exception:
            fields["gas_usd"] = unresolved(DataSource.LOCAL_CALCULATION, "无法验证历史SOL价格", "gas_usd")
    return fields
