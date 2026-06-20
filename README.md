# Financial Signals MCP

**Derived financial intelligence for AI agents — not another SEC EDGAR filings
server.** Six of those already exist. This serves the *interpreted* layer: the
patterns, surprises, flows, scores, and anomalies an agent actually needs to make
a decision. Raw data is commodity; **interpreted signals are premium**.

> Part of the **FoundryNet Data Network**. Attest your agent's financial analysis
> with [MINT Protocol](https://mint-mcp-production.up.railway.app/mcp). See also:
> **gov-contracts-mcp**, **brand-intel-mcp**, **patent-intel-mcp**.
>
> Built as a **free-tier alternative to enterprise financial data** (FactSet,
> Morningstar, S&P Capital IQ) — financial intelligence for agents without
> enterprise subscriptions.

## Connect

- **MCP endpoint** (Streamable HTTP): `https://financial-signals-mcp-production.up.railway.app/mcp`
- **Registry**: `io.github.FoundryNet/financial-signals-mcp`
- **Agent card**: `https://financial-signals-mcp-production.up.railway.app/.well-known/agent-card.json`

### Claude Desktop / Cursor / Claude Code

```
claude mcp add --transport http financial-signals https://financial-signals-mcp-production.up.railway.app/mcp
```

```json
{ "mcpServers": { "financial-signals": { "url": "https://financial-signals-mcp-production.up.railway.app/mcp" } } }
```

## Tools

| Tool | Price | What it does |
|---|---|---|
| `insider_activity` | $0.01 | Insider transactions **with pattern analysis** (cluster_sell, large_buy, ceo_buy, pre_earnings) |
| `earnings_check` | $0.01 | 8-quarter EPS surprises, beat streak, guidance trend, next date |
| `institutional_moves` | $0.01 | Significant 13F position changes with context |
| `screen_stocks` | $0.01 | Ratio screen ranked by the **proprietary composite_value_score** |
| `sector_snapshot` | $0.01 | Sector medians, top/bottom by value score, aggregate trend |
| `macro_dashboard` | **free** | Macro indicators with trend + historical percentile — the gateway |
| `company_profile` | $0.01 | Full blended profile + value score + sector positioning |
| `anomaly_alert` | $0.02 | Unusual patterns across all monitored companies (premium) |
| `mint_info` | **free** | FoundryNet Data Network + MINT Protocol |

**Free tier:** 25 paid-tool queries/day per agent (plus free `macro_dashboard` +
`mint_info`). Then x402: the tool returns an HTTP-402 with a Solana USDC payment
memo — pay it, re-call with the same args plus `payment_tx=<signature>`. An
`Authorization: Bearer fnet_…` key bypasses the paywall.

## The moat: composite_value_score

`screen_stocks` and `company_profile` expose a proprietary **composite_value_score
(0-100)** — a transparent blend of: valuation vs. sector, growth, margin quality,
insider sentiment, institutional momentum, and earnings consistency. Sort
`screen_stocks` by it and you're using a ranking nobody else computes.

## Sources & method

A daily run after US market close computes DERIVED tables (not raw filings) over
the S&P 500 from free sources: **yfinance** (price, ratios, earnings, insider &
institutional — Yahoo's aggregation of SEC data), **FRED** (macro), and **SEC
EDGAR** (supplementary). Signal-typing + the composite score are computed at ingest.

**Honesty notes:** revenue surprise, guidance direction, and post-earnings move
are not reliably free, so they're null/`none` where unavailable (`roic` uses ROA
as a capital-efficiency proxy). Coverage grows as the daily universe is processed.

## More

part of the **FoundryNet Data Network**.

Built by [FoundryNet](https://foundrynet.io) · hello@foundrynet.io

## Live network activity

**Live feed:** [mint.foundrynet.io/feed](https://mint.foundrynet.io/feed)  
Real-time verified work across 13 servers and autonomous agents, anchored on Solana via [MINT Protocol](https://mint.foundrynet.io).
