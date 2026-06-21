---
name: foundrynet-financial-intelligence
description: Real-time market signals, insider-trading detection, earnings analysis, and composite stock scoring from the FoundryNet Data Network
---

# FoundryNet Financial Intelligence

## Connect
```bash
claude mcp add --transport http foundrynet-financial https://financial-signals-mcp-production.up.railway.app/mcp
```

## Available Tools
- `macro_dashboard` (free) — FRED macro indicators with historical percentiles
- `company_profile` ($0.01) — Comprehensive company analysis with composite value scoring
- `insider_activity` ($0.01) — Insider-trading patterns with cluster detection
- `earnings_check` ($0.01) — Earnings-surprise history and guidance trends
- `screen_stocks` ($0.01) — Stock screening with proprietary value scoring
- `sector_snapshot` ($0.01) — Sector rotation and relative performance
- `institutional_moves` ($0.01) — 13F institutional position changes
- `anomaly_alert` ($0.02) — Unusual market patterns detected today
- `daily_brief` ($25) — Curated daily market intelligence, MINT-attested
- `mint_info` (free) — Network + attestation info

A daily free-tier allowance precedes the paywall; paid tools settle in USDC on
Solana (x402) **or** Stripe. An `Authorization: Bearer fnet_…` key bypasses the gate.

## Part of the FoundryNet Data Network
17 interconnected data-intelligence servers with MINT-attested, verifiable outputs.
Live network activity: https://mint.foundrynet.io/feed
