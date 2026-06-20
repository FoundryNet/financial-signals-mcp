-- Financial Signals — derived-intelligence schema for financial_signals_aggregator
-- + financial-signals-mcp. Standalone Supabase project. Idempotent.
-- Stores DERIVED signals (patterns/anomalies/scores), not raw filings.

-- ── tracked universe ─────────────────────────────────────────────────────────
create table if not exists tracked_tickers (
  ticker     text primary key,
  company    text,
  sector     text,
  added_at   timestamptz not null default now()
);

-- ── insider_signals ──────────────────────────────────────────────────────────
create table if not exists insider_signals (
  id uuid primary key default gen_random_uuid(),
  company text, ticker text,
  insider_name text, insider_title text,
  transaction_type text,                 -- buy | sell | exercise
  shares numeric, value_usd numeric, transaction_date date,
  shares_remaining numeric, ownership_change_pct numeric,
  signal_type text,                      -- cluster_sell | large_buy | ceo_buy | pre_earnings
  days_to_next_earnings integer, price_at_transaction numeric,
  context text,
  created_at timestamptz not null default now(),
  unique (ticker, insider_name, transaction_date, shares, transaction_type)
);
create index if not exists idx_insider_ticker on insider_signals (ticker);
create index if not exists idx_insider_date on insider_signals (transaction_date desc);
create index if not exists idx_insider_signal on insider_signals (signal_type);

-- ── earnings_signals ─────────────────────────────────────────────────────────
create table if not exists earnings_signals (
  id uuid primary key default gen_random_uuid(),
  company text, ticker text,
  report_date date, fiscal_quarter text,
  eps_actual numeric, eps_estimate numeric, eps_surprise_pct numeric,
  revenue_actual numeric, revenue_estimate numeric, revenue_surprise_pct numeric,
  beat_streak integer, guidance_direction text,         -- raised|lowered|maintained|none
  post_earnings_move_pct numeric, historical_surprise_avg_4q numeric,
  next_earnings_date date,
  signal text,
  updated_at timestamptz not null default now(),
  unique (ticker, report_date)
);
create index if not exists idx_earnings_ticker on earnings_signals (ticker);
create index if not exists idx_earnings_date on earnings_signals (report_date desc);

-- ── institutional_signals ────────────────────────────────────────────────────
create table if not exists institutional_signals (
  id uuid primary key default gen_random_uuid(),
  company text, ticker text, institution_name text,
  shares_current numeric, shares_previous numeric, shares_delta numeric,
  value_current_usd numeric, value_delta_usd numeric,
  ownership_pct numeric, filing_date date,
  signal_type text,         -- new_position | exit | significant_increase | significant_decrease
  context text,
  updated_at timestamptz not null default now(),
  unique (ticker, institution_name, filing_date)
);
create index if not exists idx_inst_ticker on institutional_signals (ticker);
create index if not exists idx_inst_signal on institutional_signals (signal_type);

-- ── ratio_screens ────────────────────────────────────────────────────────────
create table if not exists ratio_screens (
  ticker text primary key,
  company text, sector text, market_cap numeric,
  pe_ratio numeric, ps_ratio numeric, pb_ratio numeric, ev_ebitda numeric,
  revenue_growth_yoy numeric, earnings_growth_yoy numeric,
  gross_margin numeric, operating_margin numeric, net_margin numeric,
  roe numeric, roic numeric, debt_to_equity numeric,
  dividend_yield numeric, payout_ratio numeric, free_cash_flow_yield numeric,
  sector_pe_median numeric, sector_ps_median numeric,
  pe_vs_sector text,                     -- premium | discount | inline (+ pct in value)
  pe_vs_sector_pct numeric,
  composite_value_score numeric,         -- 0-100 proprietary
  updated_at timestamptz not null default now()
);
create index if not exists idx_ratio_sector on ratio_screens (sector);
create index if not exists idx_ratio_score on ratio_screens (composite_value_score desc nulls last);
create index if not exists idx_ratio_mktcap on ratio_screens (market_cap desc nulls last);

-- ── macro_signals ────────────────────────────────────────────────────────────
create table if not exists macro_signals (
  fred_series_id text primary key,
  indicator_name text,
  current_value numeric, previous_value numeric, change_pct numeric,
  trend text,                            -- rising | falling | flat
  historical_percentile numeric,         -- vs ~20yr history
  signal text,
  updated_at timestamptz not null default now()
);

-- ── free-tier counter + payments ─────────────────────────────────────────────
create table if not exists fin_query_usage (
  agent_key text not null, day date not null,
  count integer not null default 0, updated_at timestamptz not null default now(),
  primary key (agent_key, day)
);
create or replace function fin_claim_free_query(p_agent_key text, p_day date, p_cap integer)
returns jsonb language plpgsql as $$
declare cur integer; ok boolean;
begin
  insert into fin_query_usage (agent_key, day, count, updated_at)
  values (p_agent_key, p_day, 0, now())
  on conflict (agent_key, day) do nothing;
  select count into cur from fin_query_usage
    where agent_key = p_agent_key and day = p_day for update;
  if cur < p_cap then
    update fin_query_usage set count = count + 1, updated_at = now()
      where agent_key = p_agent_key and day = p_day;
    ok := true; cur := cur + 1;
  else ok := false; end if;
  return jsonb_build_object('allowed', ok, 'count', cur, 'cap', p_cap);
end; $$;

create table if not exists fin_payments (
  tx_signature text primary key, intent text, agent_key text, tool text,
  amount_usdc numeric, payer_wallet text, recipient text, status text,
  block_time bigint, created_at timestamptz not null default now()
);
