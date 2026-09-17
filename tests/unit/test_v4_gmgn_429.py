from __future__ import annotations

import json as json_mod
import unittest
from unittest.mock import MagicMock

from app.api.exceptions import GMGNRateLimitError
from app.domain.enums import ReportPeriod, TaskStatus
from app.domain.models import AnalysisOptions, WalletAnalysisRequest
from app.providers.dexscreener.client import DexScreenerProvider
from app.providers.gmgn.adapter import GMGNVerifierProvider
from app.providers.helius.client import HeliusProvider
from app.providers.moralis.client import MoralisProvider
from app.providers.orchestrator import DataOrchestrator
from app.providers.solana.rpc_client import SolanaRpcProvider
from app.services.wallet_analysis_service import WalletAnalysisService
from app.storage.database import Database


class Gmgn429JobContinuesTests(unittest.TestCase):
    def test_gmgn_all_429_moralis_ok_job_succeeds(self):
        class DummyGMGN:
            api_key = "k"
            request_count = 0
            retry_429_count = 0
            error_count = 0
            on_raw = None

            def get_wallet_stats(self, *args, **kwargs):
                raise GMGNRateLimitError("GMGN 429")

            def get_wallet_profits(self, *args, **kwargs):
                raise GMGNRateLimitError("GMGN 429")

            def get_token_info(self, *args, **kwargs):
                raise GMGNRateLimitError("GMGN 429")

            def get_token_pool_info(self, *args, **kwargs):
                raise GMGNRateLimitError("GMGN 429")

            def get_wallet_activity(self, *args, **kwargs):
                raise GMGNRateLimitError("GMGN 429")

        gmgn = DummyGMGN()

        moralis_session = MagicMock()

        def moralis_request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            if "swaps" in url:
                payload = {
                    "page": 1,
                    "pageSize": 1,
                    "cursor": None,
                    "result": [
                        {
                            "transactionHash": "BuySig",
                            "transactionType": "buy",
                            "blockTimestamp": "2026-08-01T00:00:00.000Z",
                            "walletAddress": "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
                            "bought": {"address": "MintAAA", "name": "Alpha", "symbol": "AAA", "amount": "1", "usdPrice": 1, "usdAmount": 1},
                            "sold": {"address": "So11111111111111111111111111111111111111112", "symbol": "SOL", "amount": "0.01"},
                            "totalValueUsd": 1,
                        }
                    ],
                }
            elif url.endswith("/metadata"):
                payload = [
                    {
                        "mint": "MintAAA",
                        "standard": "metaplex",
                        "name": "Alpha",
                        "symbol": "AAA",
                        "decimals": "6",
                        "totalSupply": "1000",
                        "totalSupplyFormatted": "1000",
                        "fullyDilutedValue": "1000",
                        "marketCap": "1000",
                        "circulatingSupply": "1000",
                        "metaplex": {},
                        "links": {},
                        "description": "",
                        "isVerifiedContract": False,
                        "possibleSpam": False,
                        "logo": None,
                        "tokenStandard": 1,
                    }
                ]
            else:
                payload = {"nativeBalance": {"solana": "1", "lamports": "1000000000"}, "tokens": [], "nfts": []}
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        moralis_session.request.side_effect = moralis_request
        dex_session = MagicMock()

        def dex_request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            payload = [
                {
                    "chainId": "solana",
                    "dexId": "raydium",
                    "pairAddress": "pool1",
                    "baseToken": {"address": "MintAAA", "symbol": "AAA"},
                    "quoteToken": {"address": "So11111111111111111111111111111111111111112", "symbol": "SOL"},
                    "priceUsd": "1",
                    "liquidity": {"usd": 1000},
                    "fdv": 1100,
                    "marketCap": 1000,
                    "pairCreatedAt": 200000,
                }
            ]
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        dex_session.request.side_effect = dex_request
        rpc_session = MagicMock()

        def rpc_request(method, url, params=None, json=None, headers=None, timeout=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            body = json if json is not None else {}
            m = body.get("method")
            if m == "getTransaction":
                payload = {
                    "jsonrpc": "2.0",
                    "result": {
                        "blockTime": 102,
                        "meta": {
                            "err": None,
                            "fee": 5000,
                            "preBalances": [1_000_000_000],
                            "postBalances": [990_000_000],
                            "preTokenBalances": [],
                            "postTokenBalances": [
                                {
                                    "mint": "MintAAA",
                                    "owner": "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
                                    "uiTokenAmount": {"uiAmount": 1, "amount": "1000000", "decimals": 6},
                                }
                            ],
                        },
                        "transaction": {
                            "signatures": ["BuySig"],
                            "message": {"accountKeys": [{"pubkey": "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV"}], "instructions": []},
                        },
                    },
                }
            elif m == "getTokenAccountsByOwner":
                payload = {"jsonrpc": "2.0", "result": {"value": []}}
            elif m == "getTokenSupply":
                payload = {"jsonrpc": "2.0", "result": {"value": {"uiAmount": 1000}}}
            else:
                payload = {"jsonrpc": "2.0", "result": "ok"}
            resp.json.return_value = payload
            resp.content = json_mod.dumps(payload).encode()
            return resp

        rpc_session.request.side_effect = rpc_request
        moralis = MoralisProvider("mk", session=moralis_session)
        moralis._shared_session = moralis_session
        dex = DexScreenerProvider(session=dex_session)
        dex._shared_session = dex_session
        rpc = SolanaRpcProvider(session=rpc_session)
        rpc._shared_session = rpc_session
        orch = DataOrchestrator(
            [moralis, rpc, HeliusProvider(""), dex, GMGNVerifierProvider(gmgn, deep_history=False)],
        )
        db = Database(path=self._db_path())
        svc = WalletAnalysisService(gmgn, db=db, orchestrator=orch, deep_gmgn_history=False)
        req = WalletAnalysisRequest(
            wallet_address="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
            period=ReportPeriod.D7,
            start_time=1,
            end_time=2_000_000_000,
            options=AnalysisOptions(save_raw_json=False),
        )
        report = svc.analyze(req)
        self.assertIn(report.status, {TaskStatus.SUCCESS, TaskStatus.PARTIAL, TaskStatus.WARNING})
        self.assertTrue(report.excel_path.endswith(".xlsx"))
        self.assertEqual(len(report.tokens), 1)
        self.assertEqual(report.tokens[0].token_address, "MintAAA")
        self.assertIsNotNone(report.tokens[0].first_buy_time.value)

    def _db_path(self):
        import os
        import tempfile
        from pathlib import Path

        fd, name = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        return Path(name)


if __name__ == "__main__":
    unittest.main()
