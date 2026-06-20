from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def earnings_check(
        ticker: str,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Check the earnings track record for an S&P 500 stock — 8 quarters of EPS
        surprises, the consecutive beat/miss streak, average surprise, guidance
        trend, and next earnings date, derived from SEC filings and market data.
        Earnings analysis and surprise signals for trading agents.

        PAID: $0.01 USDC per query after the daily free allowance (25/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            ticker: the stock ticker, e.g. "AAPL".
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_earnings(ticker, agent_key=identity.resolve_agent_key(agent_id),
                                      payment_tx=payment_tx, api_key=identity.bearer())
