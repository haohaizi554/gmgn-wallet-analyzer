from __future__ import annotations

from typing import Optional

from app.providers.solana.rpc_client import SolanaRpcProvider, TX_TTL
from app.providers.solana.transaction_parser import VerifiedTransaction


class TransactionVerifier:
    def __init__(self, rpc: SolanaRpcProvider) -> None:
        self.rpc = rpc

    def verify(self, wallet: str, token_address: str, transaction_signature: str) -> VerifiedTransaction:
        return self.rpc.verify_transaction(wallet, transaction_signature, token_address)
