from __future__ import annotations

import re
from dataclasses import dataclass

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_RE = re.compile(rf"^[{BASE58_ALPHABET}]+$")


@dataclass(frozen=True)
class AddressValidation:
    address: str
    valid: bool
    reason: str = ""


def validate_solana_address(address: str) -> AddressValidation:
    value = (address or "").strip()
    if not value:
        return AddressValidation(address=value, valid=False, reason="地址为空")
    if value.startswith("0x"):
        return AddressValidation(address=value, valid=False, reason="这是 EVM 地址，当前仅支持 Solana")
    if not BASE58_RE.match(value):
        return AddressValidation(address=value, valid=False, reason="不是合法 Base58 字符")
    if len(value) < 32 or len(value) > 44:
        return AddressValidation(address=value, valid=False, reason="Solana 地址长度应为 32-44")
    return AddressValidation(address=value, valid=True)


def parse_wallet_lines(text: str) -> tuple[list[str], list[AddressValidation]]:
    lines = [line.strip() for line in (text or "").splitlines()]
    wallets: list[str] = []
    errors: list[AddressValidation] = []
    seen: set[str] = set()
    for line in lines:
        if not line or line.startswith("#"):
            continue
        result = validate_solana_address(line)
        if not result.valid:
            errors.append(result)
            continue
        if result.address in seen:
            continue
        seen.add(result.address)
        wallets.append(result.address)
    return wallets, errors


def summarize_wallet_input(text: str) -> dict[str, int]:
    raw = [line.strip() for line in (text or "").splitlines() if line.strip() and not line.strip().startswith("#")]
    wallets, errors = parse_wallet_lines(text)
    return {
        "valid": len(wallets),
        "invalid": len(errors),
        "duplicate": max(0, len(raw) - len(set(raw))),
        "lines": len(raw),
        "mode_batch": 1 if len(wallets) > 1 else 0,
    }


def short_address(address: str, prefix: int = 4, suffix: int = 3) -> str:
    value = (address or "").strip()
    if not value:
        return "未知地址"
    if len(value) <= prefix + suffix + 3:
        return value
    return f"{value[:prefix]}...{value[-suffix:]}"
