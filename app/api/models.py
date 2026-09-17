from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ApiResponse:
    path: str
    method: str
    status_code: int
    data: Any
    raw: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    from_cache: bool = False
    cursor_next: Optional[str] = None
    page: int = 1
