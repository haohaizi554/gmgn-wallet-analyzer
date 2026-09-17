from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.domain.enums import FieldStatus
from app.domain.models import AuditedValue, TokenInfo, TokenPoolInfo, known, missing, not_applicable
from app.services.special_assets import lookup_special_asset

PLATFORM_MAP = {
    "pump": "Pump.fun",
    "pumpfun": "Pump.fun",
    "pump.fun": "Pump.fun",
    "pump_fun": "Pump.fun",
    "pump_amm": "Pump.fun",
    "pumpamm": "Pump.fun",
    "raydium": "Raydium",
    "raydium_clmm": "Raydium",
    "raydium_cpmm": "Raydium",
    "raydium_amm": "Raydium",
    "ray_launchpad": "LaunchLab",
    "raydium_launchpad": "LaunchLab",
    "pumpswap": "Pump.fun",
    "meteora": "Meteora",
    "meteora_dlmm": "Meteora",
    "meteora_amm": "Meteora",
    "meteora_dyn": "Meteora",
    "orca": "Orca",
    "orca_whirlpool": "Orca",
    "whirlpool": "Orca",
    "launchlab": "LaunchLab",
    "launch_lab": "LaunchLab",
    "launchlab_amm": "LaunchLab",
    "stonkfun": "stonkfun",
    "letsbonk": "LetsBonk",
    "moonshot": "Moonshot",
    "bags": "Bags",
    "believe": "Believe",
    "jupiter": "Jupiter",
    "phoenix": "Phoenix",
}


@dataclass
class PlatformResolution:
    display: AuditedValue
    launchpad_platform: AuditedValue
    asset_source: AuditedValue
    liquidity_platform: AuditedValue
    primary_pool: AuditedValue


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def map_platform(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    mapped = PLATFORM_MAP.get(_normalize_key(text))
    if mapped:
        return mapped
    if text in {"Pump.fun", "Raydium", "Meteora", "Orca", "LaunchLab", "xStocks", "Coinbase", "Wormhole", "Allbridge"}:
        return text
    return text


def resolve_platforms(
    token_info: Optional[TokenInfo],
    pool_info: Optional[TokenPoolInfo] = None,
    activity_platform: Optional[str] = None,
    autofill: bool = True,
) -> PlatformResolution:
    token_address = token_info.token_address if token_info else ""
    special = lookup_special_asset(token_address, token_info) if autofill else None

    launchpad = missing("token_info.launchpad_platform", "GMGN 未提供")
    for source, raw in (
        ("token_info.launchpad_platform", token_info.launchpad_platform if token_info else None),
        ("token_info.launchpad", token_info.launchpad if token_info else None),
        ("wallet_activity.launchpad_platform", activity_platform),
    ):
        mapped = map_platform(raw)
        if mapped:
            launchpad = known(mapped, source, reason=f"原始值={raw}")
            break

    liquidity = missing("token_pool_info.exchange", "GMGN 未提供")
    pool_addr = missing("token_pool_info.address", "GMGN 未提供")
    liq_candidates = []
    if autofill:
        liq_candidates = [
            ("token_info.pool.exchange", token_info.pool_exchange if token_info else None),
            ("token_pool_info.exchange", pool_info.exchange if pool_info else None),
        ]
    else:
        liq_candidates = [
            ("token_pool_info.exchange", pool_info.exchange if pool_info else None),
        ]
    for source, raw in liq_candidates:
        mapped = map_platform(raw)
        if mapped:
            liquidity = known(mapped, source, reason=f"原始值={raw}")
            break
    if pool_info and pool_info.pool_address:
        pool_addr = known(pool_info.pool_address, "token_pool_info.address")
    elif token_info and token_info.pool_address:
        pool_addr = known(token_info.pool_address, "token_info.pool.pool_address")

    asset = missing("special_asset_registry", "GMGN 未提供")
    if special:
        asset = known(special.platform or special.display or special.label, "special_asset_registry", reason=special.reason)

    if launchpad.status == FieldStatus.KNOWN:
        display = launchpad
    elif special:
        display = known(special.platform, "special_asset_resolver", reason=special.reason)
    elif autofill and liquidity.status == FieldStatus.KNOWN:
        display = liquidity
    elif token_info and token_info.info_status == FieldStatus.ERROR:
        display = AuditedValue(None, "token_info", FieldStatus.ERROR, reason=token_info.info_error or "Token Info 失败")
    elif autofill:
        display = not_applicable("platform_resolver", "非 Launchpad")
    else:
        display = missing("token_info.launchpad_platform", "GMGN 未提供")

    return PlatformResolution(
        display=display,
        launchpad_platform=launchpad if launchpad.status == FieldStatus.KNOWN else not_applicable("token_info.launchpad_platform", "非 Launchpad"),
        asset_source=asset if asset.status == FieldStatus.KNOWN else not_applicable("special_asset_registry", "无登记资产来源"),
        liquidity_platform=liquidity,
        primary_pool=pool_addr,
    )


def resolve_source_platform(
    token_info: Optional[TokenInfo],
    pool_info: Optional[TokenPoolInfo] = None,
    activity_platform: Optional[str] = None,
    autofill: bool = True,
) -> AuditedValue:
    return resolve_platforms(token_info, pool_info, activity_platform, autofill=autofill).display
