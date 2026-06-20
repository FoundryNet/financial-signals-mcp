"""Daily curated brief — financial-signals.

Runs once a day at BRIEF_HOUR_UTC (05:00 UTC) as an in-process background task
(same shape as the aggregation loop). It queries the last 24h of derived signals,
ranks by significance, packages the top movers, attests the package through MINT
for verifiable provenance, and upserts it into the `daily_briefs` table. The paid
`daily_brief` tool just reads that row back.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import config
import mint_integration
import supa

logger = logging.getLogger("fin.curator")

SERVER = config.SERVER_SLUG
PRICE = config.PRICE_DAILY_BRIEF


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _expires_at(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (d + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")


def related_briefs(exclude: str) -> list:
    return [{"server": s, "price": p, "tool": "daily_brief"}
            for s, p in config.NETWORK_BRIEFS.items() if s != exclude]


async def _curate_signals(since_iso: str) -> tuple[dict, int]:
    """Build the financial brief body from the last 24h. Returns (signals, count)."""
    # Top insider anomalies (signal_type present), severity-ranked.
    ins = await supa.recent_since("insider_signals", "created_at", since_iso,
                                  extra={"signal_type": "not.is.null"})
    sev = {"cluster_sell": 3, "large_buy": 2, "ceo_buy": 2}
    ins.sort(key=lambda r: sev.get(r.get("signal_type"), 1), reverse=True)
    top_insider = [{"ticker": r.get("ticker"), "signal_type": r.get("signal_type"),
                    "context": r.get("context")} for r in ins[:5]]

    # Top earnings surprises by |eps_surprise_pct|.
    earn = await supa.recent_since("earnings_signals", "updated_at", since_iso)
    earn = [r for r in earn if r.get("eps_surprise_pct") is not None]
    earn.sort(key=lambda r: abs(r.get("eps_surprise_pct") or 0), reverse=True)
    top_earnings = [{"ticker": r.get("ticker"), "eps_surprise_pct": r.get("eps_surprise_pct"),
                     "signal": r.get("signal")} for r in earn[:5]]

    # Top institutional moves (exits/decreases) by position value.
    inst = await supa.recent_since("institutional_signals", "updated_at", since_iso,
                                   extra={"signal_type": "not.is.null"})
    inst.sort(key=lambda r: (r.get("value_current_usd") or 0), reverse=True)
    top_inst = [{"ticker": r.get("ticker"), "institution": r.get("institution_name"),
                 "signal_type": r.get("signal_type"), "value_usd": r.get("value_current_usd")}
                for r in inst[:3]]

    # Top 10 composite value-score movers (current screen).
    movers = await supa.ratios(sort_by="composite_value_score", limit=10)
    top_value = [{"ticker": r.get("ticker"), "company": r.get("company"),
                  "sector": r.get("sector"),
                  "composite_value_score": r.get("composite_value_score"),
                  "pe_ratio": r.get("pe_ratio")} for r in movers[:10]]

    # Macro summary.
    macro = await supa.macro()
    macro_summary = [{"indicator": r.get("indicator_name"), "value": r.get("value"),
                      "percentile": r.get("percentile")} for r in macro]

    signals = {
        "top_insider_anomalies": top_insider,
        "top_earnings_surprises": top_earnings,
        "top_institutional_moves": top_inst,
        "top_value_score_movers": top_value,
        "macro_summary": macro_summary,
    }
    count = len(top_insider) + len(top_earnings) + len(top_inst) + len(top_value) + len(macro_summary)
    return signals, count


async def run_curation(date_str: str | None = None) -> dict:
    """Generate, attest, and store today's brief. Idempotent per date (upsert)."""
    date_str = date_str or _today()
    since_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    signals, count = await _curate_signals(since_iso)

    brief = {
        "brief_date": date_str, "server": SERVER, "signal_count": count,
        "signals": signals, "expires_at": _expires_at(date_str),
        "related_briefs": related_briefs(SERVER),
    }
    # Attest for provenance (sync httpx → run off the event loop; fail-open).
    attestation = await asyncio.to_thread(
        mint_integration.attest_data, brief, "analysis",
        f"Daily {SERVER} brief: {count} signals")
    brief["provenance"] = attestation

    row = {
        "brief_date": date_str, "brief_data": brief, "signal_count": count,
        "attestation_hash": attestation.get("attestation_hash"),
        "expires_at": _expires_at(date_str),
    }
    res = await supa.upsert("daily_briefs", [row], "brief_date")
    if isinstance(res, dict) and res.get("error"):
        logger.warning(f"daily brief upsert failed: {str(res)[:200]}")
    else:
        logger.info(f"daily brief stored: {date_str} ({count} signals, "
                    f"attested={attestation.get('mint_verified')})")
    return brief


async def get_brief(date_str: str | None = None) -> dict | None:
    """Read a stored brief; None if missing or expired."""
    date_str = date_str or _today()
    rows = await supa.select("daily_briefs",
                             {"select": "*", "brief_date": f"eq.{date_str}", "limit": "1"})
    if not rows:
        return None
    row = rows[0]
    exp = row.get("expires_at")
    if exp:
        try:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(exp.replace("Z", "+00:00")):
                return None
        except Exception:  # noqa: BLE001
            pass
    return row.get("brief_data")


async def bump_purchase(date_str: str) -> None:
    """Best-effort purchase counter via RPC (no-op if the function is absent)."""
    try:
        await supa.rpc("increment_brief_purchase", {"p_brief_date": date_str})
    except Exception:  # noqa: BLE001
        pass


async def curator_loop() -> None:
    """Sleep until BRIEF_HOUR_UTC each day, then curate. Cancellable."""
    while True:
        now = datetime.now(timezone.utc)
        secs = now.hour * 3600 + now.minute * 60 + now.second
        wait = (config.BRIEF_HOUR_UTC * 3600 - secs) % 86400 or 86400
        try:
            await asyncio.sleep(wait)
            if supa.configured():
                await run_curation()
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            logger.warning(f"curator loop error: {e}")
            await asyncio.sleep(3600)
