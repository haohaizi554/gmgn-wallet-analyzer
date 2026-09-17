from __future__ import annotations

import unittest

from app.domain.models import TokenInfo, TokenPoolInfo
from app.services.platform_resolver import map_platform, resolve_source_platform


class PlatformTests(unittest.TestCase):
    def test_pool_exchange_fallback_when_launchpad_platform_missing(self):
        info = TokenInfo(
            token_address="Mint1",
            symbol="AAA",
            name="AAA",
            launchpad=None,
            launchpad_platform=None,
            pool_exchange="raydium",
        )
        value = resolve_source_platform(info, TokenPoolInfo("Mint1"))
        self.assertEqual(value.value, "Raydium")
        self.assertEqual(value.source, "token_info.pool.exchange")

    def test_does_not_invent_pumpfun(self):
        info = TokenInfo(token_address="Mint2", symbol="BBB", name="BBB")
        value = resolve_source_platform(info, None)
        self.assertEqual(value.reason, "非 Launchpad")
        self.assertNotEqual(value.value, "Pump.fun")

    def test_maps_ray_launchpad(self):
        self.assertEqual(map_platform("ray_launchpad"), "LaunchLab")
        self.assertEqual(map_platform("pumpswap"), "Pump.fun")


if __name__ == "__main__":
    unittest.main()
