from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

from app.utils.money import to_decimal

WSOL_MINT = "So11111111111111111111111111111111111111112"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


@dataclass
class VerifiedTransaction:
    signature: str
    block_time: Optional[int] = None
    slot: Optional[int] = None
    success: bool = False
    fee_lamports: Optional[int] = None
    fee_sol: Optional[Decimal] = None
    wallet_sol_delta: Optional[Decimal] = None
    token_delta: Optional[Decimal] = None
    token_delta_raw: Optional[Decimal] = None
    decimals: Optional[int] = None
    pre_balance: Optional[int] = None
    post_balance: Optional[int] = None
    pre_token_balance: Optional[Decimal] = None
    post_token_balance: Optional[Decimal] = None
    program_ids: list[str] = field(default_factory=list)
    instructions: list[dict[str, Any]] = field(default_factory=list)
    inner_instructions: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    found: bool = False


def _ui_amount(entry: dict[str, Any]) -> tuple[Optional[Decimal], Optional[Decimal], Optional[int]]:
    ui = entry.get("uiTokenAmount") if isinstance(entry.get("uiTokenAmount"), dict) else {}
    amount_raw = to_decimal(ui.get("amount"))
    amount = to_decimal(ui.get("uiAmount") if ui.get("uiAmount") is not None else ui.get("uiAmountString"))
    decimals = ui.get("decimals")
    try:
        decimals_i = int(decimals) if decimals is not None else None
    except (TypeError, ValueError):
        decimals_i = None
    return amount, amount_raw, decimals_i


def parse_verified_transaction(payload: Any, wallet: str, mint: str = "", signature: str = "") -> VerifiedTransaction:
    if not payload or not isinstance(payload, dict):
        return VerifiedTransaction(signature=signature, found=False)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    tx = payload.get("transaction") if isinstance(payload.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    account_keys = message.get("accountKeys") or []
    keys: list[str] = []
    for item in account_keys:
        if isinstance(item, str):
            keys.append(item)
        elif isinstance(item, dict):
            keys.append(str(item.get("pubkey") or ""))
    wallet_index = keys.index(wallet) if wallet in keys else -1
    pre_balances = meta.get("preBalances") or []
    post_balances = meta.get("postBalances") or []
    pre_lamports = int(pre_balances[wallet_index]) if wallet_index >= 0 and wallet_index < len(pre_balances) else None
    post_lamports = int(post_balances[wallet_index]) if wallet_index >= 0 and wallet_index < len(post_balances) else None
    fee = meta.get("fee")
    try:
        fee_i = int(fee) if fee is not None else None
    except (TypeError, ValueError):
        fee_i = None
    pre_tok = _token_balance(meta.get("preTokenBalances") or [], wallet, mint)
    post_tok = _token_balance(meta.get("postTokenBalances") or [], wallet, mint)
    token_delta = None
    token_delta_raw = None
    decimals = None
    if post_tok or pre_tok:
        post_amt, post_raw, post_dec = post_tok or (Decimal("0"), Decimal("0"), None)
        pre_amt, pre_raw, pre_dec = pre_tok or (Decimal("0"), Decimal("0"), None)
        if post_amt is not None and pre_amt is not None:
            token_delta = post_amt - pre_amt
        if post_raw is not None and pre_raw is not None:
            token_delta_raw = post_raw - pre_raw
        decimals = post_dec if post_dec is not None else pre_dec
    sol_delta = None
    if pre_lamports is not None and post_lamports is not None:
        sol_delta = Decimal(post_lamports - pre_lamports) / Decimal("1000000000")
    programs: list[str] = []
    instructions = message.get("instructions") or []
    for ins in instructions:
        if isinstance(ins, dict):
            pid = ins.get("programId") or (keys[ins["programIdIndex"]] if ins.get("programIdIndex") is not None and ins.get("programIdIndex") < len(keys) else "")
            if pid:
                programs.append(str(pid))
    inner = meta.get("innerInstructions") or []
    for group in inner:
        for ins in (group.get("instructions") if isinstance(group, dict) else []) or []:
            if isinstance(ins, dict) and ins.get("programId"):
                programs.append(str(ins["programId"]))
    sigs = tx.get("signatures") or []
    sig = signature or (str(sigs[0]) if sigs else "")
    err = meta.get("err")
    block_time = payload.get("blockTime")
    try:
        block_time_i = int(block_time) if block_time is not None else None
    except (TypeError, ValueError):
        block_time_i = None
    return VerifiedTransaction(
        signature=sig,
        block_time=block_time_i,
        slot=payload.get("slot"),
        success=err is None,
        fee_lamports=fee_i,
        fee_sol=(Decimal(fee_i) / Decimal("1000000000")) if fee_i is not None else None,
        wallet_sol_delta=sol_delta,
        token_delta=token_delta,
        token_delta_raw=token_delta_raw,
        decimals=decimals,
        pre_balance=pre_lamports,
        post_balance=post_lamports,
        pre_token_balance=(pre_tok[0] if pre_tok else None),
        post_token_balance=(post_tok[0] if post_tok else None),
        program_ids=list(dict.fromkeys(programs)),
        instructions=instructions if isinstance(instructions, list) else [],
        inner_instructions=inner if isinstance(inner, list) else [],
        raw=payload,
        found=True,
    )


def _token_balance(rows: list[Any], wallet: str, mint: str) -> Optional[tuple[Optional[Decimal], Optional[Decimal], Optional[int]]]:
    if not mint:
        return None
    total_ui = Decimal("0")
    total_raw = Decimal("0")
    decimals = None
    found = False
    for item in rows:
        if not isinstance(item, dict):
            continue
        if str(item.get("mint") or "") != mint:
            continue
        owner = str(item.get("owner") or "")
        if wallet and owner and owner != wallet:
            continue
        ui_amt, raw_amt, dec = _ui_amount(item)
        found = True
        if ui_amt is not None:
            total_ui += ui_amt
        if raw_amt is not None:
            total_raw += raw_amt
        if dec is not None:
            decimals = dec
    if not found:
        return None
    return (total_ui, total_raw, decimals)
