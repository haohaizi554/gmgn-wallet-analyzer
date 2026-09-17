from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

from app.utils.money import format_usd_compact, to_decimal
from app.utils.validators import short_address

PLACEHOLDER = {
    "",
    "-",
    "—",
    "无",
    "未知",
    "未实现",
    "无法验证",
    "无法验证历史成本",
    "GMGN 未提供",
    "未计算",
    "无交易",
    "转入",
    "转出",
}

_SUFFIX = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}


def parse_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, dict):
        return parse_number(value.get("value"))
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return None
        return float(value)
    parsed = to_decimal(value)
    if parsed is not None:
        return float(parsed)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text or text in PLACEHOLDER or text.startswith("不适用"):
        return None
    text = text.replace("$", "").replace("%", "").replace("＋", "+").replace("−", "-")
    text = text.replace("（估）", "").replace("(估)", "")
    if not text or text in PLACEHOLDER:
        return None
    mult = 1.0
    if text[-1:] in _SUFFIX and text[-2:-1].upper() != "E":
        mult = _SUFFIX[text[-1]]
        text = text[:-1]
    parsed = to_decimal(text)
    if parsed is None:
        return None
    return float(parsed) * mult


def parse_percent(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    number = parse_number(value)
    if number is None:
        return None
    if "%" in text:
        return number
    if abs(number) <= 20:
        return number * 100.0
    return number


def _day_key(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


@dataclass
class TokenPoint:
    symbol: str
    mint: str
    realized: float
    total: float
    pnl_pct: Optional[float]
    buy_usd: float
    sell_usd: float
    platform: str
    acquisition: str
    status: str


@dataclass
class DailyPoint:
    day: str
    realized: float
    volume: float
    trades: int
    cumulative: float = 0.0


@dataclass
class NamedCount:
    name: str
    count: int
    usd: float = 0.0


@dataclass
class VizSnapshot:
    title: str
    wallet: str
    wallet_short: str
    period: str
    status: str
    token_count: int
    buy_count: int
    sell_count: int
    open_positions: int
    realized: Optional[float]
    total: Optional[float]
    gas: Optional[float]
    win_count: int = 0
    loss_count: int = 0
    flat_count: int = 0
    win_usd: float = 0.0
    loss_usd: float = 0.0
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    tokens: list[TokenPoint] = field(default_factory=list)
    daily: list[DailyPoint] = field(default_factory=list)
    platforms: list[NamedCount] = field(default_factory=list)
    acquisitions: list[NamedCount] = field(default_factory=list)
    pnl_buckets: list[NamedCount] = field(default_factory=list)
    insight: str = ""
    source: str = ""
    has_detail: bool = False

    @property
    def decided(self) -> int:
        return self.win_count + self.loss_count


def format_signed_usd(value: Optional[float]) -> str:
    if value is None:
        return "—"
    compact = format_usd_compact(value)
    if value > 0 and not compact.startswith("+"):
        return f"+{compact}"
    return compact


def format_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _clean_label(value: Any, fallback: str = "未知") -> str:
    text = str(value or "").strip()
    if not text or text in PLACEHOLDER:
        return fallback
    return text


def _audit_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if hasattr(value, "value"):
        return parse_number(getattr(value, "value"))
    return parse_number(value)


def _count_map(items: Iterable[tuple[str, float]]) -> list[NamedCount]:
    tallies: dict[str, NamedCount] = {}
    for name, usd in items:
        label = _clean_label(name)
        item = tallies.get(label)
        if item is None:
            item = NamedCount(name=label, count=0, usd=0.0)
            tallies[label] = item
        item.count += 1
        item.usd += usd
    return sorted(tallies.values(), key=lambda n: (n.count, abs(n.usd)), reverse=True)


_PNL_BUCKETS = [
    ("< -50%", lambda p: p < -50),
    ("-50~-20%", lambda p: -50 <= p < -20),
    ("-20~0%", lambda p: -20 <= p < 0),
    ("0%", lambda p: p == 0),
    ("0~20%", lambda p: 0 < p <= 20),
    ("20~50%", lambda p: 20 < p <= 50),
    ("50~100%", lambda p: 50 < p <= 100),
    ("> 100%", lambda p: p > 100),
]


def _pnl_buckets(tokens: list[TokenPoint]) -> list[NamedCount]:
    counts = {label: 0 for label, _ in _PNL_BUCKETS}
    for token in tokens:
        if token.pnl_pct is None:
            continue
        for label, pred in _PNL_BUCKETS:
            if pred(token.pnl_pct):
                counts[label] += 1
                break
    return [NamedCount(name=label, count=counts[label]) for label, _ in _PNL_BUCKETS]


def _finalize(snap: VizSnapshot) -> VizSnapshot:
    win_count = loss_count = flat_count = 0
    win_usd = loss_usd = 0.0
    for token in snap.tokens:
        if token.realized > 0:
            win_count += 1
            win_usd += token.realized
        elif token.realized < 0:
            loss_count += 1
            loss_usd += token.realized
        else:
            flat_count += 1
    snap.win_count = win_count
    snap.loss_count = loss_count
    snap.flat_count = flat_count
    snap.win_usd = win_usd
    snap.loss_usd = loss_usd
    decided = win_count + loss_count
    snap.win_rate = (win_count / decided) if decided else None
    if loss_usd < 0:
        snap.profit_factor = abs(win_usd / loss_usd) if win_usd else 0.0
    elif win_usd > 0:
        snap.profit_factor = None if decided == 0 else float("inf")
    else:
        snap.profit_factor = None
    if snap.realized is None and snap.tokens:
        snap.realized = sum(t.realized for t in snap.tokens)
    if snap.total is None and snap.tokens:
        snap.total = sum(t.total for t in snap.tokens)
    if not snap.token_count:
        snap.token_count = len(snap.tokens)
    if not snap.open_positions:
        snap.open_positions = sum(1 for t in snap.tokens if t.status == "仍持仓")
    running = 0.0
    for point in snap.daily:
        running += point.realized
        point.cumulative = running
    snap.platforms = snap.platforms or _count_map((t.platform, t.buy_usd) for t in snap.tokens)
    snap.acquisitions = snap.acquisitions or _count_map((t.acquisition, t.buy_usd) for t in snap.tokens)
    snap.pnl_buckets = snap.pnl_buckets or _pnl_buckets(snap.tokens)
    snap.has_detail = bool(snap.tokens or snap.daily)
    snap.insight = _insight(snap)
    return snap


def _insight(snap: VizSnapshot) -> str:
    if not snap.tokens and snap.realized is None:
        return "这份报告还没有可画的明细，重新跑一次分析后会生成图表。"
    parts = [f"{snap.token_count} 枚代币"]
    if snap.win_rate is not None:
        parts.append(f"胜率 {snap.win_rate * 100:.0f}%（{snap.win_count} 盈 / {snap.loss_count} 亏）")
    if snap.realized is not None:
        parts.append(f"已实现 {format_signed_usd(snap.realized)}")
    ranked = sorted(snap.tokens, key=lambda t: t.realized, reverse=True)
    if ranked:
        best = ranked[0]
        worst = ranked[-1]
        if best.realized > 0:
            parts.append(f"最大贡献 {best.symbol} {format_signed_usd(best.realized)}")
        if worst.realized < 0:
            parts.append(f"最大回撤 {worst.symbol} {format_signed_usd(worst.realized)}")
        abs_total = sum(abs(t.realized) for t in snap.tokens)
        top3 = sum(abs(t.realized) for t in sorted(snap.tokens, key=lambda t: abs(t.realized), reverse=True)[:3])
        if abs_total > 0 and top3 > 0:
            parts.append(f"前 3 枚占盈亏绝对值 {top3 / abs_total * 100:.0f}%")
    if snap.profit_factor == float("inf"):
        parts.append("没有亏损代币")
    elif snap.profit_factor is not None:
        parts.append(f"盈亏比 {snap.profit_factor:.2f}")
    return " · ".join(parts)


def snapshot_from_payload(payload: dict[str, Any], *, source: str = "") -> VizSnapshot:
    wallet_info = payload.get("wallet") or {}
    summary = payload.get("summary") or {}
    wallet = str(wallet_info.get("address") or payload.get("wallet_address") or "")
    tokens: list[TokenPoint] = []
    for row in payload.get("tokens") or []:
        realized = parse_number(row.get("本地FIFO已实现"))
        if realized is None:
            realized = parse_number(row.get("已实现盈亏")) or 0.0
        total = parse_number(row.get("总盈亏"))
        if total is None:
            total = realized
        tokens.append(
            TokenPoint(
                symbol=_clean_label(row.get("币种"), fallback=(str(row.get("代币合约") or "")[:6] or "未知")),
                mint=str(row.get("代币合约") or ""),
                realized=float(realized or 0.0),
                total=float(total or 0.0),
                pnl_pct=parse_percent(row.get("总盈亏%")),
                buy_usd=parse_number(row.get("买入总额")) or 0.0,
                sell_usd=parse_number(row.get("卖出总额")) or 0.0,
                platform=_clean_label(row.get("来源平台"), fallback="未知来源"),
                acquisition=_clean_label(row.get("获得方式"), fallback="未知"),
                status=_clean_label(row.get("持仓状态") or row.get("状态"), fallback="持仓未知"),
            )
        )
    daily_map: dict[str, DailyPoint] = {}
    for row in payload.get("trades") or []:
        day = _day_key(row.get("时间"))
        if not day:
            continue
        kind = str(row.get("类型") or "").lower()
        volume = parse_number(row.get("USD金额")) or 0.0
        realized = parse_number(row.get("单笔盈亏")) or 0.0
        if kind not in {"sell", "remove", "卖出"}:
            realized = 0.0
        point = daily_map.get(day)
        if point is None:
            point = DailyPoint(day=day, realized=0.0, volume=0.0, trades=0)
            daily_map[day] = point
        point.trades += 1
        point.volume += abs(volume)
        point.realized += realized
    snap = VizSnapshot(
        title=short_address(wallet) if wallet else "未命名钱包",
        wallet=wallet,
        wallet_short=short_address(wallet) if wallet else "—",
        period=str(wallet_info.get("period") or payload.get("period") or "—"),
        status=str((payload.get("meta") or {}).get("status") or payload.get("status") or "—"),
        token_count=int(summary.get("token_count") or len(tokens) or 0),
        buy_count=int(summary.get("buy_count") or 0),
        sell_count=int(summary.get("sell_count") or 0),
        open_positions=int(summary.get("open_positions") or 0),
        realized=_audit_float(summary.get("gmgn_realized_profit")),
        total=_audit_float(summary.get("gmgn_total_profit")),
        gas=_audit_float(summary.get("gas_total_usd")),
        tokens=tokens,
        daily=[daily_map[k] for k in sorted(daily_map)],
        source=source,
    )
    return _finalize(snap)


def snapshot_from_report(report: Any, *, source: str = "当前分析") -> VizSnapshot:
    request = getattr(report, "request", None)
    wallet = getattr(request, "wallet_address", "") if request is not None else ""
    period = getattr(getattr(request, "period", None), "value", None) or getattr(request, "period", "—")
    summary = getattr(report, "summary", None)
    tokens: list[TokenPoint] = []
    for token in getattr(report, "tokens", None) or []:
        realized = _audit_float(getattr(token, "fifo_realized_profit", None))
        if realized is None:
            realized = _audit_float(getattr(token, "realized_profit", None)) or 0.0
        total = _audit_float(getattr(token, "total_profit", None))
        if total is None:
            total = realized
        pct_raw = getattr(getattr(token, "total_profit_pnl", None), "value", None)
        pnl_pct = None
        if pct_raw is not None:
            number = parse_number(pct_raw)
            if number is not None:
                pnl_pct = number * 100.0 if abs(number) <= 20 else number
        platform = getattr(getattr(token, "source_platform", None), "value", None)
        acq = getattr(getattr(token, "acquisition", None), "acquisition_type", None)
        status = getattr(getattr(token, "position_status", None), "value", None)
        tokens.append(
            TokenPoint(
                symbol=_clean_label(getattr(token, "symbol", None), fallback=(getattr(token, "token_address", "") or "")[:6] or "未知"),
                mint=str(getattr(token, "token_address", "") or ""),
                realized=float(realized or 0.0),
                total=float(total or 0.0),
                pnl_pct=pnl_pct,
                buy_usd=parse_number(getattr(token, "buy_total_usd", None)) or 0.0,
                sell_usd=parse_number(getattr(token, "sell_total_usd", None)) or 0.0,
                platform=_clean_label(platform, fallback="未知来源"),
                acquisition=_clean_label(getattr(acq, "value", acq), fallback="未知"),
                status=_clean_label(status, fallback="持仓未知"),
            )
        )
    daily_map: dict[str, DailyPoint] = {}
    for trade in getattr(report, "trades", None) or []:
        day = _day_key(getattr(trade, "timestamp", None))
        if not day:
            continue
        kind = str(getattr(getattr(trade, "event_type", None), "value", getattr(trade, "event_type", "")) or "").lower()
        volume = parse_number(getattr(trade, "cost_usd", None)) or 0.0
        realized = parse_number(getattr(trade, "single_pnl_display", None)) or 0.0
        if kind not in {"sell", "remove"}:
            realized = 0.0
        point = daily_map.get(day)
        if point is None:
            point = DailyPoint(day=day, realized=0.0, volume=0.0, trades=0)
            daily_map[day] = point
        point.trades += 1
        point.volume += abs(volume)
        point.realized += realized
    snap = VizSnapshot(
        title=short_address(wallet) if wallet else "当前分析",
        wallet=wallet,
        wallet_short=short_address(wallet) if wallet else "—",
        period=str(period or "—"),
        status=str(getattr(getattr(report, "status", None), "value", getattr(report, "status", "—"))),
        token_count=int(getattr(summary, "token_count", 0) or len(tokens)),
        buy_count=int(getattr(summary, "buy_count", 0) or 0),
        sell_count=int(getattr(summary, "sell_count", 0) or 0),
        open_positions=int(getattr(summary, "open_positions", 0) or 0),
        realized=_audit_float(getattr(summary, "gmgn_realized_profit", None)),
        total=_audit_float(getattr(summary, "gmgn_total_profit", None)),
        gas=_audit_float(getattr(summary, "gas_total_usd", None)),
        tokens=tokens,
        daily=[daily_map[k] for k in sorted(daily_map)],
        source=source,
    )
    return _finalize(snap)


def snapshot_from_summary_row(row: dict[str, Any]) -> VizSnapshot:
    summary = row.get("summary") or {}
    wallet = str(row.get("wallet_address") or "")
    snap = VizSnapshot(
        title=short_address(wallet) if wallet else "历史报告",
        wallet=wallet,
        wallet_short=short_address(wallet) if wallet else "—",
        period=str(row.get("period") or "—"),
        status=str(row.get("status") or "—"),
        token_count=int(summary.get("token_count") or 0),
        buy_count=int(summary.get("buy_count") or 0),
        sell_count=int(summary.get("sell_count") or 0),
        open_positions=int(summary.get("open_positions") or 0),
        realized=_audit_float(summary.get("gmgn_realized_profit")),
        total=_audit_float(summary.get("gmgn_total_profit")),
        gas=_audit_float(summary.get("gas_total_usd")),
        source=str(row.get("json_path") or ""),
    )
    return _finalize(snap)
