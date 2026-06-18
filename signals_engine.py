"""The derived-intelligence engine — turns free raw data (yfinance + FRED) into
SIGNALS: insider patterns, earnings surprises/streaks, institutional moves, ratio
screens with sector context, macro percentiles, and the proprietary
composite_value_score. All functions are synchronous + defensive (yfinance fields
are inconsistent), returning partial data rather than raising.
"""
from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime, timezone

import config

logger = logging.getLogger("fin.engine")


def _f(v):
    """Safe float; None on NaN/None/bad."""
    try:
        if v is None:
            return None
        x = float(v)
        return None if math.isnan(x) or math.isinf(x) else x
    except (TypeError, ValueError):
        return None


def _pct(v):
    x = _f(v)
    return round(x * 100, 2) if x is not None else None


def _isodate(v):
    try:
        if v is None:
            return None
        if hasattr(v, "date"):
            return v.date().isoformat()
        return str(v)[:10]
    except Exception:  # noqa: BLE001
        return None


# ── ratios (ratio_screens, pre sector-median + score) ─────────────────────────
def compute_ratios(ticker: str, company: str, sector: str, info: dict) -> dict:
    mc = _f(info.get("marketCap"))
    fcf = _f(info.get("freeCashflow"))
    return {
        "ticker": ticker, "company": info.get("longName") or company,
        "sector": info.get("sector") or sector, "market_cap": mc,
        "pe_ratio": _f(info.get("trailingPE")),
        "ps_ratio": _f(info.get("priceToSalesTrailing12Months")),
        "pb_ratio": _f(info.get("priceToBook")),
        "ev_ebitda": _f(info.get("enterpriseToEbitda")),
        "revenue_growth_yoy": _pct(info.get("revenueGrowth")),
        "earnings_growth_yoy": _pct(info.get("earningsGrowth") if info.get("earningsGrowth") is not None
                                    else info.get("earningsQuarterlyGrowth")),
        "gross_margin": _pct(info.get("grossMargins")),
        "operating_margin": _pct(info.get("operatingMargins")),
        "net_margin": _pct(info.get("profitMargins")),
        "roe": _pct(info.get("returnOnEquity")),
        "roic": _pct(info.get("returnOnAssets")),  # ROA proxy for capital efficiency
        "debt_to_equity": _f(info.get("debtToEquity")),
        "dividend_yield": _pct(info.get("dividendYield")) if _f(info.get("dividendYield")) and _f(info.get("dividendYield")) < 1 else _f(info.get("dividendYield")),
        "payout_ratio": _pct(info.get("payoutRatio")),
        "free_cash_flow_yield": round(fcf / mc * 100, 2) if (fcf and mc) else None,
    }


# ── earnings (earnings_signals) ───────────────────────────────────────────────
def compute_earnings(ticker: str, company: str, tk) -> tuple[list, str | None]:
    rows, next_date = [], None
    try:
        ed = tk.earnings_dates
    except Exception:  # noqa: BLE001
        ed = None
    if ed is None or getattr(ed, "empty", True):
        return rows, next_date
    now = datetime.now(timezone.utc)
    surprises, past = [], []
    for idx, r in ed.iterrows():
        try:
            dt = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
            dtt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:  # noqa: BLE001
            continue
        reported = _f(r.get("Reported EPS"))
        est = _f(r.get("EPS Estimate"))
        surp = _f(r.get("Surprise(%)"))
        if dtt > now and reported is None:
            if next_date is None or dtt < next_date:
                next_date = dtt
            continue
        if reported is not None or surp is not None:
            past.append((dtt, est, reported, surp))
    past.sort(key=lambda x: x[0], reverse=True)
    # beat streak over chronological order
    streak = 0
    for _, _, _, surp in past:
        if surp is None:
            break
        if surp > 0:
            streak = streak + 1 if streak >= 0 else 1
        elif surp < 0:
            streak = streak - 1 if streak <= 0 else -1
        else:
            break
    for _, _, surp_ in [(p[0], p[1], p[3]) for p in past][:4]:
        if surp_ is not None:
            surprises.append(surp_)
    avg4 = round(statistics.mean(surprises), 2) if surprises else None
    nxt = next_date.date().isoformat() if next_date else None
    # Emit up to 8 past quarters; summary fields (streak/avg/next/signal) on the
    # latest row only (older rows carry just their point-in-time surprise).
    for i, (dtt, est, reported, surp) in enumerate(past[:8]):
        latest = i == 0
        rows.append({
            "ticker": ticker, "company": company, "report_date": dtt.date().isoformat(),
            "fiscal_quarter": f"{dtt.year}Q{(dtt.month - 1)//3 + 1}",
            "eps_actual": reported, "eps_estimate": est, "eps_surprise_pct": surp,
            "revenue_actual": None, "revenue_estimate": None, "revenue_surprise_pct": None,
            "beat_streak": streak if latest else None,
            "guidance_direction": "none" if latest else None,
            "post_earnings_move_pct": None,
            "historical_surprise_avg_4q": avg4 if latest else None,
            "next_earnings_date": nxt if latest else None,
            "signal": _earnings_signal(surp, streak) if latest else None,
        })
    return rows, nxt


