"""financial-signals-mcp tools — derived intelligence, one per file.

  insider_activity     ($0.01)  insider transactions + pattern analysis (premium)
  earnings_check       ($0.01)  8-quarter surprise/streak/guidance + next date
  institutional_moves  ($0.01)  significant 13F position changes with context
  screen_stocks        ($0.01)  ratio screen + composite_value_score (proprietary)
  sector_snapshot      ($0.01)  sector medians, top/bottom, aggregate trends
  macro_dashboard      (free)   macro indicators — the discovery gateway
  company_profile      ($0.01)  full blended profile + value score + positioning
  anomaly_alert        ($0.02)  unusual patterns across all companies (premium)
  mint_info            (free)   FoundryNet Data Network + MINT cross-promo
"""
from . import insider as insider_tool
from . import earnings as earnings_tool
from . import institutional as institutional_tool
from . import screen as screen_tool
from . import sector as sector_tool
from . import macro as macro_tool
from . import company as company_tool
from . import anomaly as anomaly_tool
from . import mint as mint_tool


def register_all(mcp) -> None:
    for m in (insider_tool, earnings_tool, institutional_tool, screen_tool, sector_tool,
              macro_tool, company_tool, anomaly_tool, mint_tool):
        m.register(mcp)
