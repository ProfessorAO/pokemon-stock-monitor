from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib import robotparser

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("stock_monitor.adapters")

USER_AGENT = "PokemonStockMonitorBot/0.2 (+read-only stock check; contact via operator)"

PRICE_RE = re.compile(r"\d+(?:[.,]\d{1,2})?")

RELEASE_DATE_PATTERNS = [
    re.compile(r"release\s*date[:\-]?\s*([0-9]{1,2}[\/\-.][0-9]{1,2}[\/\-.][0-9]{2,4})", re.I),
    re.compile(r"release\s*date[:\-]?\s*([A-Za-z]+\s+\d{1,2},?\s+\d{4})", re.I),
    re.compile(r"releas(?:es|ing)\s+on\s+([A-Za-z0-9,\s]{6,25})", re.I),
    re.compile(r"available\s+from\s+([0-9]{1,2}[\/\-.][0-9]{1,2}[\/\-.][0-9]{2,4})", re.I),
]


@dataclass
class ProductRecord:
    retailer: str
    sku: str
    name: str
    url: str
    price: Optional[float]
    available: bool
    release_date_text: Optional[str] = None
    error: Optional[str] = None


def parse_price(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    match = PRICE_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def extract_release_date_text(text: str) -> Optional[str]:
    for pattern in RELEASE_DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0).strip()
    return None


def extract_jsonld_products(soup: BeautifulSoup) -> list[dict]:
    results: list[dict] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (TypeError, ValueError):
            continue
        candidates = list(data) if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                candidates.extend(g for g in graph if isinstance(g, dict))
            item_type = item.get("@type")
            if item_type == "Product" or (isinstance(item_type, list) and "Product" in item_type):
                results.append(item)
    return results


class RateLimiter:
    """Enforces a minimum delay between requests to the same host."""

    def __init__(self, min_delay_seconds: float):
        self.min_delay = min_delay_seconds
        self._last_request_at: dict[str, float] = {}

    def wait(self, host: str) -> None:
        last = self._last_request_at.get(host)
        now = time.monotonic()
        if last is not None:
            elapsed = now - last
            if elapsed < self.min_delay:
                time.sleep(self.min_delay - elapsed)
        self._last_request_at[host] = time.monotonic()


class RobotsCache:
    """Caches robots.txt per host and refuses to fetch disallowed paths.

    Fetches robots.txt via the shared httpx client (bounded timeout) rather
    than urllib.robotparser's own .read(), which has no timeout and can hang
    the worker thread indefinitely if a host stalls the connection instead
    of refusing it.
    """

    def __init__(self, client: httpx.Client):
        self.client = client
        self._parsers: dict[str, Optional[robotparser.RobotFileParser]] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._parsers:
            parser = robotparser.RobotFileParser()
            try:
                response = self.client.get(
                    urljoin(origin, "/robots.txt"),
                    headers={"User-Agent": USER_AGENT},
                    timeout=10,
                    follow_redirects=True,
                )
                if response.status_code >= 400:
                    parser = None
                else:
                    parser.parse(response.text.splitlines())
            except Exception:
                parser = None
            self._parsers[origin] = parser
        parser = self._parsers[origin]
        if parser is None:
            return True
        try:
            return parser.can_fetch(USER_AGENT, url)
        except Exception:
            return True


_playwright_ctx = None
_browser = None
_browser_lock = threading.Lock()


def _get_browser():
    """Lazily starts a single shared headless Chromium instance for the process.

    Plain headless rendering only -- no stealth/fingerprint-spoofing plugins.
    This exists to execute client-side JS on pages that don't block us (they
    return 200 OK, they just render content in the browser), not to get past
    sites that are actively refusing requests.
    """
    global _playwright_ctx, _browser
    with _browser_lock:
        if _browser is None:
            from playwright.sync_api import sync_playwright

            ctx = sync_playwright().start()
            try:
                _browser = ctx.chromium.launch(headless=True)
                _playwright_ctx = ctx
            except Exception:
                # Don't leave a dangling driver connection -- a failed launch
                # would otherwise permanently break every later attempt in
                # this process with "Please use the Async API instead."
                try:
                    ctx.stop()
                except Exception:
                    pass
                raise
        return _browser


def fetch_rendered(url: str, timeout_ms: int = 25000) -> Optional[str]:
    try:
        browser = _get_browser()
    except Exception:
        logger.exception("Could not start Playwright/Chromium")
        return None

    try:
        # Chromium's own default UA, not our custom "...Bot..." string used for
        # plain HTTP identification -- this is a real browser engine either way,
        # just not one whose UA a site's front-end JS can string-match on "bot"
        # to decide whether to load a widget.
        context = browser.new_context()
        try:
            page = context.new_page()
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            _dismiss_cookie_banner(page)
            page.wait_for_load_state("networkidle", timeout=10000)
            _dismiss_popups(page)
            page.wait_for_load_state("networkidle", timeout=10000)
            return page.content()
        finally:
            context.close()
    except Exception:
        logger.warning("Playwright render failed for %s", url, exc_info=True)
        return None