def _earnings_signal(surp, streak) -> str:
    parts = []
    if surp is not None:
        parts.append(f"{'Beat' if surp >= 0 else 'Missed'} EPS by {abs(surp):.1f}%")
    if streak and abs(streak) >= 2:
        parts.append(f"{abs(streak)} consecutive {'beats' if streak > 0 else 'misses'}")
    return ", ".join(parts) or "No recent surprise data"


# ── insider (insider_signals) ─────────────────────────────────────────────────
def compute_insider(ticker: str, company: str, tk, next_earnings: str | None) -> list:
    try:
        df = tk.insider_transactions
    except Exception:  # noqa: BLE001
        df = None
    if df is None or getattr(df, "empty", True):
        return []
    recs = []
    for _, r in df.iterrows():
        txt = str(r.get("Transaction") or r.get("Text") or "")
        ttype = _classify_txn(txt)
        shares = _f(r.get("Shares"))
        value = _f(r.get("Value"))
        date = _isodate(r.get("Start Date") or r.get("Date"))
        recs.append({
            "ticker": ticker, "company": company,
            "insider_name": str(r.get("Insider") or "").strip() or None,
            "insider_title": str(r.get("Position") or "").strip() or None,
            "transaction_type": ttype, "shares": shares, "value_usd": value,
            "transaction_date": date,
            "shares_remaining": _f(r.get("Ownership")),
            "ownership_change_pct": None, "price_at_transaction": None,
            "days_to_next_earnings": _days_between(date, next_earnings),
        })
    # signal typing across the set
    sells = [r for r in recs if r["transaction_type"] == "sell" and r["transaction_date"]]
    cluster = _cluster_dates([r["transaction_date"] for r in sells], window_days=5, min_n=3)
    for r in recs:
        r["signal_type"], r["context"] = _insider_signal(r, recs, cluster)
    return [r for r in recs if r["transaction_date"]]


def _classify_txn(txt: str) -> str:
    t = txt.lower()
    if "exerc" in t:
        return "exercise"
    if any(k in t for k in ("purchase", "buy", "acqui", "bought")):
        return "buy"
    if any(k in t for k in ("sale", "sell", "sold", "disposition")):
        return "sell"
    return "other"


def _insider_signal(r, allrecs, cluster) -> tuple[str | None, str]:
    title = (r.get("insider_title") or "").lower()
    is_ceo = "ceo" in title or "chief executive" in title
    val = r.get("value_usd") or 0
    d2e = r.get("days_to_next_earnings")
    pre = d2e is not None and 0 <= d2e <= 14
    if r["transaction_type"] == "sell" and r["transaction_date"] in cluster:
        n = cluster[r["transaction_date"]]
        return "cluster_sell", f"Cluster sell: {n} insiders sold within 5 days{' ahead of earnings' if pre else ''}"
    if r["transaction_type"] == "buy" and is_ceo:
        return "ceo_buy", f"CEO bought ${val:,.0f}" if val else "CEO purchase"
    if r["transaction_type"] == "buy" and val and val >= 1_000_000:
        return "large_buy", f"Large insider buy: ${val:,.0f}"
    if pre and r["transaction_type"] in ("buy", "sell"):
        return "pre_earnings", f"Insider {r['transaction_type']} {d2e} days before earnings"
    return None, ""


