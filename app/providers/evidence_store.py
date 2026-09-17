from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.domain.evidence import Evidence, ResolvedField
from app.storage.repositories import Repositories
from app.utils.time_utils import now_ts


@dataclass
class EvidenceStore:
    repos: Repositories | None = None
    job_id: str = ""
    items: list[Evidence] = field(default_factory=list)
    resolved: dict[tuple[str, str, str], ResolvedField] = field(default_factory=dict)

    def add(self, evidence: Evidence, wallet: str = "", token: str = "") -> None:
        self.items.append(evidence)
        if self.repos and self.job_id:
            self.repos.save_evidence(
                self.job_id,
                wallet,
                token,
                evidence.field,
                evidence.provider,
                evidence.raw_value,
                evidence.normalized_value,
                evidence.reference,
                evidence.confidence,
            )

    def put_resolved(self, wallet: str, token: str, field_name: str, resolved: ResolvedField) -> None:
        self.resolved[(wallet, token, field_name)] = resolved
        if self.repos and self.job_id:
            self.repos.save_resolved_field(
                self.job_id,
                wallet,
                token,
                field_name,
                resolved.value,
                resolved.status.value,
                resolved.primary_source.value,
                resolved.confidence,
                resolved.estimated,
                resolved.note or "",
            )

    def get_resolved(self, wallet: str, token: str, field_name: str) -> Optional[ResolvedField]:
        return self.resolved.get((wallet, token, field_name))

    def for_token(self, field_name: str, token: str = "") -> list[Evidence]:
        return [e for e in self.items if e.field == field_name]
