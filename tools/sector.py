from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def sector_snapshot(
        sector: str,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Get a market-intelligence snapshot for a GICS sector — median financial
        ratios (P/E, P/S, P/B, EV/EBITDA, margins, yield), the top and bottom names
        by composite_value_score, and the aggregate earnings-growth trend, derived
        from SEC filings and market data across the S&P 500.

        PAID: $0.01 USDC per query after the daily free allowance (25/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            sector: GICS sector, e.g. "Information Technology", "Energy".
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_sector(sector, agent_key=identity.resolve_agent_key(agent_id),
                                    payment_tx=payment_tx, api_key=identity.bearer())
