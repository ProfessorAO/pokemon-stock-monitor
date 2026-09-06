from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Economics:
    buy_price: float
    vend_price: float
    profit: float
    margin_percent: float


def compute_economics(
    buy_price: float,
    sku: str,
    vend_overrides: dict,
    default_vend_multiplier: float,
) -> Economics:
    vend_price = vend_overrides.get(sku, round(buy_price * default_vend_multiplier, 2))
    profit = round(vend_price - buy_price, 2)
    margin_percent = round((profit / vend_price) * 100, 1) if vend_price else 0.0
    return Economics(buy_price=buy_price, vend_price=vend_price, profit=profit, margin_percent=margin_percent)


def meets_margin_threshold(economics: Optional[Economics], min_margin_percent: float) -> bool:
    if economics is None:
        return True  # no price known yet — don't suppress the alert, just can't show economics
    return economics.margin_percent >= min_margin_percent
