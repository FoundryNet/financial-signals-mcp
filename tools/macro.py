import core


def register(mcp) -> None:
    @mcp.tool
    async def macro_dashboard() -> dict:
        """Get current macro indicators with trend and historical-percentile
        context — Treasury yields, the 10Y-2Y spread, Fed funds, CPI, unemployment,
        VIX, credit spreads, and the dollar, sourced from FRED. FREE market
        intelligence — every financial agent needs macro context, so this is the
        gateway.
        """
        return await core.do_macro()
