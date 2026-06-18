from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def company_profile(
        ticker: str,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Comprehensive blended profile for a ticker — full ratios, insider
        activity summary, institutional ownership concentration, earnings track
        record, sector positioning, and the proprietary composite_value_score. One
        call for the full financial-intelligence picture.

        PAID: $0.01 USDC per query after the daily free allowance (25/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            ticker: the stock ticker, e.g. "MSFT".
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_company(ticker, agent_key=identity.resolve_agent_key(agent_id),
                                     payment_tx=payment_tx, api_key=identity.bearer())
