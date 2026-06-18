#!/usr/bin/env python3
"""financial_signals_aggregator — daily derived-signal computation (after US close,
~5pm PT). For each ticker in the universe it pulls free data (yfinance), computes
insider/earnings/institutional/ratio signals + the composite_value_score, derives
sector medians, and upserts the DERIVED tables. Macro signals come from FRED.

The MCP server runs run_aggregation() in-process daily; this is also the
standalone/manual entry point:
  python financial_signals_aggregator.py            # capped universe (FIN_MAX_TICKERS_PER_RUN)
  python financial_signals_aggregator.py 25         # first 25 tickers (seed/test)
  python financial_signals_aggregator.py AAPL MSFT  # specific tickers
"""
from __future__ import annotations

import asyncio
import logging
import sys
import warnings

import config
import signals_engine
import supa
from http_util import request_json

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("fin.agg")


def load_universe(limit=None, only=None) -> list:
    if only:
        return [(t.upper(), t.upper(), None) for t in only]
    if config.FIN_UNIVERSE:
        ts = [x.strip().upper() for x in config.FIN_UNIVERSE.split(",") if x.strip()]
        uni = [(t, t, None) for t in ts]
    else:
        from universe import SP500
        uni = list(SP500)
    cap = limit or config.FIN_MAX_TICKERS_PER_RUN
    return uni[:cap]


def process_ticker(t: str, company: str, sector: str, prev_inst: dict) -> dict:
    """Blocking yfinance work for one ticker → all derived signal pieces."""
    import yfinance as yf
    tk = yf.Ticker(t)
    try:
        info = tk.info or {}
    except Exception:  # noqa: BLE001
        info = {}
    ratio = signals_engine.compute_ratios(t, company, sector, info)
    earnings, next_e = signals_engine.compute_earnings(t, ratio["company"], tk)
    insider = signals_engine.compute_insider(t, ratio["company"], tk, next_e)
    inst = signals_engine.compute_institutional(t, ratio["company"], tk, prev_inst)
    return {"ratio": ratio, "earnings": earnings, "insider": insider, "institutional": inst}


async def run_aggregation(limit=None, only=None) -> dict:
    # Macro (independent of the ticker loop).
    macro_rows = await signals_engine.fetch_macro(request_json)
    if macro_rows:
        await supa.upsert("macro_signals", macro_rows, "fred_series_id")
    log.info(f"macro: {len(macro_rows)} indicators")

    universe = load_universe(limit, only)
    log.info(f"processing {len(universe)} tickers")
    per, all_ratios = {}, []
    ins_all, earn_all, inst_all, tick_rows = [], [], [], []

    for i, (t, c, s) in enumerate(universe):
        prev = await supa.prev_institutional(t)
        try:
            data = await asyncio.to_thread(process_ticker, t, c, s, prev)
        except Exception as e:  # noqa: BLE001
            log.warning(f"{t}: {e}")
            continue
        per[t] = data
        all_ratios.append(data["ratio"])
        ins_all.extend(data["insider"])
        earn_all.extend(data["earnings"])
        inst_all.extend(data["institutional"])
        tick_rows.append({"ticker": t, "company": data["ratio"].get("company"),
                          "sector": data["ratio"].get("sector")})
        if (i + 1) % 25 == 0:
            log.info(f"  …{i + 1}/{len(universe)}")

    # Sector medians + composite score (second pass).
    medians = signals_engine.sector_medians(all_ratios)
    ratio_rows = []
    for t, data in per.items():
        rr = data["ratio"]
        med = medians.get(rr.get("sector"), {})
        rr["sector_pe_median"], rr["sector_ps_median"] = med.get("pe"), med.get("ps")
        if rr.get("pe_ratio") and med.get("pe"):
            diff = (rr["pe_ratio"] - med["pe"]) / med["pe"] * 100
            rr["pe_vs_sector_pct"] = round(diff, 1)
            rr["pe_vs_sector"] = "premium" if diff > 5 else ("discount" if diff < -5 else "inline")
        rr["composite_value_score"] = signals_engine.composite_score(
            rr, data["insider"], data["institutional"], data["earnings"], med.get("pe"))
        ratio_rows.append(rr)

    # Upserts. Dedup each batch on its conflict key (PostgREST 500s if a single
    # request's ON CONFLICT target hits the same row twice) and chunk large sets.
    async def _push(table, rows, keys):
        seen, deduped = set(), []
        for r in rows:
            k = tuple(r.get(c) for c in keys.split(","))
            if k in seen:
                continue
            seen.add(k)
            deduped.append(r)
        # PostgREST bulk insert requires every object to share the same key set —
        # union all keys and fill missing with None.
        allkeys = set()
        for r in deduped:
            allkeys.update(r.keys())
        deduped = [{k: r.get(k) for k in allkeys} for r in deduped]
        for i in range(0, len(deduped), 500):
            res = await supa.upsert(table, deduped[i:i + 500], keys)
            if isinstance(res, dict) and res.get("error"):
                log.warning(f"upsert {table} chunk {i}: {str(res)[:200]}")

    await _push("tracked_tickers", tick_rows, "ticker")
    await _push("ratio_screens", ratio_rows, "ticker")
    if earn_all:
        await _push("earnings_signals", earn_all, "ticker,report_date")
    if inst_all:
        await _push("institutional_signals", inst_all, "ticker,institution_name,filing_date")
    if ins_all:
        ins_clean = [r for r in ins_all if r.get("transaction_date")]
        await _push("insider_signals", ins_clean,
                    "ticker,insider_name,transaction_date,shares,transaction_type")

    res = {"tickers": len(per), "ratios": len(ratio_rows), "insider": len(ins_all),
           "earnings": len(earn_all), "institutional": len(inst_all), "macro": len(macro_rows)}
    log.info(f"done: {res}")
    return res


async def main() -> None:
    args = [a for a in sys.argv[1:] if a.strip()]
    if args and args[0].isdigit():
        res = await run_aggregation(limit=int(args[0]))
    elif args:
        res = await run_aggregation(only=args)
    else:
        res = await run_aggregation()
    print(res)


if __name__ == "__main__":
    asyncio.run(main())