def _cluster_dates(dates, window_days, min_n) -> dict:
    """Map each date to the count of transactions within a window_days span, when
    that span has >= min_n transactions."""
    ds = sorted(d for d in dates if d)
    out = {}
    from datetime import date as _date
    parsed = []
    for d in ds:
        try:
            parsed.append(_date.fromisoformat(d))
        except Exception:  # noqa: BLE001
            pass
    for i, d in enumerate(parsed):
        n = sum(1 for o in parsed if 0 <= (d - o).days <= window_days or 0 <= (o - d).days <= window_days)
        if n >= min_n:
            out[d.isoformat()] = n
    return out


def _days_between(d1, d2) -> int | None:
    from datetime import date as _date
    try:
        return (_date.fromisoformat(d2) - _date.fromisoformat(d1)).days
    except Exception:  # noqa: BLE001
        return None


# ── institutional (institutional_signals) ─────────────────────────────────────
def compute_institutional(ticker: str, company: str, tk, prev: dict) -> list:
    try:
        df = tk.institutional_holders
    except Exception:  # noqa: BLE001
        df = None
    if df is None or getattr(df, "empty", True):
        return []
    rows = []
    for _, r in df.iterrows():
        name = str(r.get("Holder") or "").strip()
        if not name:
            continue
        shares = _f(r.get("Shares"))
        value = _f(r.get("Value"))
        pdate = _isodate(r.get("Date Reported"))
        p = prev.get(name)
        sprev = _f(p.get("shares_current")) if p else None
        vprev = _f(p.get("value_current_usd")) if p else None
        sdelta = (shares - sprev) if (shares is not None and sprev is not None) else None
        vdelta = (value - vprev) if (value is not None and vprev is not None) else None
        sig, ctx = _inst_signal(name, shares, sprev, sdelta, value, vdelta)
        rows.append({
            "ticker": ticker, "company": company, "institution_name": name,
            "shares_current": shares, "shares_previous": sprev, "shares_delta": sdelta,
            "value_current_usd": value, "value_delta_usd": vdelta,
            "ownership_pct": _pct(r.get("pctHeld")) if r.get("pctHeld") is not None else _f(r.get("% Out")),
            "filing_date": pdate, "signal_type": sig, "context": ctx,
        })
    return rows


def _inst_signal(name, shares, sprev, sdelta, value, vdelta) -> tuple[str | None, str]:
    if sprev is None and shares:
        return "new_position", f"{name}: position of ${value:,.0f}" if value else f"{name}: new position"
    if shares == 0 and sprev:
        return "exit", f"{name} exited the position"
    if sdelta and sprev:
        chg = sdelta / sprev if sprev else 0
        if chg >= 0.25:
            return "significant_increase", f"{name} increased stake {chg*100:.0f}%"
        if chg <= -0.25:
            return "significant_decrease", f"{name} cut stake {abs(chg)*100:.0f}%"
    return None, ""


