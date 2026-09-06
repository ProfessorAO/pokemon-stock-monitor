from __future__ import annotations

import logging
import threading

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from . import db
from .config import load_settings
from .worker import run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = load_settings()
app = FastAPI(title="Pokémon Stock Monitor")


@app.on_event("startup")
def start_worker() -> None:
    thread = threading.Thread(target=run_forever, args=(settings,), daemon=True)
    thread.start()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/status")
def api_status():
    return {"products": db.list_latest_status()}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    rows = db.list_latest_status()
    row_html = []
    for row in rows:
        available = row.get("available")
        status_label = "IN STOCK" if available else "out of stock" if available is not None else "unknown"
        status_color = "#1a7f37" if available else "#666"
        price = f"£{row['price']:.2f}" if row.get("price") is not None else "—"
        release = row.get("release_date_text") or "—"
        error = row.get("error") or ""
        row_html.append(
            f"<tr>"
            f"<td>{row['retailer']}</td>"
            f"<td><a href='{row['url']}' target='_blank' rel='noopener'>{row['name']}</a></td>"
            f"<td style='color:{status_color}; font-weight:600'>{status_label}</td>"
            f"<td>{price}</td>"
            f"<td>{release}</td>"
            f"<td>{row.get('observed_at') or '—'}</td>"
            f"<td style='color:#b00'>{error}</td>"
            f"</tr>"
        )

    table_body = "\n".join(row_html) or "<tr><td colspan='7'>No products tracked yet.</td></tr>"

    html = f"""
    <html>
      <head>
        <title>Pokémon Stock Monitor</title>
        <style>
          body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #fafafa; color: #111; }}
          table {{ border-collapse: collapse; width: 100%; background: white; }}
          th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; font-size: 14px; }}
          th {{ background: #f0f0f0; }}
          h1 {{ font-size: 1.4rem; }}
        </style>
      </head>
      <body>
        <h1>Pokémon Stock Monitor</h1>
        <table>
          <thead>
            <tr>
              <th>Retailer</th><th>Product</th><th>Status</th><th>Price</th>
              <th>Release info</th><th>Last checked (UTC)</th><th>Last error</th>
            </tr>
          </thead>
          <tbody>
            {table_body}
          </tbody>
        </table>
      </body>
    </html>
    """
    return HTMLResponse(content=html)
