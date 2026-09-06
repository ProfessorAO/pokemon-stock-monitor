from __future__ import annotations

import httpx

from .argos import ArgosAdapter
from .base import GenericAdapter, ProductRecord, RateLimiter, RobotsCache
from .chaos_cards import ChaosCardsAdapter
from .game import GameAdapter
from .magic_madhouse import MagicMadhouseAdapter
from .pokemon_center import PokemonCenterAdapter
from .smyths import SmythsAdapter
from .the_card_vault import TheCardVaultAdapter

ADAPTER_REGISTRY: dict[str, type[GenericAdapter]] = {
    "pokemon_center": PokemonCenterAdapter,
    "smyths": SmythsAdapter,
    "argos": ArgosAdapter,
    "game": GameAdapter,
    "magic_madhouse": MagicMadhouseAdapter,
    "the_card_vault": TheCardVaultAdapter,
    "chaos_cards": ChaosCardsAdapter,
}


def build_adapters(
    retailer_configs: list[dict],
    in_stock_keywords: list[str],
    out_of_stock_keywords: list[str],
    min_request_delay_seconds: float = 5.0,
) -> list[GenericAdapter]:
    client = httpx.Client()
    rate_limiter = RateLimiter(min_delay_seconds=min_request_delay_seconds)
    robots = RobotsCache(client=client)

    adapters: list[GenericAdapter] = []
    for retailer_config in retailer_configs:
        adapter_cls = ADAPTER_REGISTRY.get(retailer_config["name"], GenericAdapter)
        adapters.append(
            adapter_cls(
                retailer_config=retailer_config,
                client=client,
                rate_limiter=rate_limiter,
                robots=robots,
                in_stock_keywords=in_stock_keywords,
                out_of_stock_keywords=out_of_stock_keywords,
            )
        )
    return adapters


__all__ = ["build_adapters", "ADAPTER_REGISTRY", "ProductRecord"]
