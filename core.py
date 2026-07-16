"""Shared logic behind the MCP tools + REST routes: the 8 operations + the x402
gating. Paid tools run payment_gate.precheck(price) first; macro_dashboard and
mint_info are free. Sector snapshots and anomalies are computed on the fly from
the derived signal tables.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from datetime import datetime, timedelta, timezone

import config
import daily_curator
import mint_integration
import payment_gate
import stripe_gate
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
    result = {"since": since, "count": len(anomalies), "anomalies": anomalies[:100],
              "billing": _billing(dec)}
    # Provenance attestation (additive; fail-open; off the event loop).
    result["provenance"] = await asyncio.to_thread(
        mint_integration.attest_data, result, "analysis", "anomaly_alert query result")
    return result


# ── daily_brief (premium, curated) ────────────────────────────────────────────
async def do_daily_brief(date, *, agent_key, payment_tx=None, api_key=None,
                         stripe_token=None):
    day = (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()

    # Stripe rail (parallel to x402): a paid Checkout Session unlocks the brief.
    stripe_err = None
    if stripe_token and stripe_gate.is_active():
        sv = await stripe_gate.verify_session(stripe_token, config.PRICE_DAILY_BRIEF,
                                              tool="daily_brief", agent_key=agent_key)
        if sv["ok"]:
            brief = await daily_curator.get_brief(day)
            if not brief:
                return {"error": "not_available",
                        "detail": f"No brief for {day} (not yet generated, or expired at midnight UTC). "
                                  f"Briefs are curated daily at {config.BRIEF_HOUR_UTC:02d}:00 UTC.",
                        "billing": "stripe"}
            await daily_curator.bump_purchase(day)
            return {**brief, "billing": "stripe", "stripe_session": sv["session"]}
        stripe_err = sv.get("detail")  # surface on the 402 below

    dec = await _gate("daily_brief", {"date": day}, config.PRICE_DAILY_BRIEF,
                      agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return stripe_gate.augment_402(dec["body"], config.PRICE_DAILY_BRIEF,
                                       stripe_error=stripe_err)
    brief = await daily_curator.get_brief(day)
    if not brief:
        return {"error": "not_available",
                "detail": f"No brief for {day} (not yet generated, or expired at midnight UTC). "
                          f"Briefs are curated daily at {config.BRIEF_HOUR_UTC:02d}:00 UTC.",
                "billing": _billing(dec)}
    await daily_curator.bump_purchase(day)
    return {**brief, "billing": _billing(dec)}


def _sev_name(n):
    return {1: "low", 2: "medium", 3: "high"}.get(n, "low")


# ── mint_info (FREE) ──────────────────────────────────────────────────────────
def mint_info() -> dict:
    return {
        "network": "FoundryNet Data Network", **mint_integration.network_feed_block(),
        "message": "Attest your agent's financial analysis with MINT Protocol for verifiable proof of work.",
        "positioning": ("A free-tier alternative to enterprise financial data (FactSet, "
                        "Morningstar, S&P Capital IQ) — financial intelligence for agents "
                        "without enterprise subscriptions."),
        "mint_protocol": {"mcp_endpoint": config.MINT_MCP_URL, "info_url": config.MINT_INFO_URL,
                          "tools": ["mint_register", "mint_attest", "mint_verify",
                                    "mint_rate", "mint_recommend", "mint_discover"]},
        "see_also": config.SISTER_SERVERS,
    }


# ── Soft upsell: surface the daily_brief on every paid, non-brief response ─────
# Appends one non-blocking `available_intelligence` field to successful paid tool
# responses so the calling agent learns a single curated brief can replace many
# individual paid queries. Skips error and 402/payment_required bodies, and never
# touches daily_brief itself (no self-upsell). Brief status is cached 5 min, so
# this adds no per-call DB latency. Added 2026-06-20 (seller_agent v2 upsell hook).
import time as _upsell_time

_brief_upsell_cache = {"day": None, "ts": 0.0, "available": False, "count": 0}


async def _brief_status_cached() -> tuple[bool, int]:
    day = _upsell_time.strftime("%Y-%m-%d", _upsell_time.gmtime())
    now = _upsell_time.time()
    c = _brief_upsell_cache
    if c["day"] == day and (now - c["ts"]) < 300:
        return c["available"], c["count"]
    avail, count = False, 0
    try:
        brief = await daily_curator.get_brief(day)
        if brief:
            avail, count = True, int(brief.get("signal_count") or 0)
    except Exception:  # noqa: BLE001
        return c["available"], c["count"]
    c.update(day=day, ts=now, available=avail, count=count)
    return avail, count


async def _available_intelligence() -> dict:
    avail, count = await _brief_status_cached()
    return {"daily_brief": {
        "available": avail,
        "signal_count": count,
        "price_usd": config.PRICE_DAILY_BRIEF,
        "tool": "daily_brief",
        "note": "Curated daily intelligence — more efficient than individual queries",
    }}


def _make_upsell(_fn):
    import functools

    @functools.wraps(_fn)
    async def _wrapped(*a, **k):
        result = await _fn(*a, **k)
        if isinstance(result, dict) and "error" not in result and "payment_required" not in result:
            try:
                result["available_intelligence"] = await _available_intelligence()
            except Exception:  # noqa: BLE001
                pass
            try:
                import asyncio as _aio, mint_integration as _mint, upsell_engine as _upsell_engine
                _hb = await _aio.to_thread(_mint.network_heartbeat)
                _av, _ct = await _brief_status_cached()
                result["foundrynet_network"] = {**_hb, **_upsell_engine.get_upsell(
                    brief_price=config.PRICE_DAILY_BRIEF, brief_signal_count=(_ct if _av else None))}
            except Exception:  # noqa: BLE001
                pass
        return result

    return _wrapped


for _upsell_fn in ("do_insider", "do_earnings", "do_institutional", "do_screen", "do_sector", "do_company", "do_anomaly",):
    if _upsell_fn in globals():
        globals()[_upsell_fn] = _make_upsell(globals()[_upsell_fn])



# ── brief_summary ($0.50): structured top-5 sample of today's brief (upsell) ──
def _top_signals(brief: dict, n: int = 5) -> list:
    """Flatten a brief's signals into a flat top-N list — structure-agnostic
    (works whether `signals` is a dict-of-categories or a flat list)."""
    sig = (brief or {}).get("signals")
    items: list = []
    if isinstance(sig, dict):
        for cat, val in sig.items():
            if isinstance(val, list):
                for it in val:
                    items.append({"category": cat, **(it if isinstance(it, dict) else {"value": it})})
            elif isinstance(val, dict):
                items.append({"category": cat, **val})
            elif val not in (None, "", 0):
                items.append({"category": cat, "value": val})
    elif isinstance(sig, list):
        items = sig
    return items[:n]


async def do_brief_summary(date, *, agent_key, payment_tx=None, api_key=None):
    """Top-5 signals from today's brief as structured JSON (no prose) — the $0.50
    sample that upsells the full daily_brief."""
    from datetime import datetime, timezone
    day = (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
    dec = await payment_gate.precheck("brief_summary", {"date": day}, config.PRICE_BRIEF_SUMMARY,
                                      agent_key, payment_tx, api_key)
    if dec["gate"] == "blocked":
        return dec["body"]
    brief = await daily_curator.get_brief(day)
    if not brief:
        return {"error": "not_available",
                "detail": f"No brief for {day} yet (curated daily; expires next midnight UTC).",
                "billing": _billing(dec)}
    return {
        "date": day,
        "top_signals": _top_signals(brief, 5),
        "total_signals": brief.get("signal_count"),
        "full_brief": {"tool": "daily_brief", "price_usd": config.PRICE_DAILY_BRIEF,
                       "note": "Full brief returns all signals with complete detail + MINT attestation."},
        "billing": _billing(dec),
    }
