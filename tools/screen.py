from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def screen_stocks(
        sector: Optional[str] = None,
        min_market_cap: Optional[float] = None,
        max_pe: Optional[float] = None,
        min_dividend_yield: Optional[float] = None,
        min_value_score: Optional[float] = None,
        sort_by: Optional[str] = None,
        limit: int = 50,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Screen stocks by fundamentals — full ratio profile with sector
        comparison, ranked by the proprietary composite_value_score (a blend of
        valuation-vs-sector, growth, margin quality, insider sentiment,
        institutional momentum, and earnings consistency). Sorting by value score
        is YOUR proprietary ranking.

        PAID: $0.01 USDC per query after the daily free allowance (25/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            sector: GICS sector filter, partial match (e.g. "Technology").
            min_market_cap: minimum market cap (USD).
            max_pe: maximum trailing P/E.
            min_dividend_yield: minimum dividend yield (percent, e.g. 2.5).
            min_value_score: minimum composite_value_score (0-100).
            sort_by: value_score | market_cap | pe | dividend_yield | revenue_growth.
            limit: max rows (1-200, default 50).
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        filters = {"sector": sector, "min_market_cap": min_market_cap, "max_pe": max_pe,
                   "min_dividend_yield": min_dividend_yield, "min_value_score": min_value_score,
                   "sort_by": sort_by or "composite_value_score", "limit": limit}
        return await core.do_screen(filters, agent_key=identity.resolve_agent_key(agent_id),
                                    payment_tx=payment_tx, api_key=identity.bearer())
