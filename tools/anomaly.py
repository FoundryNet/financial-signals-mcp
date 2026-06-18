from typing import Optional

import core
import identity


def register(mcp) -> None:
    @mcp.tool
    async def anomaly_alert(
        min_severity: Optional[str] = "low",
        agent_id: Optional[str] = None,
        payment_tx: Optional[str] = None,
    ) -> dict:
        """Unusual patterns detected across all monitored companies in the last few
        days — insider clusters, earnings divergences, institutional exits, and
        ratio extremes — ranked by severity. The premium market-intelligence sweep.

        PAID: $0.02 USDC per query after the daily free allowance (25/day). On a
        402, pay the returned Solana memo and re-call with the SAME args plus
        payment_tx=<signature>. An Authorization: Bearer fnet_ key bypasses it.

        Args:
            min_severity: "low", "medium", or "high" (default low).
            agent_id: stable id for your agent (scopes the free-tier counter).
            payment_tx: Solana tx signature, when re-calling after a 402.
        """
        return await core.do_anomaly(min_severity, agent_key=identity.resolve_agent_key(agent_id),
                                     payment_tx=payment_tx, api_key=identity.bearer())
