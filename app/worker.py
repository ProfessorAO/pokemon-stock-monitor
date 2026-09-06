from __future__ import annotations

import logging
import time

from . import db
from .adapters import GenericAdapter, build_adapters
from .config import Settings
from .economics import compute_economics, meets_margin_threshold
from .notifier import send_sms

logger = logging.getLogger("stock_monitor.worker")


def format_alert(kind: str, record, economics) -> str:
    lines = [f"{kind}: {record.name}", f"Retailer: {record.retailer}", f"Link: {record.url}"]
    if record.release_date_text:
        lines.append(f"Release info: {record.release_date_text}")
    if economics is not None:
        lines.append(
            f"Buy: £{economics.buy_price:.2f} -> Vend: £{economics.vend_price:.2f} "
            f"(profit £{economics.profit:.2f}, {economics.margin_percent:.1f}% margin)"
        )
    return "\n".join(lines)


def process_product(settings: Settings, adapter: GenericAdapter, url: str) -> None:
    record = adapter.check(url)

    is_new = db.upsert_product(
        retailer=record.retailer,
        sku=record.sku,
        name=record.name,
        url=record.url,
        release_date_text=record.release_date_text,
    )

    previous = db.get_last_observation(record.retailer, record.sku)
    was_available = bool(previous["available"]) if previous else False

    db.insert_observation(
        retailer=record.retailer,
        sku=record.sku,
        available=record.available,
        price=record.price,
        error=record.error,
    )

    economics = None
    if record.price is not None:
        economics = compute_economics(
            buy_price=record.price,
            sku=record.sku,
            vend_overrides=settings.vend_overrides,
            default_vend_multiplier=settings.default_vend_multiplier,
        )

    if is_new:
        logger.info("New product detected: %s (%s)", record.name, record.url)
        if meets_margin_threshold(economics, settings.min_margin_percent):
            send_sms(settings, format_alert("New product detected", record, economics))
        return

    restocked = record.available and not was_available
    if restocked:
        logger.info("Restock detected: %s (%s)", record.name, record.url)
        if meets_margin_threshold(economics, settings.min_margin_percent):
            send_sms(settings, format_alert("Restock", record, economics))


def run_cycle(settings: Settings, adapters: list[GenericAdapter]) -> None:
    for adapter in adapters:
        try:
            discovered_urls = set(adapter.discover())
        except Exception:
            logger.exception("Discovery failed for %s", adapter.name)
            discovered_urls = set()

        known_urls = {row["url"] for row in db.list_known_products(adapter.name)}
        all_urls = discovered_urls | known_urls

        for url in all_urls:
            try:
                process_product(settings, adapter, url)
            except Exception:
                logger.exception("Check failed for %s (%s)", adapter.name, url)


def run_forever(settings: Settings) -> None:
    db.init_db(settings.database_path)
    adapters = build_adapters(
        retailer_configs=settings.retailers,
        in_stock_keywords=settings.in_stock_keywords,
        out_of_stock_keywords=settings.out_of_stock_keywords,
        min_request_delay_seconds=settings.min_request_delay_seconds,
    )
    logger.info("Starting worker with %d adapter(s): %s", len(adapters), [a.name for a in adapters])

    while True:
        started_at = time.monotonic()
        run_cycle(settings, adapters)
        elapsed = time.monotonic() - started_at
        sleep_for = max(0.0, settings.polling_interval_seconds - elapsed)
        time.sleep(sleep_for)
