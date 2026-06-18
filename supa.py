"""Supabase PostgREST client for financial-signals-mcp (standalone project).

Reads the derived signal tables for the tools and upserts them from the
aggregator. Defensive: failures degrade to None/[]/{}/False.
"""
from __future__ import annotations

import logging
from typing import Optional

import config
from http_util import request_json

logger = logging.getLogger("fin.supa")


def configured() -> bool:
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)


def _headers(extra: Optional[dict] = None) -> dict:
    h = {"apikey": config.SUPABASE_SERVICE_KEY,
         "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
         "Content-Type": "application/json", "Accept": "application/json"}
    if extra:
        h.update(extra)
    return h


def _url(path: str) -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{path}"


async def select(table: str, params: dict) -> list:
    if not configured():
        return []
    r = await request_json("GET", _url(table), headers=_headers(),
                           params=params, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, list):
        return r
    logger.warning(f"select {table} failed: {r}")
    return []


async def upsert(table: str, rows: list, on_conflict: str) -> dict:
    if not configured() or not rows:
        return {"data": []}
    r = await request_json("POST", _url(table),
                           headers=_headers({"Prefer": "resolution=merge-duplicates,return=minimal"}),
                           params={"on_conflict": on_conflict},
                           body=rows, timeout=max(config.REQUEST_TIMEOUT, 60))
    if isinstance(r, dict) and r.get("error"):
        return r
    return {"data": rows}


async def rpc(fn: str, body: dict):
    if not configured():
        return None
    return await request_json("POST", _url(f"rpc/{fn}"), headers=_headers(),
                              body=body, timeout=config.REQUEST_TIMEOUT)


# ── reads for tools ───────────────────────────────────────────────────────────
async def insider(ticker=None, days_from=None, signal_type=None, limit=100) -> list:
    p = {"select": "*", "order": "transaction_date.desc", "limit": str(limit)}
    if ticker:
        p["ticker"] = f"eq.{ticker.upper()}"
    if signal_type:
        p["signal_type"] = f"eq.{signal_type}"
    if days_from:
        p["transaction_date"] = f"gte.{days_from}"
    return await select("insider_signals", p)


async def earnings(ticker: str, limit=8) -> list:
    return await select("earnings_signals",
                        {"select": "*", "ticker": f"eq.{ticker.upper()}",
                         "order": "report_date.desc", "limit": str(limit)})


async def institutional(ticker=None, institution=None, signal_type=None,
                        min_value=None, limit=100) -> list:
    p = {"select": "*", "order": "value_delta_usd.desc.nullslast", "limit": str(limit)}
    if ticker:
        p["ticker"] = f"eq.{ticker.upper()}"
    if institution:
        p["institution_name"] = f"ilike.*{institution}*"
    if signal_type:
        p["signal_type"] = f"eq.{signal_type}"
    if min_value is not None:
        p["value_current_usd"] = f"gte.{min_value}"
    return await select("institutional_signals", p)


async def ratios(*, sector=None, min_market_cap=None, max_pe=None,
                 min_dividend_yield=None, min_value_score=None,
                 sort_by="composite_value_score", limit=50) -> list:
    order_col = {"value_score": "composite_value_score", "composite_value_score": "composite_value_score",
                 "market_cap": "market_cap", "pe": "pe_ratio", "pe_ratio": "pe_ratio",
                 "dividend_yield": "dividend_yield", "revenue_growth": "revenue_growth_yoy"
                 }.get(sort_by, "composite_value_score")
    desc = order_col != "pe_ratio"
    p = {"select": "*", "order": f"{order_col}.{'desc' if desc else 'asc'}.nullslast",
         "limit": str(min(max(int(limit or 50), 1), 200))}
    if sector:
        p["sector"] = f"ilike.*{sector}*"
    if min_market_cap is not None:
        p["market_cap"] = f"gte.{min_market_cap}"
    if max_pe is not None:
        p["pe_ratio"] = f"lte.{max_pe}"
    if min_dividend_yield is not None:
        p["dividend_yield"] = f"gte.{min_dividend_yield}"
    if min_value_score is not None:
        p["composite_value_score"] = f"gte.{min_value_score}"
    return await select("ratio_screens", p)


async def ratios_by_sector(sector: str, limit=500) -> list:
    return await select("ratio_screens",
                        {"select": "*", "sector": f"ilike.*{sector}*", "limit": str(limit)})


async def ratio_one(ticker: str) -> Optional[dict]:
    rows = await select("ratio_screens", {"select": "*", "ticker": f"eq.{ticker.upper()}", "limit": "1"})
    return rows[0] if rows else None


async def macro() -> list:
    return await select("macro_signals", {"select": "*", "order": "indicator_name.asc"})


async def prev_institutional(ticker: str) -> dict:
    rows = await select("institutional_signals",
                        {"select": "institution_name,shares_current,value_current_usd",
                         "ticker": f"eq.{ticker.upper()}", "limit": "200"})
    return {r["institution_name"]: r for r in rows if r.get("institution_name")}


async def recent_since(table: str, date_col: str, since_iso: str, extra: Optional[dict] = None,
                       limit=500) -> list:
    p = {"select": "*", date_col: f"gte.{since_iso}", "limit": str(limit),
         "order": f"{date_col}.desc"}
    if extra:
        p.update(extra)
    return await select(table, p)


# ── free-tier + payments ──────────────────────────────────────────────────────
async def claim_free_query(agent_key: str, day: str, cap: int) -> Optional[dict]:
    r = await rpc("fin_claim_free_query", {"p_agent_key": agent_key, "p_day": day, "p_cap": cap})
    if isinstance(r, dict) and "allowed" in r:
        return r
    if isinstance(r, list) and r and isinstance(r[0], dict):
        return r[0]
    return None


async def payment_tx_used(tx_signature: str) -> bool:
    rows = await select("fin_payments", {"tx_signature": f"eq.{tx_signature}",
                                         "select": "tx_signature", "limit": "1"})
    return bool(rows)


async def insert_payment(row: dict) -> dict:
    if not configured():
        return {"error": "not_configured"}
    r = await request_json("POST", _url("fin_payments"),
                           headers=_headers({"Prefer": "return=minimal"}),
                           body=row, timeout=config.REQUEST_TIMEOUT)
    if isinstance(r, dict) and r.get("error"):
        return r
    return {"data": [row]}
