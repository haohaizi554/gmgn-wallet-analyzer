from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Generic, Optional, TypeVar

from app.domain.enums import DataSource, FieldStatus, ResolutionStatus
from app.domain.models import AuditedValue

T = TypeVar("T")

RESOLUTION_TO_FIELD = {
    ResolutionStatus.VERIFIED: FieldStatus.VERIFIED,
    ResolutionStatus.CONSENSUS: FieldStatus.CONSENSUS,
    ResolutionStatus.DIRECT: FieldStatus.DIRECT,
    ResolutionStatus.DERIVED: FieldStatus.DERIVED,
    ResolutionStatus.ESTIMATED: FieldStatus.ESTIMATED,
    ResolutionStatus.NOT_APPLICABLE: FieldStatus.NOT_APPLICABLE,
    ResolutionStatus.UNRESOLVED: FieldStatus.UNRESOLVED,
    ResolutionStatus.CONFLICT: FieldStatus.CONFLICT,
}


@dataclass
class Evidence:
    provider: str
    field: str
    raw_value: Any
    normalized_value: Any
    timestamp: Optional[int] = None
    reference: str = ""
    confidence: float = 0.5
    source: DataSource = DataSource.LOCAL_CALCULATION
    endpoint: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "field": self.field,
            "raw_value": _jsonable(self.raw_value),
            "normalized_value": _jsonable(self.normalized_value),
            "timestamp": self.timestamp,
            "reference": self.reference,
            "confidence": self.confidence,
            "source": self.source.value,
            "endpoint": self.endpoint,
            "note": self.note,
        }


@dataclass
class ResolvedField(Generic[T]):
    value: T | None
    status: ResolutionStatus
    primary_source: DataSource
    sources: list[DataSource] = field(default_factory=list)
    confidence: float = 0.5
    evidence: list[Evidence] = field(default_factory=list)
    note: str | None = None
    estimated: bool = False
    field_name: str = ""
    source_values: dict[str, Any] = field(default_factory=dict)

    def export_status(self) -> FieldStatus:
        if self.estimated and self.status not in (ResolutionStatus.NOT_APPLICABLE, ResolutionStatus.UNRESOLVED, ResolutionStatus.CONFLICT):
            return FieldStatus.ESTIMATED
        return RESOLUTION_TO_FIELD.get(self.status, FieldStatus.UNRESOLVED)

    def to_audited(self) -> AuditedValue:
        return AuditedValue(
            value=self.value,
            source=self.primary_source.value,
            status=self.export_status(),
            estimated=self.estimated or self.status == ResolutionStatus.ESTIMATED,
            reason=self.note or "",
            field_name=self.field_name,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": _jsonable(self.value),
            "status": self.status.value,
            "primary_source": self.primary_source.value,
            "sources": [s.value for s in self.sources],
            "confidence": self.confidence,
            "note": self.note,
            "estimated": self.estimated,
            "source_values": {k: _jsonable(v) for k, v in self.source_values.items()},
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass
class CoverageMetrics:
    verified_fields: int = 0
    consensus_fields: int = 0
    direct_fields: int = 0
    derived_fields: int = 0
    estimated_fields: int = 0
    unresolved_fields: int = 0
    conflict_fields: int = 0
    not_applicable_fields: int = 0
    total_fields: int = 0

    @property
    def completeness_rate(self) -> float:
        return 1.0 if self.total_fields else 1.0

    @property
    def verified_rate(self) -> float:
        if self.total_fields <= 0:
            return 0.0
        strong = self.verified_fields + self.consensus_fields + self.direct_fields + self.derived_fields
        return strong / self.total_fields

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified_fields": self.verified_fields,
            "consensus_fields": self.consensus_fields,
            "direct_fields": self.direct_fields,
            "derived_fields": self.derived_fields,
            "estimated_fields": self.estimated_fields,
            "unresolved_fields": self.unresolved_fields,
            "conflict_fields": self.conflict_fields,
            "not_applicable_fields": self.not_applicable_fields,
            "total_fields": self.total_fields,
            "completeness_rate": 1.0,
            "verified_rate": round(self.verified_rate, 4),
            "estimated_rate": round((self.estimated_fields / self.total_fields) if self.total_fields else 0.0, 4),
            "unresolved_rate": round((self.unresolved_fields / self.total_fields) if self.total_fields else 0.0, 4),
        }


def resolved(
    value: T | None,
    status: ResolutionStatus,
    source: DataSource,
    *,
    note: str | None = None,
    estimated: bool = False,
    evidence: list[Evidence] | None = None,
    confidence: float = 0.8,
    field_name: str = "",
    source_values: dict[str, Any] | None = None,
    sources: list[DataSource] | None = None,
) -> ResolvedField[T]:
    return ResolvedField(
        value=value,
        status=status,
        primary_source=source,
        sources=sources or [source],
        confidence=confidence,
        evidence=evidence or [],
        note=note,
        estimated=estimated or status == ResolutionStatus.ESTIMATED,
        field_name=field_name,
        source_values=source_values or {},
    )


def unresolved(source: DataSource, note: str, field_name: str = "") -> ResolvedField[Any]:
    return resolved(None, ResolutionStatus.UNRESOLVED, source, note=note, field_name=field_name, confidence=0.0)


def not_applicable_field(source: DataSource, note: str, field_name: str = "") -> ResolvedField[Any]:
    return resolved(None, ResolutionStatus.NOT_APPLICABLE, source, note=note, field_name=field_name, confidence=1.0)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, DataSource):
        return value.value
    return value