# ── composite_value_score (proprietary 0-100) ────────────────────────────────
def composite_score(ratio: dict, insider_rows: list, inst_rows: list,
                    earnings_rows: list, sector_pe_median) -> float | None:
    """Blend: valuation vs sector, growth, margin quality, insider sentiment,
    institutional momentum, earnings consistency. Transparent, weighted 0-100."""
    sub, wts = [], []

    pe = ratio.get("pe_ratio")
    if pe and sector_pe_median and pe > 0:
        ratio_v = pe / sector_pe_median
        val = _clamp(100 - (ratio_v - 1) * 100, 0, 100)  # cheaper than sector → higher
        sub.append(val); wts.append(0.25)

    g = _avg([ratio.get("revenue_growth_yoy"), ratio.get("earnings_growth_yoy")])
    if g is not None:
        sub.append(_clamp(50 + g, 0, 100)); wts.append(0.20)

    m = _avg([ratio.get("net_margin"), ratio.get("operating_margin")])
    if m is not None:
        sub.append(_clamp(m * 2.5, 0, 100)); wts.append(0.15)

    buy = sum((r.get("value_usd") or 0) for r in insider_rows if r["transaction_type"] == "buy")
    sell = sum((r.get("value_usd") or 0) for r in insider_rows if r["transaction_type"] == "sell")
    if buy or sell:
        net = buy - sell
        sub.append(_clamp(50 + (net / (buy + sell) * 50), 0, 100)); wts.append(0.15)

    inc = sum(1 for r in inst_rows if r.get("signal_type") in ("new_position", "significant_increase"))
    dec = sum(1 for r in inst_rows if r.get("signal_type") in ("exit", "significant_decrease"))
    if inc or dec:
        sub.append(_clamp(50 + (inc - dec) / (inc + dec) * 50, 0, 100)); wts.append(0.10)

    if earnings_rows:
        streak = earnings_rows[0].get("beat_streak") or 0
        sub.append(_clamp(50 + streak * 12, 0, 100)); wts.append(0.15)

    if not sub:
        return None
    tw = sum(wts)
    return round(sum(s * w for s, w in zip(sub, wts)) / tw, 1)


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _avg(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def sector_medians(ratios: list) -> dict:
    """sector -> {pe_median, ps_median} from a batch of ratio rows."""
    from collections import defaultdict
    pe, ps = defaultdict(list), defaultdict(list)
    for r in ratios:
        s = r.get("sector")
        if not s:
            continue
        if r.get("pe_ratio") and r["pe_ratio"] > 0:
            pe[s].append(r["pe_ratio"])
        if r.get("ps_ratio") and r["ps_ratio"] > 0:
            ps[s].append(r["ps_ratio"])
    out = {}
    for s in set(list(pe) + list(ps)):
        out[s] = {"pe": round(statistics.median(pe[s]), 2) if pe.get(s) else None,
                  "ps": round(statistics.median(ps[s]), 2) if ps.get(s) else None}
    return out


# ── macro (macro_signals via FRED) ────────────────────────────────────────────
async def fetch_macro(request_json) -> list:
    """FRED macro series → signals with trend + ~20yr percentile. Needs FRED_API_KEY."""
    if not config.FRED_API_KEY:
        logger.info("FRED_API_KEY unset — skipping macro")
        return []
    rows = []
    for sid, name in config.FRED_SERIES.items():
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {"series_id": sid, "api_key": config.FRED_API_KEY, "file_type": "json",
                  "sort_order": "desc", "limit": "5200"}  # ~20yr daily
        r = await request_json("GET", url, params=params, timeout=config.REQUEST_TIMEOUT)
        if not isinstance(r, dict) or "observations" not in r:
            logger.warning(f"FRED {sid} failed: {str(r)[:160]}")
            continue
        obs = [o for o in r["observations"] if o.get("value") not in (".", "", None)]
        vals = []
        for o in obs:
            try:
                vals.append(float(o["value"]))
            except (TypeError, ValueError):
                pass
        if len(vals) < 2:
            continue
        cur, prev = vals[0], vals[1]
        below = sum(1 for v in vals if v <= cur)
        pct = round(below / len(vals) * 100, 1)
        change = round((cur - prev) / abs(prev) * 100, 2) if prev else None
        trend = "rising" if cur > prev else ("falling" if cur < prev else "flat")
        rows.append({
            "fred_series_id": sid, "indicator_name": name,
            "current_value": cur, "previous_value": prev, "change_pct": change,
            "trend": trend, "historical_percentile": pct,
            "signal": _macro_signal(sid, name, cur, trend, pct),
        })
    return rows


def _macro_signal(sid, name, cur, trend, pct) -> str:
    if sid == "T10Y2Y":
        return (f"Yield curve INVERTED ({cur:.2f})" if cur < 0
                else f"Yield curve positive ({cur:.2f}), {trend}")
    band = "historically high" if pct >= 80 else ("historically low" if pct <= 20 else "mid-range")
    return f"{name} {cur:.2f}, {trend}, {band} ({pct:.0f}th pctile vs 20yr)"
