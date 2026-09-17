from __future__ import annotations

from typing import Optional

from app.domain.enums import DataSource, ResolutionStatus
from app.domain.evidence import ResolvedField, resolved, unresolved


def resolve_creation_times(
    mint_created_at: Optional[int],
    pool_created_at: Optional[int],
    metadata_created_at: Optional[int] = None,
    mint_source: DataSource = DataSource.SOLANA_RPC,
    pool_source: DataSource = DataSource.DEXSCREENER,
) -> dict[str, ResolvedField]:
    created = (
        resolved(mint_created_at, ResolutionStatus.VERIFIED if mint_source == DataSource.SOLANA_RPC else ResolutionStatus.DIRECT, mint_source, field_name="token_created_at")
        if mint_created_at
        else unresolved(mint_source, "无法验证", "token_created_at")
    )
    pool = (
        resolved(pool_created_at, ResolutionStatus.DIRECT, pool_source, field_name="pool_created_at")
        if pool_created_at
        else unresolved(pool_source, "无法验证", "pool_created_at")
    )
    meta = (
        resolved(metadata_created_at, ResolutionStatus.DIRECT, DataSource.SOLANA_RPC, field_name="metadata_created_at")
        if metadata_created_at
        else unresolved(DataSource.SOLANA_RPC, "无法验证", "metadata_created_at")
    )
    return {"token_created_at": created, "pool_created_at": pool, "metadata_created_at": meta}
