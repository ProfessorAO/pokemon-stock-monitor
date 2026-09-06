# Pokémon Stock Monitor

Monitors UK Pokémon TCG retailers for restocks and newly-listed products, and
sends an SMS alert (via Twilio) when something worth acting on happens. A
small dashboard shows current status for everything being tracked.

**Boundary:** read-only stock/price checking with conservative rate limits and
robots.txt respect, manual checkout only. This does not attempt CAPTCHA or
bot-protection bypass, and does not automate purchasing.

## How it works

- **Discovery** — each retailer adapter fetches its configured listing/search
  page(s) and matches links against a per-retailer URL pattern to find
  candidate product pages. This avoids depending on exact CSS classes, which
  change often and couldn't be verified against live pages during this build
  (see "Known limitations" below).
- **Monitoring** — for every known product (discovered or already tracked),
  the adapter fetches the product page and reads its JSON-LD `Product` schema
  (name / price / availability) where present, falling back to a keyword scan
  of the visible text (`in_stock_keywords` / `out_of_stock_keywords` in
  `config.json`).
- **Alerts** — a brand-new product, or a false→true stock transition, triggers
  an SMS if the resulting margin meets `MIN_MARGIN_PERCENT`.
- **Economics** — vend price defaults to `buy_price * DEFAULT_VEND_MULTIPLIER`,
  overridable per-SKU via `vend_overrides` in `config.json`.
- **Storage** — SQLite (`products` + `observations` tables), read by the
  dashboard and written by the background worker.

## Project layout

```
app/
  main.py          FastAPI app: dashboard, /health, /api/status, starts the worker
  worker.py         polling loop: discover -> check -> compare -> alert
  adapters/
    base.py         GenericAdapter engine (fetch, robots.txt, rate limiting, JSON-LD parsing)
    <retailer>.py   thin per-retailer subclasses — override here for site-specific handling
  db.py             SQLite schema + queries
  economics.py      vend price / margin calculation
  notifier.py       Twilio SMS sending
  config.py         env vars + config.json loading
config.json          retailer listing URLs, selectors/patterns, keyword lists
```

## Setup

```bash
cp .env.example .env      # fill in Twilio credentials
docker compose up --build
```

Dashboard: http://localhost:8080. Health check: http://localhost:8080/health.

### Required environment variables

| Variable | Purpose |
|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `TWILIO_TO_NUMBER` | SMS alerts. Leave blank to disable SMS (alerts are still logged). |
| `POLLING_INTERVAL_SECONDS` | How often the full discover+check cycle runs (default 300s). |
| `MIN_REQUEST_DELAY_SECONDS` | Minimum delay between requests to the same host (default 5s). |
| `MIN_MARGIN_PERCENT` | Alerts are suppressed below this margin (default 15%). |
| `DEFAULT_VEND_MULTIPLIER` | Vend price = buy price × this, unless overridden per-SKU. |
| `DATABASE_PATH` | SQLite file location. |

Twilio trial accounts prepend "Sent from your Twilio trial account - " to
every message; `notifier.py` sends a leading newline so that tag lands on its
own line rather than running into the alert text.

### Adding or adjusting a retailer

Edit its entry in `config.json`:

```json
{
  "name": "smyths",
  "enabled": true,
  "base_url": "https://www.smythstoys.com",
  "listing_urls": ["<a search or category page listing Pokémon TCG products>"],
  "product_url_pattern": "<regex matching that retailer's product page paths>"
}
```

No code changes needed unless a retailer needs bespoke handling — in that case
override `discover()`/`check()` in its adapter subclass under `app/adapters/`.

## Known limitations

- **Listing URLs and patterns are unverified.** This sandbox's network policy
  blocks outbound requests to retailer sites, so the `listing_urls` and
  `product_url_pattern` values in `config.json` are best-effort and will need
  checking/adjusting against the real pages once deployed. Each retailer entry
  has a `"verified": false` flag as a reminder — flip it once you've confirmed
  discovery actually finds real products for that site.
- **JavaScript-rendered storefronts.** If a retailer's listing or product page
  renders its content client-side (common on modern React/Vue storefronts),
  a plain HTTP fetch won't see the product data and that adapter will find
  nothing. The fix is either an official API/feed for that retailer, or
  swapping in a headless-browser fetch (e.g. Playwright) for that adapter
  specifically — not included here to keep the deployed service lightweight.
- **Release dates** are extracted with a best-effort regex over page text
  (`extract_release_date_text` in `app/adapters/base.py`) and stored as raw
  text, not a parsed date — treat it as a hint to verify, not a guarantee.
- Sites that block simple HTTP requests (403/429, bot-protection challenges)
  are recorded as fetch errors rather than bypassed, per the project boundary.
