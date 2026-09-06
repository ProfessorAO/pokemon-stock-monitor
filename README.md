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

- **Pokémon Center, Smyths, Argos, and GAME are disabled** (`"enabled": false`
  in `config.json`). Confirmed live against the deployed service, including
  through a rendered headless browser (not just a plain HTTP client):
  - Pokémon Center and Smyths both return an **Incapsula** bot-mitigation
    block page ("Request unsuccessful. Incapsula incident ID: ...").
  - Argos returns an **Akamai** "Access Denied" page.
  - GAME's connection fails at the TLS/HTTP2 protocol level
    (`net::ERR_HTTP2_PROTOCOL_ERROR`), consistent with the same kind of
    active mitigation.

  These are real, active anti-bot systems working as intended, not a
  User-Agent check or a wrong selector. Per this project's boundary (no
  CAPTCHA/bot-protection bypass), nothing further has been attempted against
  them — no stealth/fingerprint-spoofing, no proxy rotation, no crawler
  impersonation. Each retailer entry carries a `blocked_reason` field
  explaining what was found. The realistic paths forward are an official
  API/affiliate feed for that retailer, or accepting they can't be
  automated and checking them manually. Flip `"enabled": true` (and clear
  `blocked_reason`) only if one of those changes.
- **Magic Madhouse works** — its listing pages are plain server-rendered
  HTML with no bot protection encountered so far. `product_url_pattern`
  still needs a final pass against its real product URL structure (see the
  `stock_monitor.adapters` warning logs for the actual link paths found).
- **`"render": true`** on a retailer config renders that page with headless
  Chromium (`app/adapters/base.py:fetch_rendered`) instead of a plain HTTP
  GET — for pages that return real content but need JS execution to show it.
  It is plain headless rendering with no stealth patches, so it does nothing
  to get past a site that's actively refusing automated clients (see above).
- **Release dates** are extracted with a best-effort regex over page text
  (`extract_release_date_text` in `app/adapters/base.py`) and stored as raw
  text, not a parsed date — treat it as a hint to verify, not a guarantee.
- Sites that block simple HTTP requests (403/429, bot-protection challenges)
  are recorded as fetch errors rather than bypassed, per the project boundary.
