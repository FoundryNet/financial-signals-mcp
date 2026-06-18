from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def insider_activity(
        ticker: Optional[str] = None,
        days_back: Optional[int] = None,
        signal_type: Optional[str] = None,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Insider transactions with PATTERN analysis — not raw filings. Surfaces
        derived signals like cluster_sell ("3 insiders sold within 5 days, 12 days
        before earnings"), large_buy, ceo_buy, and pre_earnings. The premium tool
        for "show me unusual insider selling before earnings".

        PAID: $0.01 USDC per query after a daily free allowance (25/day). On a 402,
        pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. agent_id scopes your allowance; an Authorization:
        Bearer fnet_ key bypasses it.

        Args:
            ticker: optional ticker filter, e.g. "NVDA".
            days_back: only transactions in the last N days.
            signal_type: cluster_sell | large_buy | ceo_buy | pre_earnings.
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_insider(ticker, days_back, signal_type,
                                     agent_key=identity.resolve_agent_key(agent_id),
                                     payment_tx=payment_tx, api_key=identity.bearer())
