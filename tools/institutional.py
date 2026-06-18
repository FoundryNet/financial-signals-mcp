from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def institutional_moves(
        ticker: Optional[str] = None,
        institution: Optional[str] = None,
        signal_type: Optional[str] = None,
        min_value: Optional[float] = None,
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Significant institutional (13F) position changes with context — new
        positions, exits, and big increases/decreases (e.g. "Bridgewater initiated
        $400M position"). Institutional ownership flow for any ticker or fund.

        PAID: $0.01 USDC per query after the daily free allowance (25/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            ticker: optional ticker filter.
            institution: optional institution name, partial match (e.g. "Vanguard").
            signal_type: new_position | exit | significant_increase | significant_decrease.
            min_value: minimum current position value (USD).
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_institutional(ticker, institution, signal_type, min_value,
                                           agent_key=identity.resolve_agent_key(agent_id),
                                           payment_tx=payment_tx, api_key=identity.bearer())