_COOKIE_CONSENT_SELECTORS = [
    "text=/^Accept all cookies$/i",
    "text=/^Accept all$/i",
    "text=/^Accept cookies$/i",
    "text=/^Allow all$/i",
    "text=/^Allow selection$/i",
    "text=/^I accept$/i",
    "text=/^Accept$/i",
    "#onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    "button[aria-label='Accept all cookies']",
]

_POPUP_DISMISS_SELECTORS = [
    "text=/^No,? thanks$/i",
    "text=/^No thank you$/i",
    "[aria-label='Close']",
    "[aria-label='close']",
    "button.mfp-close",
    ".modal-close",
    ".klaviyo-close-form",
]


def _dismiss_cookie_banner(page) -> None:
    """Click through a cookie-consent banner if one is present.

    Ordinary, expected site interaction (the same click any visitor makes),
    not a bot-protection workaround -- many sites don't render/hydrate the
    rest of the page until the consent dialog is dismissed. Many consent
    widgets (Cookiebot, TrustArc, Quantcast) render inside an iframe, so
    every frame is checked, not just the main page.
    """
    page.wait_for_timeout(1500)  # give the consent script time to inject its banner
    for frame in page.frames:
        for selector in _COOKIE_CONSENT_SELECTORS:
            try:
                # wait_for_selector actually waits/retries; is_visible() does not
                # and will silently report false if the banner hasn't rendered yet.
                handle = frame.wait_for_selector(selector, state="visible", timeout=800)
                if handle:
                    handle.click(timeout=1000)
                    return
            except Exception:
                continue


def _dismiss_popups(page) -> None:
    """Dismiss a marketing/newsletter popup if one is present, same reasoning
    as the cookie banner -- ordinary interaction, not evasion. Falls back to
    pressing Escape, which closes most modal overlays regardless of markup."""
    page.wait_for_timeout(1000)
    for frame in page.frames:
        for selector in _POPUP_DISMISS_SELECTORS:
            try:
                handle = frame.wait_for_selector(selector, state="visible", timeout=800)
                if handle:
                    handle.click(timeout=1000)
                    return
            except Exception:
                continue
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


_HYDRATION_MARKERS = [
    "__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__", "window.__APOLLO_STATE__",
    "application/ld+json", "shopify", "Shopify.theme",
]


def diagnose_static_html(client: httpx.Client, url: str) -> None:
    """One-off diagnostic: check whether the plain (non-rendered) HTML embeds
    a server-side hydration JSON blob that could be parsed directly instead
    of relying on the rendered DOM -- often far more robust than scraping
    rendered markup when a site's product grid loads client-side."""
    try:
        response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
    except httpx.HTTPError:
        return
    if response.status_code >= 400:
        return
    text = response.text
    found = [m for m in _HYDRATION_MARKERS if m.lower() in text.lower()]
    logger.warning(
        "%s: static HTML hydration-marker check -- length=%d, markers found=%s",
        url, len(text), found,
    )


