"""Env-driven configuration for financial-signals-mcp.

The derived-intelligence layer over free financial sources (yfinance, SEC EDGAR,
FRED, FINRA) — insider/earnings/institutional/ratio/macro SIGNALS, not raw
filings — cached in its own standalone Supabase project. 8 tools, x402 metered.
Part of the FoundryNet Data Network.

Required to be useful:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   the standalone financial-signals project.
Optional:
  FRED_API_KEY            free FRED key (macro_signals no-op without it)
  PORT, REQUEST_TIMEOUT
  X402_ENABLED, SOLANA_WALLET, PAYMENT_RECIPIENT, PAYMENT_VERIFY_RPC,
  PAYMENT_USDC_MINT, PAYMENT_EXPIRY_SECONDS
  FREE_TIER_DAILY         default 25
  AGG_HOUR_UTC            daily aggregation hour, default 1 (≈5pm PT prev day / after close)
  FIN_MAX_TICKERS_PER_RUN cap tickers processed per run, default 120
  FIN_UNIVERSE            comma-separated tickers override (else bundled S&P 500)
  SEC_USER_AGENT          required UA for SEC EDGAR
  PRICE_*                 per-tool USDC prices
"""
from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _flag(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").strip().lower() in ("1", "true", "yes", "on")


SUPABASE_URL         = _env("SUPABASE_URL", "https://mebgqxjistxvxsoeyysi.supabase.co").rstrip("/")
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY")

PORT            = int(_env("PORT", "8080"))
REQUEST_TIMEOUT = int(_env("REQUEST_TIMEOUT", "30"))

# ── Sources ──────────────────────────────────────────────────────────────────
FRED_API_KEY  = _env("FRED_API_KEY")
SEC_USER_AGENT = _env("SEC_USER_AGENT", "FoundryNet Data Network hello@foundrynet.io")
AGG_HOUR_UTC  = int(_env("AGG_HOUR_UTC", "1"))   # ~17:00 PT (after US market close)
FIN_MAX_TICKERS_PER_RUN = int(_env("FIN_MAX_TICKERS_PER_RUN", "120"))
FIN_UNIVERSE  = _env("FIN_UNIVERSE")   # comma list override; else bundled S&P 500

# FRED macro series to track (id -> human name).
FRED_SERIES = {
    "DGS10": "10-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
    "T10Y2Y": "10Y-2Y Treasury Spread",
    "FEDFUNDS": "Federal Funds Rate",
    "CPIAUCSL": "CPI (All Urban Consumers)",
    "UNRATE": "Unemployment Rate",
    "T10YIE": "10-Year Breakeven Inflation",
    "VIXCLS": "CBOE Volatility Index (VIX)",
    "DTWEXBGS": "US Dollar Index (Broad)",
    "BAMLH0A0HYM2": "High-Yield Credit Spread",
}

# ── x402 per-tool pricing ────────────────────────────────────────────────────
X402_ENABLED      = _flag("X402_ENABLED", True)
SOLANA_WALLET     = _env("SOLANA_WALLET", "wUumjWWvtFEr69qkTw3wHNVQVxLA8DTyJSyVgGmLThd")
PAYMENT_RECIPIENT = _env("PAYMENT_RECIPIENT", SOLANA_WALLET).strip()
PAYMENT_VERIFY_RPC = _env("PAYMENT_VERIFY_RPC", "https://api.mainnet-beta.solana.com").rstrip("/")
PAYMENT_USDC_MINT  = _env("PAYMENT_USDC_MINT", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v").strip()
PAYMENT_EXPIRY_SECONDS = int(_env("PAYMENT_EXPIRY_SECONDS", "300"))

FREE_TIER_DAILY = int(_env("FREE_TIER_DAILY", "25"))

PRICE_INSIDER       = float(_env("PRICE_INSIDER", "0.01"))
PRICE_EARNINGS      = float(_env("PRICE_EARNINGS", "0.01"))
PRICE_INSTITUTIONAL = float(_env("PRICE_INSTITUTIONAL", "0.01"))
PRICE_SCREEN        = float(_env("PRICE_SCREEN", "0.01"))
PRICE_SECTOR        = float(_env("PRICE_SECTOR", "0.01"))
PRICE_COMPANY       = float(_env("PRICE_COMPANY", "0.01"))
PRICE_ANOMALY       = float(_env("PRICE_ANOMALY", "0.02"))

# ── FoundryNet Data Network cross-promo ──────────────────────────────────────
MINT_MCP_URL  = _env("MINT_MCP_URL", "https://mint-mcp-production.up.railway.app/mcp")
MINT_INFO_URL = _env("MINT_INFO_URL", "https://mint.foundrynet.io")
SISTER_SERVERS = {
    "gov-contracts-mcp": "https://gov-contracts-mcp-production.up.railway.app/mcp",
    "brand-intel-mcp":   "https://brand-intel-mcp-production.up.railway.app/mcp",
    "patent-intel-mcp":  "https://patent-intel-mcp-production.up.railway.app/mcp",
}

PUBLIC_MCP_URL = _env("PUBLIC_MCP_URL", "https://financial-signals-mcp-production.up.railway.app/mcp")
