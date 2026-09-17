from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from app.domain.enums import DataSource, ResolutionStatus
from app.domain.evidence import Evidence, ResolvedField, resolved, unresolved

CONSENSUS_TOLERANCE = Decimal("0.05")
CONFLICT_THRESHOLD = Decimal("0.10")


def _as_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def resolve_numeric_consensus(
    field_name: str,
    candidates: dict[DataSource, Any],
    *,
    tolerance: Decimal = CONSENSUS_TOLERANCE,
    conflict: Decimal = CONFLICT_THRESHOLD,
) -> ResolvedField:
    present = {src: _as_decimal(val) for src, val in candidates.items() if _as_decimal(val) is not None}
    evidence = [
        Evidence(provider=src.value, field=field_name, raw_value=val, normalized_value=str(val), source=src, confidence=0.7)
        for src, val in present.items()
    ]
    if not present:
        return unresolved(DataSource.LOCAL_CALCULATION, "无法验证", field_name)
    if len(present) == 1:
        src, val = next(iter(present.items()))
        return resolved(val, ResolutionStatus.DIRECT, src, evidence=evidence, field_name=field_name, source_values={s.value: str(v) for s, v in present.items()})
    values = list(present.values())
    primary_src = next(iter(present))
    primary = present[primary_src]
    max_diff = Decimal("0")
    base = max(abs(v) for v in values) or Decimal("1")
    for val in values:
        diff = abs(val - primary) / base if base else Decimal("0")
        if diff > max_diff:
            max_diff = diff
    note = f"差异 {float(max_diff)*100:.1f}%"
    source_values = {s.value: str(v) for s, v in present.items()}
    if max_diff <= tolerance:
        return resolved(
            primary,
            ResolutionStatus.CONSENSUS,
            primary_src,
            note=note,
            evidence=evidence,
            field_name=field_name,
            source_values=source_values,
            sources=list(present.keys()),
            confidence=0.9,
        )
    if max_diff > conflict:
        return resolved(
            primary,
            ResolutionStatus.CONFLICT,
            primary_src,
            note=note,
            evidence=evidence,
            field_name=field_name,
            source_values=source_values,
            sources=list(present.keys()),
            confidence=0.3,
        )
    return resolved(
        primary,
        ResolutionStatus.DIRECT,
        primary_src,
        note=note,
        evidence=evidence,
        field_name=field_name,
        source_values=source_values,
        sources=list(present.keys()),
        confidence=0.6,
    )
