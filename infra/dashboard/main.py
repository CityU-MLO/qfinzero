"""
QFinZero — System Status Dashboard.

Polls /_stats from PMB and NPP, /health from UPQ,
and serves a live HTML dashboard.

Start:
    cd infra/dashboard
    python main.py
    # open http://127.0.0.1:19380
"""

import sys
import os
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import settings

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("dashboard")

SERVICES = {
    "PMB": {"url": settings.pmb_url, "stats": "/_stats", "health": "/v1/health"},
    "NPP": {"url": settings.npp_url, "stats": "/_stats", "health": "/npp/health"},
    "UPQ": {"url": settings.upq_url, "stats": None, "health": "/health"},
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=3.0)
    logger.info("Dashboard started on %s:%s", settings.host, settings.port)
    yield
    await app.state.http.aclose()


app = FastAPI(title="QFinZero Dashboard", version="0.1.0", lifespan=lifespan)


async def _fetch_service(http: httpx.AsyncClient, name: str, svc: dict) -> dict:
    base = svc["url"]
    result = {"name": name, "status": "down", "stats": None, "health": None}

    # Try health
    try:
        r = await http.get(f"{base}{svc['health']}")
        if r.status_code < 400:
            result["status"] = "up"
            result["health"] = r.json()
    except Exception:
        pass

    # Try stats (Python services only)
    if svc["stats"]:
        try:
            r = await http.get(f"{base}{svc['stats']}")
            if r.status_code < 400:
                result["stats"] = r.json()
                result["status"] = "up"
        except Exception:
            pass

    return result


@app.get("/api/status")
async def api_status(request: Request):
    http = request.app.state.http
    import asyncio
    tasks = [_fetch_service(http, name, svc) for name, svc in SERVICES.items()]
    results = await asyncio.gather(*tasks)
    return JSONResponse({"services": results, "poll_interval": settings.poll_interval})


@app.get("/", response_class=HTMLResponse)
async def index():
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>QFinZero Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
         background: #0d1117; color: #c9d1d9; padding: 24px; }
  h1 { color: #58a6ff; margin-bottom: 8px; font-size: 22px; }
  .subtitle { color: #8b949e; margin-bottom: 24px; font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; }
  .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
  .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  .card-title { font-size: 16px; font-weight: 600; }
  .badge { padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
  .badge-up { background: #1a7f37; color: #aff5b4; }
  .badge-down { background: #8b1a1a; color: #ffa0a0; }
  .metric-row { display: flex; justify-content: space-between; padding: 4px 0;
                border-bottom: 1px solid #21262d; font-size: 13px; }
  .metric-row:last-child { border-bottom: none; }
  .metric-label { color: #8b949e; }
  .metric-value { color: #e6edf3; font-weight: 500; font-variant-numeric: tabular-nums; }
  .endpoint-table { width: 100%; margin-top: 12px; font-size: 12px; border-collapse: collapse; }
  .endpoint-table th { text-align: left; color: #8b949e; padding: 4px 6px;
                        border-bottom: 1px solid #30363d; font-weight: 500; }
  .endpoint-table td { padding: 3px 6px; border-bottom: 1px solid #21262d;
                        font-variant-numeric: tabular-nums; }
  .endpoint-table tr:hover td { background: #1c2128; }
  .section-label { color: #8b949e; font-size: 11px; text-transform: uppercase;
                   letter-spacing: 0.5px; margin-top: 12px; margin-bottom: 4px; }
  .refresh-note { color: #484f58; font-size: 11px; margin-top: 16px; text-align: center; }
  .latency-good { color: #3fb950; }
  .latency-warn { color: #d29922; }
  .latency-bad { color: #f85149; }
</style>
</head>
<body>

<h1>QFinZero Dashboard</h1>
<p class="subtitle">System Status &amp; API Performance &mdash; <span id="time"></span></p>

<div class="grid" id="cards"></div>
<p class="refresh-note">Auto-refreshes every <span id="interval">5</span>s</p>

<script>
function latencyClass(ms) {
  if (ms < 50) return 'latency-good';
  if (ms < 200) return 'latency-warn';
  return 'latency-bad';
}

function fmt(n, d) {
  if (n == null || n === undefined) return '-';
  return typeof n === 'number' ? n.toFixed(d || 1) : n;
}

function renderCard(svc) {
  const s = svc.stats;
  const isUp = svc.status === 'up';
  let html = `
    <div class="card">
      <div class="card-header">
        <span class="card-title">${svc.name}</span>
        <span class="badge ${isUp ? 'badge-up' : 'badge-down'}">${isUp ? 'UP' : 'DOWN'}</span>
      </div>`;

  if (s) {
    html += `
      <div class="metric-row"><span class="metric-label">Uptime</span>
        <span class="metric-value">${Math.floor(s.uptime_seconds/3600)}h ${Math.floor((s.uptime_seconds%3600)/60)}m</span></div>
      <div class="metric-row"><span class="metric-label">Total Requests</span>
        <span class="metric-value">${s.total_requests.toLocaleString()}</span></div>
      <div class="metric-row"><span class="metric-label">Total Errors</span>
        <span class="metric-value">${s.total_errors}</span></div>
      <div class="metric-row"><span class="metric-label">Active Now</span>
        <span class="metric-value">${s.active_requests}</span></div>`;

    // Endpoint table
    const eps = Object.entries(s.endpoints || {});
    if (eps.length > 0) {
      html += `<div class="section-label">Endpoints</div>
        <table class="endpoint-table">
        <tr><th>Endpoint</th><th>Reqs</th><th>Err</th><th>p50</th><th>p95</th><th>p99</th><th>RPM</th></tr>`;
      // Sort by count desc
      eps.sort((a,b) => b[1].count - a[1].count);
      for (const [ep, d] of eps) {
        const l = d.latency_ms;
        html += `<tr>
          <td>${ep}</td>
          <td>${d.count}</td>
          <td>${d.errors}</td>
          <td class="${latencyClass(l.p50)}">${fmt(l.p50)}</td>
          <td class="${latencyClass(l.p95)}">${fmt(l.p95)}</td>
          <td class="${latencyClass(l.p99)}">${fmt(l.p99)}</td>
          <td>${fmt(d.last_60s.rpm)}</td>
        </tr>`;
      }
      html += '</table>';
    }
  } else if (isUp) {
    html += '<div class="metric-row"><span class="metric-label">Health</span><span class="metric-value">OK (no detailed stats)</span></div>';
  } else {
    html += '<div class="metric-row"><span class="metric-label">Status</span><span class="metric-value" style="color:#f85149">Unreachable</span></div>';
  }

  html += '</div>';
  return html;
}

async function refresh() {
  try {
    const r = await fetch('/api/status');
    const data = await r.json();
    document.getElementById('interval').textContent = data.poll_interval;
    document.getElementById('time').textContent = new Date().toLocaleTimeString();
    document.getElementById('cards').innerHTML = data.services.map(renderCard).join('');
  } catch (e) {
    console.error('refresh failed', e);
  }
}

refresh();
setInterval(refresh, (""" + str(settings.poll_interval) + """) * 1000);
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
