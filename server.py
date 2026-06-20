"""financial-signals-mcp — derived financial intelligence for autonomous agents.

Part of the FoundryNet Data Network. NOT another SEC EDGAR filings server — this
serves the DERIVED layer: insider patterns, earnings surprises/streaks,
institutional moves, ratio screens with a proprietary composite_value_score,
macro percentiles, and cross-company anomalies. A free-tier alternative to
enterprise financial data (FactSet, Morningstar, S&P Capital IQ).

8 tools (insider_activity, earnings_check, institutional_moves, screen_stocks,
sector_snapshot, macro_dashboard [free], company_profile, anomaly_alert) + a free
mint_info. Free tier 25/day, then x402 (USDC on Solana). Daily compute after US
close. Transport: Streamable HTTP at /mcp (+ legacy /sse). Health: /health.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

import config
import core
import daily_curator
import financial_signals_aggregator as agg
import identity
import payment_gate
import supa
import tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("fin.mcp")

if not supa.configured():
    logger.warning("SUPABASE_SERVICE_KEY not set — dataset disabled until configured.")
if not config.FRED_API_KEY:
    logger.warning("FRED_API_KEY not set — macro signals will be empty until configured.")

mcp = FastMCP("financial-signals")

if payment_gate.is_active():
    logger.info(f"pay-per-query ARMED → {config.PAYMENT_RECIPIENT} after "
                f"{config.FREE_TIER_DAILY}/day free")
else:
    logger.info("pay-per-query INERT — all tools free")

tools.register_all(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok", "service": "financial-signals-mcp", "transport": "streamable-http",
        "network": "FoundryNet Data Network",
        "tools": ["insider_activity", "earnings_check", "institutional_moves", "screen_stocks",
                  "sector_snapshot", "macro_dashboard", "company_profile", "anomaly_alert",
                  "daily_brief", "mint_info"],
        "dataset": "supabase:financial_signals" if supa.configured() else "unconfigured",
        "fred_key": "set" if config.FRED_API_KEY else "unset",
        "x402_enabled": config.X402_ENABLED,
        "query_payment": "armed" if payment_gate.is_active() else "free",
        "free_tier_daily": config.FREE_TIER_DAILY,
        "payment_recipient": config.PAYMENT_RECIPIENT,
        "universe_cap": config.FIN_MAX_TICKERS_PER_RUN,
    })


@mcp.custom_route("/ping", methods=["GET"])
async def ping(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ── REST surface ─────────────────────────────────────────────────────────────
_ERR = {"bad_request": 400, "not_configured": 503, "not_found": 404, "payment_required": 402}


def _resp(d: dict) -> JSONResponse:
    if "error" not in d:
        return JSONResponse(d, status_code=200)
    err = str(d.get("error") or "")
    code = _ERR.get(err, 502 if err in ("network", "non_json_response", "unreachable") else 400)
    if err.startswith("http_") and err[5:].isdigit():
        code = int(err[5:])
    return JSONResponse(d, status_code=code)


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def _akey(request: Request, body: dict) -> str:
    return identity.resolve_agent_key(body.get("agent_id"), request=request)


@mcp.custom_route("/v1/insider", methods=["POST"])
async def rest_insider(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_insider(b.get("ticker"), b.get("days_back"), b.get("signal_type"),
                                       agent_key=_akey(request, b), payment_tx=b.get("payment_tx"),
                                       api_key=identity.bearer(request)))


@mcp.custom_route("/v1/earnings", methods=["POST"])
async def rest_earnings(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_earnings(b.get("ticker", ""), agent_key=_akey(request, b),
                                        payment_tx=b.get("payment_tx"), api_key=identity.bearer(request)))


@mcp.custom_route("/v1/institutional", methods=["POST"])
async def rest_institutional(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_institutional(b.get("ticker"), b.get("institution"), b.get("signal_type"),
                                             b.get("min_value"), agent_key=_akey(request, b),
                                             payment_tx=b.get("payment_tx"), api_key=identity.bearer(request)))


@mcp.custom_route("/v1/screen", methods=["POST"])
async def rest_screen(request: Request) -> JSONResponse:
    b = await _body(request)
    filters = {k: b.get(k) for k in ("sector", "min_market_cap", "max_pe", "min_dividend_yield",
                                     "min_value_score", "sort_by", "limit")}
    return _resp(await core.do_screen(filters, agent_key=_akey(request, b),
                                      payment_tx=b.get("payment_tx"), api_key=identity.bearer(request)))


@mcp.custom_route("/v1/sector", methods=["POST"])
async def rest_sector(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_sector(b.get("sector", ""), agent_key=_akey(request, b),
                                      payment_tx=b.get("payment_tx"), api_key=identity.bearer(request)))


@mcp.custom_route("/v1/macro", methods=["GET", "POST"])
async def rest_macro(request: Request) -> JSONResponse:
    return _resp(await core.do_macro())


@mcp.custom_route("/v1/company", methods=["POST"])
async def rest_company(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_company(b.get("ticker", ""), agent_key=_akey(request, b),
                                       payment_tx=b.get("payment_tx"), api_key=identity.bearer(request)))


@mcp.custom_route("/v1/anomaly", methods=["POST"])
async def rest_anomaly(request: Request) -> JSONResponse:
    b = await _body(request)
    return _resp(await core.do_anomaly(b.get("min_severity", "low"), agent_key=_akey(request, b),
                                       payment_tx=b.get("payment_tx"), api_key=identity.bearer(request)))


@mcp.custom_route("/v1/mint-info", methods=["GET", "POST"])
async def rest_mint(request: Request) -> JSONResponse:
    return JSONResponse(core.mint_info())


@mcp.custom_route("/admin/aggregate", methods=["POST"])
async def admin_aggregate(request: Request) -> JSONResponse:
    import os
    tok = os.environ.get("ADMIN_TOKEN", "")
    if not tok or request.headers.get("x-admin-token") != tok:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    qp = request.query_params
    limit = int(qp["limit"]) if qp.get("limit", "").isdigit() else None
    only = [x for x in qp.get("tickers", "").split(",") if x.strip()] or None
    if qp.get("wait") == "1":
        return JSONResponse(await agg.run_aggregation(limit=limit, only=only))
    asyncio.create_task(agg.run_aggregation(limit=limit, only=only))
    return JSONResponse({"started": True, "limit": limit, "tickers": only})


# ── Discovery (FoundryNet Data Network cross-promo) ──────────────────────────
_TAGLINE = "Derived financial intelligence — insider, earnings, institutional & ratio signals for agents."
_DESC = ("Derived financial intelligence for agents: insider trading patterns, earnings "
         "surprises, institutional ownership moves, financial ratios with a proprietary "
         "value score, macro signals, and anomaly detection. A free-tier alternative to "
         "FactSet/Morningstar/Capital IQ. Part of the FoundryNet Data Network — attest "
         "analysis with MINT Protocol; see also gov-contracts-mcp, brand-intel-mcp, patent-intel-mcp.")
_KEYWORDS = ["financial data", "stock screening", "insider trading", "earnings analysis",
             "institutional ownership", "financial ratios", "market intelligence", "alternative data"]

_AGENT_CARD = {
    "name": "Financial Signals MCP",
    "description": ("Analyze S&P 500 stocks with derived signals — insider trading, earnings "
                    "surprises, institutional ownership, financial ratios, and macro — distilled "
                    "from SEC filings and market data."),
    "url": "https://financial-signals-mcp-production.up.railway.app/mcp",
    "version": "1.0.0",
    "capabilities": {"tools": ["insider_activity", "earnings_check", "institutional_moves",
                               "screen_stocks", "sector_snapshot", "macro_dashboard",
                               "company_profile", "anomaly_alert", "daily_brief", "mint_info"]},
    "provider": {"name": "FoundryNet", "url": "https://foundrynet.io"},
    "network": "FoundryNet Data Network",
    "attestation": {"protocol": "MINT Protocol",
                    "endpoint": "https://mint-mcp-production.up.railway.app/mcp",
                    "verified_outputs": True, "live_feed": "https://mint.foundrynet.io/feed", "feed_api": "https://mint-mcp-production.up.railway.app/v1/feed"},
    "protocols": {"mcp": {"endpoint": config.PUBLIC_MCP_URL, "transport": "streamable-http", "tools_count": 10},
                  "x402": {"supported": True, "currency": "USDC", "network": "solana"}},
    "see_also": config.SISTER_SERVERS, "mint_protocol": config.MINT_MCP_URL,
    "contact": "hello@foundrynet.io",
}


@mcp.custom_route("/.well-known/agent-card.json", methods=["GET"])
async def agent_card(request: Request) -> JSONResponse:
    return JSONResponse(_AGENT_CARD, headers={"Cache-Control": "public, max-age=300"})


@mcp.custom_route("/.well-known/mcp", methods=["GET"])
async def mcp_endpoints(request: Request) -> JSONResponse:
    return JSONResponse({"endpoints": [{"url": config.PUBLIC_MCP_URL, "transport": "streamable-http",
                                        "name": "Financial Signals MCP"}]},
                        headers={"Cache-Control": "public, max-age=300"})


async def _live_tools() -> list:
    res = mcp.list_tools()
    if inspect.iscoroutine(res):
        res = await res
    return [{"name": t.name, "description": (getattr(t, "description", "") or "").strip(),
             "inputSchema": getattr(t, "parameters", None) or {"type": "object"}} for t in res]


@mcp.custom_route("/.well-known/mcp/server-card.json", methods=["GET"])
async def server_card(request: Request) -> JSONResponse:
    live = await _live_tools()
    return JSONResponse({
        "serverInfo": {"name": "Financial Signals MCP", "version": "1.0.0"},
        "authentication": {"type": "http", "scheme": "bearer",
                           "description": ("macro_dashboard and mint_info are free; other tools give 25 "
                                           "free queries/day then take an fnet_ Bearer key OR x402 USDC.")},
        "tools": live, "version": "1.0", "name": "Financial Signals MCP",
        "tagline": _TAGLINE, "description": _DESC,
        "serverUrl": config.PUBLIC_MCP_URL, "transport": "streamable-http",
        "tools_count": len(live),
        "categories": ["finance", "data", "trading", "research", "alternative-data"],
        "keywords": _KEYWORDS, "network": "FoundryNet Data Network",
        "see_also": config.SISTER_SERVERS,
        "pricing": {"model": "metered",
                    "free_tier": f"{config.FREE_TIER_DAILY} queries/day + free macro_dashboard",
                    "paid_from": f"{config.PRICE_INSIDER} USDC per query (x402)"},
    }, headers={"Cache-Control": "public, max-age=300"})


# ── Daily aggregation (after US close ≈ AGG_HOUR_UTC) ────────────────────────
async def _agg_loop():
    while True:
        now = time.gmtime()
        secs = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
        wait = (config.AGG_HOUR_UTC * 3600 - secs) % 86400 or 86400
        try:
            await asyncio.sleep(wait)
            if supa.configured():
                await agg.run_aggregation()
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"agg loop error: {e}")
            await asyncio.sleep(3600)


_FREE_TOOL_NAMES = {"mint_info", "macro_dashboard", "cve_detail", "detail",
                    "domain_age", "convert", "rates", "market_overview", "price",
                    "quote", "batch_quote", "sector_performance"}


@mcp.custom_route("/.well-known/mcp.json", methods=["GET"])
async def wellknown_mcp_json(request: Request) -> JSONResponse:
    """Machine-discovery card (emerging standard) for AI clients/crawlers."""
    live = await _live_tools()
    names = [t["name"] for t in live]
    return JSONResponse({
        "name": _AGENT_CARD["name"],
        "description": _AGENT_CARD["description"],
        "url": config.PUBLIC_MCP_URL,
        "transport": ["streamable-http"],
        "tools": names,
        "pricing": {"model": "per-query", "free_tier": True,
                    "paid_tools": [n for n in names if n not in _FREE_TOOL_NAMES]},
        "attestation": {"enabled": True, "protocol": "MINT Protocol",
                        "feed": "https://mint.foundrynet.io/feed"},
        "network": {"name": "FoundryNet Data Network", "servers": 17,
                    "homepage": "https://foundrynet.io"},
    }, headers={"Cache-Control": "public, max-age=300"})


def build_dual_app():
    main_app = mcp.http_app(transport="http", path="/mcp")
    sse_app = mcp.http_app(transport="sse", path="/sse")
    for r in sse_app.routes:
        if getattr(r, "path", None) in ("/sse", "/messages"):
            main_app.router.routes.append(r)
    main_life, sse_life = main_app.router.lifespan_context, sse_app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def _dual_lifespan(app):
        async with main_life(app):
            async with sse_life(app):
                task = asyncio.create_task(_agg_loop())
                brief_task = asyncio.create_task(daily_curator.curator_loop())
                try:
                    yield
                finally:
                    for t in (task, brief_task):
                        t.cancel()
                        with contextlib.suppress(Exception):
                            await t
    main_app.router.lifespan_context = _dual_lifespan
    return main_app


if __name__ == "__main__":
    import uvicorn
    logger.info(f"financial-signals-mcp starting on 0.0.0.0:{config.PORT} "
                f"(dataset={'supabase' if supa.configured() else 'off'}, x402={config.X402_ENABLED})")
    uvicorn.run(build_dual_app(), host="0.0.0.0", port=config.PORT, log_level="warning")
