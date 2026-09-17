from __future__ import annotations

from typing import Any, Optional

from app.providers.helius.parsers import parse_history_page


class HeliusWalletApi:
    def wallet_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.rest_base}{path}"
        query = {"api-key": self.api_key}
        if params:
            query.update({k: v for k, v in params.items() if v not in (None, "")})
        self._use_rest()
        payload = self.http_request("GET", url, params=query, headers=self._rest_headers(), provider=self)
        self.credits.record(self._wallet_method(path))
        return payload

    def _wallet_method(self, path: str) -> str:
        if path.endswith("/history"):
            return "wallet_history"
        if path.endswith("/transfers"):
            return "wallet_transfers"
        if path.endswith("/balances"):
            return "wallet_balances"
        if "/balance-at" in path:
            return "wallet_balance_at"
        return "wallet_api"

    def _rest_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}

    def get_wallet_history_page(
        self,
        wallet: str,
        *,
        before: str | None = None,
        after: str | None = None,
        limit: int = 100,
        tx_type: str | None = None,
        token_accounts: str = "balanceChanged",
    ) -> tuple[list, Optional[str], bool]:
        params: dict[str, Any] = {"limit": max(1, min(100, int(limit))), "tokenAccounts": token_accounts or "balanceChanged"}
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        if tx_type:
            params["type"] = tx_type
        payload = self.wallet_get(f"/v1/wallet/{wallet}/history", params)
        return parse_history_page(payload)

    def get_wallet_balances(self, wallet: str) -> Any:
        return self.wallet_get(f"/v1/wallet/{wallet}/balances")

    def get_wallet_transfers_page(self, wallet: str, *, before: str | None = None, limit: int = 100) -> Any:
        params: dict[str, Any] = {"limit": max(1, min(100, int(limit)))}
        if before:
            params["before"] = before
        return self.wallet_get(f"/v1/wallet/{wallet}/transfers", params)