class GenericAdapter:
    """
    Config-driven retailer adapter.

    Discovery finds candidate product URLs on a listing/search page by matching
    links against a per-retailer URL pattern (site markup/CSS classes change too
    often to hardcode reliably). Monitoring reads each product page's JSON-LD
    Product schema first (name/price/availability), falling back to keyword
    scanning of visible text when a site doesn't expose structured data.
    """

    def __init__(
        self,
        retailer_config: dict,
        client: httpx.Client,
        rate_limiter: RateLimiter,
        robots: RobotsCache,
        in_stock_keywords: list[str],
        out_of_stock_keywords: list[str],
    ):
        self.config = retailer_config
        self.name = retailer_config["name"]
        self.base_url = retailer_config["base_url"]
        self.client = client
        self.rate_limiter = rate_limiter
        self.robots = robots
        self.in_stock_keywords = in_stock_keywords
        self.out_of_stock_keywords = out_of_stock_keywords
        self.product_url_pattern = re.compile(retailer_config["product_url_pattern"])

    def fetch(self, url: str) -> Optional[str]:
        if not self.robots.allowed(url):
            return None
        host = urlparse(url).netloc
        self.rate_limiter.wait(host)

        if self.config.get("render"):
            html = fetch_rendered(url)
            if html is None or len(BeautifulSoup(html, "lxml").find_all("a", href=True)) < 5:
                diagnose_static_html(self.client, url)
            return html

        try:
            response = self.client.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True
            )
        except httpx.HTTPError:
            return None
        if response.status_code in (401, 403, 429) or response.status_code >= 500:
            return None
        if response.status_code >= 400:
            return None
        return response.text

    def discover(self) -> list[str]:
        """Return candidate product page URLs found on the configured listing pages."""
        found: set[str] = set()
        for listing_url in self.config.get("listing_urls", []):
            html = self.fetch(listing_url)
            if not html:
                logger.warning("%s: listing page fetch failed or blocked: %s", self.name, listing_url)
                continue
            soup = BeautifulSoup(html, "lxml")
            all_paths: set[str] = set()
            for a in soup.find_all("a", href=True):
                href = a["href"]
                absolute = urljoin(self.base_url, href)
                path = urlparse(absolute).path
                all_paths.add(path)
                if self.product_url_pattern.search(path):
                    found.add(absolute.split("?")[0].split("#")[0])
            if not any(self.product_url_pattern.search(p) for p in all_paths):
                if not all_paths:
                    title_tag = soup.find("title")
                    title = title_tag.get_text(strip=True) if title_tag else None
                    snippet = soup.get_text(" ", strip=True)[:300]
                    logger.warning(
                        "%s: zero links found at all on %s (page length %d, title=%r) -- "
                        "likely a bot-challenge/interstitial page rather than the real "
                        "listing, even under a rendered browser. Text snippet: %r",
                        self.name, listing_url, len(html), title, snippet,
                    )
                else:
                    known_nav_prefixes = (
                        "/accessories", "/other-tcgs", "/merch", "/magic-the-gathering",
                        "/yu-gi-oh", "/funko-pop", "/tabletop-games", "/games-workshop",
                        "/coming-soon", "/sale", "/about-us", "/accessibility",
                        "/privacypolicy", "/login", "/wishlist", "/cart", "/climate-initiative",
                        "/pokemon/pokemon-merch", "/pokemon/pokemon-repacks",
                    )
                    unrecognized = sorted(
                        p for p in all_paths
                        if p and p != "/" and not p.lower().startswith(known_nav_prefixes)
                    )
                    interesting = sorted(
                        p for p in all_paths
                        if re.search(r"pok[eé]mon|tcg|trading-card", p, re.I)
                    )
                    pokemon_specific = sorted(
                        p for p in all_paths if re.search(r"pok[eé]mon", p, re.I)
                    )
                    logger.warning(
                        "%s: product_url_pattern matched nothing on %s; %d total link paths, "
                        "%d look pokemon/tcg-related (%d mention pokemon specifically), "
                        "%d not in known nav categories; pokemon-specific sample: %s",
                        self.name, listing_url, len(all_paths), len(interesting),
                        len(pokemon_specific), len(unrecognized), pokemon_specific[:100],
                    )
        return sorted(found)

    def check(self, url: str) -> ProductRecord:
        html = self.fetch(url)
        if html is None:
            return ProductRecord(
                retailer=self.name, sku=url, name=url, url=url,
                price=None, available=False, error="fetch_blocked_or_failed",
            )

        soup = BeautifulSoup(html, "lxml")
        page_text = soup.get_text(" ", strip=True)

        name = None
        price = None
        available = None
        sku = None

        for product in extract_jsonld_products(soup):
            name = name or product.get("name")
            sku = sku or product.get("sku") or product.get("productID") or product.get("gtin13")
            offers = product.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                if price is None:
                    price = parse_price(str(offers.get("price"))) if offers.get("price") is not None else None
                availability = str(offers.get("availability", ""))
                if availability:
                    available = "instock" in availability.lower()
            if name and price is not None and available is not None:
                break

        if not name:
            title_tag = soup.find("title")
            name = title_tag.get_text(strip=True) if title_tag else url

        if not sku:
            sku = urlparse(url).path.strip("/").split("/")[-1] or url

        if available is None:
            lowered = page_text.lower()
            has_out_of_stock = any(k in lowered for k in self.out_of_stock_keywords)
            has_in_stock = any(k in lowered for k in self.in_stock_keywords)
            if has_out_of_stock:
                available = False
            elif has_in_stock:
                available = True
            else:
                available = False

        if price is None:
            price = parse_price(page_text)

        release_date_text = extract_release_date_text(page_text)

        return ProductRecord(
            retailer=self.name,
            sku=str(sku),
            name=name,
            url=url,
            price=price,
            available=bool(available),
            release_date_text=release_date_text,
        )
