from __future__ import annotations

from typing import Optional

from app.api.exceptions import GMGNError
from app.api.gmgn_client import GMGNClient
from app.api.parsers import parse_pool_info, parse_token_info
from app.domain.enums import FieldStatus
from app.domain.models import TokenInfo, TokenPoolInfo
from app.storage.cache import CacheService
from app.utils.logger import get_logger

logger = get_logger("gmgn.enricher")


class TokenEnricher:
    def __init__(self, client: GMGNClient, cache: Optional[CacheService] = None):
        self.client = client
        self.cache = cache

    def get_token_info(self, chain: str, token_address: str) -> TokenInfo:
        cached = self.cache.get_token_info(chain, token_address) if self.cache else None
        if cached is not None:
            info = parse_token_info(cached, token_address, chain)
            return info
        try:
            payload = self.client.get_token_info(chain, token_address)
        except GMGNError as exc:
            logger.warning("Token Info 失败 %s: %s", token_address, exc)
            return TokenInfo(
                token_address=token_address,
                chain=chain,
                symbol="未知",
                name="未知",
                info_status=FieldStatus.ERROR,
                info_error=str(exc),
            )
        if self.cache:
            self.cache.set_token_info(chain, token_address, payload)
        return parse_token_info(payload, token_address, chain)

    def get_pool_info(self, chain: str, token_address: str) -> TokenPoolInfo:
        cached = self.cache.get_pool(chain, token_address) if self.cache else None
        if cached is not None:
            return parse_pool_info(cached, token_address)
        try:
            payload = self.client.get_token_pool_info(chain, token_address)
        except GMGNError as exc:
            logger.warning("Token Pool 失败 %s: %s", token_address, exc)
            return TokenPoolInfo(token_address=token_address, status=FieldStatus.ERROR, error=str(exc))
        if self.cache:
            self.cache.set_pool(chain, token_address, payload)
        return parse_pool_info(payload, token_address)
