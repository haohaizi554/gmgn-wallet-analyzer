from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from app.api.gmgn_client import GMGNClient
from app.api.rate_limiter import WeightedRateLimiter
from app.domain.enums import EventType, ReportPeriod
from app.domain.models import AnalysisOptions, WalletAnalysisRequest
from app.services.wallet_analysis_service import WalletAnalysisService
from app.storage.database import Database


class IntegrationCursorTests(unittest.TestCase):
    def test_analyze_uses_min_timestamp_buy_from_history_pages(self):
        session = MagicMock()

        def request(method, url, params=None, json=None, headers=None, timeout=None):
            path = url.split("?")[0]
            q = {k: v for k, v in (params or [])}
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            if path.endswith("/v1/user/wallet_stats"):
                resp.text = '{"code":0,"data":{"realized_profit":"1","unrealized_profit":"0","winrate":"0.5","total_cost":"10","buy_count":2,"sell_count":1,"pnl":"0.1"}}'
            elif path.endswith("/v1/user/wallet_profits"):
                resp.text = '{"code":0,"data":{"list":[{"wallet_address":"7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV","realized_profit":"1","unrealized_profit":"0","total_profit":"1","total_cost":"10"}]}}'
            elif path.endswith("/v1/user/wallet_activity"):
                token = q.get("token_address")
                cursor = q.get("cursor")
                if not token:
                    resp.text = '{"code":0,"data":{"activities":[{"event_type":"sell","tx_hash":"s1","timestamp":1757800000,"token_amount":"1","cost_usd":"3","token":{"address":"MintAAA","symbol":"AAA"}}],"next":null}}'
                elif cursor is None:
                    resp.text = '{"code":0,"data":{"activities":[{"event_type":"buy","tx_hash":"b2","timestamp":1757700000,"token_amount":"1","cost_usd":"2","price_usd":"2","token":{"address":"MintAAA","symbol":"AAA"}}],"next":"n1"}}'
                else:
                    resp.text = '{"code":0,"data":{"activities":[{"event_type":"buy","tx_hash":"b1","timestamp":1722470400,"token_amount":"1","cost_usd":"1","price_usd":"1","token":{"address":"MintAAA","symbol":"AAA","total_supply":"1000"}}],"next":null}}'
            elif path.endswith("/v1/token/info"):
                resp.text = '{"code":0,"data":{"address":"MintAAA","symbol":"AAA","name":"Alpha","creation_timestamp":1722400000,"open_timestamp":1722400100,"launchpad_platform":null,"launchpad":null,"pool":{"exchange":"pump_amm","creation_timestamp":1722400200},"total_supply":"1000"}}'
            elif path.endswith("/v1/token/pool_info"):
                resp.text = '{"code":0,"data":{"address":"pool1","exchange":"pump_amm","creation_timestamp":1722400200}}'
            else:
                resp.text = '{"code":0,"data":{}}'
            return resp

        session.request.side_effect = request
        client = GMGNClient("k", limiter=WeightedRateLimiter(rate=100, capacity=100), session=session, max_429_retries=0)
        db = Database(path=self._db_path())
        svc = WalletAnalysisService(client, db=db)
        req = WalletAnalysisRequest(
            wallet_address="7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
            period=ReportPeriod.D7,
            start_time=1756684800,
            end_time=1757800001,
            max_transactions=2500,
            options=AnalysisOptions(save_raw_json=False),
        )
        report = svc.analyze(req)
        self.assertEqual(len(report.tokens), 1)
        token = report.tokens[0]
        self.assertEqual(token.token_address, "MintAAA")
        self.assertEqual(token.acquisition.timestamp, 1722470400)
        self.assertEqual(token.source_platform.value, "Pump.fun")
        self.assertEqual(token.buy_count, 1)
        self.assertEqual(token.sell_count, 1)
        self.assertEqual(report.summary.buy_count, 1)
        self.assertEqual(report.summary.sell_count, 1)
        self.assertTrue(report.excel_path.endswith(".xlsx"))
        self.assertTrue(report.json_path.endswith(".json"))

    def _db_path(self):
        import os
        import tempfile
        from pathlib import Path

        fd, name = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        return Path(name)


if __name__ == "__main__":
    unittest.main()
