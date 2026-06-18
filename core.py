"""Shared logic behind the MCP tools + REST routes: the 8 operations + the x402
gating. Paid tools run payment_gate.precheck(price) first; macro_dashboard and
mint_info are free. Sector snapshots and anomalies are computed on the fly from
the derived signal tables.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta, timezone

import config
import payment_gate
import supa

logger = logging.getLogger("fin.core")


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def _billing(d: dict) -> dict:
    g = d.get("gate")
    if g == "free":
        cap, cnt = d.get("cap"), d.get("count")
        return {"tier": "free", "used_today": cnt, "daily_free": cap,
                "remaining_today": (cap - cnt) if (cap is not None and cnt is not None) else None}
    if g == "paid":
        return {"tier": "paid", "charged_usdc": d.get("amount_usdc")}
    if g == "api_key":
        return {"tier": "api_key", "note": "billed to your Forge account"}
    return {"tier": "free", "note": "gating inert"}


async def _gate(tool, params, price, agent_key, payment_tx, api_key):
    return await payment_gate.precheck(tool, params, price, agent_key, payment_tx, api_key)


# ── insider_activity ──────────────────────────────────────────────────────────
async def do_insider(ticker, days_back, signal_type, *, agent_key, payment_tx=None, api_key=None):
    params = {k: v for k, v in {"ticker": (ticker or "").upper() or None,
                                "days_back": days_back, "signal_type": signal_type}.items() if v}
    dec = await _gate("insider_activity", params, config.PRICE_INSIDER, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    rows = await supa.insider(ticker=ticker, days_from=_days_ago(int(days_back)) if days_back else None,
                              signal_type=signal_type)
    patterns = [r for r in rows if r.get("signal_type")]
    return {"results": rows, "count": len(rows), "patterns_detected": len(patterns),
            "billing": _billing(dec)}


# ── earnings_check ────────────────────────────────────────────────────────────
async def do_earnings(ticker, *, agent_key, payment_tx=None, api_key=None):
    if not ticker:
        return {"error": "bad_request", "detail": "ticker is required"}
    dec = await _gate("earnings_check", {"ticker": ticker.upper()}, config.PRICE_EARNINGS,
                      agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    rows = await supa.earnings(ticker, limit=8)
    latest = rows[0] if rows else {}
    return {"ticker": ticker.upper(), "quarters": rows,
            "beat_streak": latest.get("beat_streak"),
            "historical_surprise_avg_4q": latest.get("historical_surprise_avg_4q"),
            "next_earnings_date": latest.get("next_earnings_date"),
            "signal": latest.get("signal"), "billing": _billing(dec)}


# ── institutional_moves ───────────────────────────────────────────────────────
async def do_institutional(ticker, institution, signal_type, min_value, *,
                           agent_key, payment_tx=None, api_key=None):
    params = {k: v for k, v in {"ticker": (ticker or "").upper() or None, "institution": institution,
                                "signal_type": signal_type, "min_value": min_value}.items() if v}
    dec = await _gate("institutional_moves", params, config.PRICE_INSTITUTIONAL, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    rows = await supa.institutional(ticker=ticker, institution=institution,
                                    signal_type=signal_type, min_value=min_value)
    return {"results": rows, "count": len(rows), "billing": _billing(dec)}


# ── screen_stocks ─────────────────────────────────────────────────────────────
async def do_screen(filters, *, agent_key, payment_tx=None, api_key=None):
    params = {k: v for k, v in (filters or {}).items() if v not in (None, "")}
    dec = await _gate("screen_stocks", params, config.PRICE_SCREEN, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    rows = await supa.ratios(**params)
    return {"results": rows, "count": len(rows),
            "note": "sorted by composite_value_score (proprietary) unless sort_by set",
            "billing": _billing(dec)}


# ── sector_snapshot ───────────────────────────────────────────────────────────
async def do_sector(sector, *, agent_key, payment_tx=None, api_key=None):
    if not sector:
        return {"error": "bad_request", "detail": "sector is required"}
    dec = await _gate("sector_snapshot", {"sector": sector}, config.PRICE_SECTOR, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    rows = await supa.ratios_by_sector(sector)
    if not rows:
        return {"sector": sector, "companies": 0, "note": "no data for this sector yet",
                "billing": _billing(dec)}

    def med(col):
        vals = [r[col] for r in rows if r.get(col) is not None]
        return round(statistics.median(vals), 2) if vals else None

    scored = [r for r in rows if r.get("composite_value_score") is not None]
    scored.sort(key=lambda r: r["composite_value_score"], reverse=True)
    growths = [r["earnings_growth_yoy"] for r in rows if r.get("earnings_growth_yoy") is not None]
    return {
        "sector": sector, "companies": len(rows),
        "median_ratios": {"pe": med("pe_ratio"), "ps": med("ps_ratio"), "pb": med("pb_ratio"),
                          "ev_ebitda": med("ev_ebitda"), "net_margin": med("net_margin"),
                          "dividend_yield": med("dividend_yield")},
        "top_by_value_score": [{"ticker": r["ticker"], "company": r.get("company"),
                                "score": r["composite_value_score"]} for r in scored[:5]],
        "bottom_by_value_score": [{"ticker": r["ticker"], "company": r.get("company"),
                                   "score": r["composite_value_score"]} for r in scored[-5:]],
        "median_earnings_growth_yoy": round(statistics.median(growths), 2) if growths else None,
        "billing": _billing(dec),
    }


# ── macro_dashboard (FREE) ────────────────────────────────────────────────────
async def do_macro():
    rows = await supa.macro()
    return {"indicators": rows, "count": len(rows),
            "note": "FoundryNet Data Network — free macro gateway", "billing": {"tier": "free"}}


# ── company_profile ───────────────────────────────────────────────────────────
async def do_company(ticker, *, agent_key, payment_tx=None, api_key=None):
    if not ticker:
        return {"error": "bad_request", "detail": "ticker is required"}
    t = ticker.upper()
    dec = await _gate("company_profile", {"ticker": t}, config.PRICE_COMPANY, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    ratio = await supa.ratio_one(t)
    insiders = await supa.insider(ticker=t, limit=50)
    insts = await supa.institutional(ticker=t, limit=50)
    earn = await supa.earnings(t, limit=8)
    ins_buys = sum(1 for r in insiders if r.get("transaction_type") == "buy")
    ins_sells = sum(1 for r in insiders if r.get("transaction_type") == "sell")
    top_holders = sorted(insts, key=lambda r: (r.get("value_current_usd") or 0), reverse=True)[:5]
    return {
        "ticker": t, "company": (ratio or {}).get("company"),
        "sector": (ratio or {}).get("sector"),
        "composite_value_score": (ratio or {}).get("composite_value_score"),
        "ratios": ratio,
        "sector_positioning": {"pe_vs_sector": (ratio or {}).get("pe_vs_sector"),
                               "pe_vs_sector_pct": (ratio or {}).get("pe_vs_sector_pct"),
                               "sector_pe_median": (ratio or {}).get("sector_pe_median")},
        "insider_summary": {"buys": ins_buys, "sells": ins_sells,
                            "recent_signals": [r["context"] for r in insiders if r.get("context")][:5]},
        "institutional_concentration": {"holders_tracked": len(insts),
                                        "top_holders": [{"name": r.get("institution_name"),
                                                         "value_usd": r.get("value_current_usd")}
                                                        for r in top_holders]},
        "earnings_track_record": {"beat_streak": (earn[0] if earn else {}).get("beat_streak"),
                                  "avg_surprise_4q": (earn[0] if earn else {}).get("historical_surprise_avg_4q"),
                                  "next_earnings_date": (earn[0] if earn else {}).get("next_earnings_date"),
                                  "recent_quarters": len(earn)},
        "billing": _billing(dec),
    }


# ── anomaly_alert (premium) ───────────────────────────────────────────────────
_SEV = {"low": 1, "medium": 2, "high": 3}


async def do_anomaly(min_severity, *, agent_key, payment_tx=None, api_key=None):
    sev_floor = _SEV.get((min_severity or "low").lower(), 1)
    dec = await _gate("anomaly_alert", {"min_severity": min_severity or "low"},
                      config.PRICE_ANOMALY, agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    since = _days_ago(3)  # since last daily run(s)
    anomalies = []

    ins = await supa.recent_since("insider_signals", "created_at", since + "T00:00:00",
                                  extra={"signal_type": "not.is.null"})
    for r in ins:
        st = r.get("signal_type")
        sev = 3 if st == "cluster_sell" else (2 if st in ("large_buy", "ceo_buy") else 1)
        if sev >= sev_floor:
            anomalies.append({"type": "insider", "severity": _sev_name(sev), "ticker": r.get("ticker"),
                              "signal_type": st, "context": r.get("context")})

    inst = await supa.recent_since("institutional_signals", "updated_at", since + "T00:00:00",
                                   extra={"signal_type": "in.(exit,significant_decrease)"})
    for r in inst:
        anomalies.append({"type": "institutional", "severity": "high" if r.get("signal_type") == "exit" else "medium",
                          "ticker": r.get("ticker"), "signal_type": r.get("signal_type"),
                          "context": r.get("context")})

    earn = await supa.recent_since("earnings_signals", "updated_at", since + "T00:00:00")
    for r in earn:
        surp = r.get("eps_surprise_pct")
        if surp is not None and abs(surp) >= 10:
            sev = 3 if abs(surp) >= 25 else 2
            if sev >= sev_floor:
                anomalies.append({"type": "earnings", "severity": _sev_name(sev), "ticker": r.get("ticker"),
                                  "signal_type": "earnings_divergence", "context": r.get("signal")})

    order = {"high": 3, "medium": 2, "low": 1}
    anomalies.sort(key=lambda a: order.get(a["severity"], 0), reverse=True)
    return {"since": since, "count": len(anomalies), "anomalies": anomalies[:100],
            "billing": _billing(dec)}


def _sev_name(n):
    return {1: "low", 2: "medium", 3: "high"}.get(n, "low")


# ── mint_info (FREE) ──────────────────────────────────────────────────────────
def mint_info() -> dict:
    return {
        "network": "FoundryNet Data Network",
        "message": "Attest your agent's financial analysis with MINT Protocol for verifiable proof of work.",
        "positioning": ("A free-tier alternative to enterprise financial data (FactSet, "
                        "Morningstar, S&P Capital IQ) — financial intelligence for agents "
                        "without enterprise subscriptions."),
        "mint_protocol": {"mcp_endpoint": config.MINT_MCP_URL, "info_url": config.MINT_INFO_URL,
                          "tools": ["mint_register", "mint_attest", "mint_verify",
                                    "mint_rate", "mint_recommend", "mint_discover"]},
        "see_also": config.SISTER_SERVERS,
    }
