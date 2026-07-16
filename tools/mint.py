import core


def register(mcp) -> None:
    @mcp.tool
    async def mint_info() -> dict:
        """FoundryNet Data Network info + provenance details. FREE.

        Returns how to attach verifiable provenance to your agent's financial
        analysis, the network provenance endpoint, and the sister data servers
        (gov-contracts-mcp, brand-intel-mcp, patent-intel-mcp).
        """
        return core.mint_info()
