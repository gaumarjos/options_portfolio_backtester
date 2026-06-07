"""Known-bug regression tests, deliberately failing.

Each test in this file is marked ``@pytest.mark.xfail(strict=True)`` so the
CI run treats them as expected failures. When a bug is fixed, the test
flips to "unexpectedly passing" (xpassed) and ``strict=True`` turns that
into a CI failure, forcing the fixer to move the test out of this file
and into the regular suite. The point is to make every known bug a
permanent, machine-checkable record rather than a comment in a slack
thread.
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path

import pandas as pd
import pytest

warnings.filterwarnings("ignore")

from options_portfolio_backtester import (
    BacktestEngine,
    Direction,
    OptionType,
    Stock,
    Strategy,
    StrategyLeg,
)
from options_portfolio_backtester.data.providers import (
    HistoricalOptionsData,
    TiingoData,
)

DATA_ROOT = Path(__file__).resolve().parent.parent / "data" / "processed"
OPTIONS_PARQUET = DATA_ROOT / "options.parquet"
STOCKS_CSV = DATA_ROOT / "stocks.csv"

requires_data = pytest.mark.skipif(
    not (OPTIONS_PARQUET.exists() and STOCKS_CSV.exists()),
    reason="Needs processed SPY data; run 'python data/fetch_data.py all --symbols SPY'.",
)


# ---------------------------------------------------------------------------
# Bug #1: Budget-mode capital leak with non-deep-OTM puts
# ---------------------------------------------------------------------------
#
# Symptom
# -------
# When ``options_budget_pct`` is set ("Spitznagel framing") and the leg
# filter selects puts with non-trivial continuous mark-to-market value
# (anything closer to ATM than ~deep OTM), the engine ends up buying
# substantially more SPY than the legitimate sources of cash justify.
# Concrete example with near-ATM puts (delta -0.40 to -0.25) at 3.3%
# budget on the 17-year SPY data: final capital is ~$3.5 billion from
# $1 million starting capital. Deep OTM puts (delta -0.10 to -0.02) at
# the same budget produce ~$60 million, which is on the order of what
# the published Spitznagel article reproduces.
#
# Diagnostic data from a 2014 trace (near-ATM @ 3.3%):
#   2013-12-31: $22.9M total, 149,761 SPY shares ($22.5M), $315K puts
#   2014-12-31: $72.4M total, 368,615 SPY shares ($63M),   $9.4M puts
#   - SPY share count grew by 218,854 over the year
#   - Legitimate funding for new shares = SPY appreciation (~$3.1M) +
#     realized option P&L (~$1.23M from BTO/STC totals) = ~$4.5M.
#   - But ~$37M of new SPY was purchased during the year.
#   - Gap (~$32M) is the leak.
#
# Suspected location
# ------------------
# rust/ob_core/src/backtest.rs, the ``rebalance_date!`` macro (around
# lines 425-500). The ``externally_funded`` path computes
# ``stocks_alloc = allocation_stocks * liquid_capital`` which is correct
# in isolation; but the same loop also adds the budget to cash and
# claws back the unspent portion. Across many monthly iterations with
# a continuously-valuable put position, some fraction of unrealized
# put value appears to flow into the stocks bucket on each rebalance.
# Likely candidates for the actual mechanism: the order of
# stock-clearing vs cash-reset, the interaction between the daily
# exit path and the rebalance path, or the timing of options_cap
# valuation vs the rebalance trigger.
#
# Historical context
# ------------------
# Three prior commits in the engine's history attempted to fix
# adjacent issues:
#   - 523ba10  Fix cash leakage in externally-funded budget path
#   - 5840620  Fix budget-mode stock allocation: use liquid capital
#   - ffdfd1d  Revert full liquidation, fix accounting with
#              cash = total - options_capital
# The current run still exhibits the leak for non-deep-OTM positions,
# implying the previous fixes closed some variants but not all.
#
# Sanity guards already passing
# -----------------------------
# - SPY-only run (budget=0) matches raw SPY within 0.05pp/yr.
# - Deep OTM at any budget matches the published article numbers to
#   within tolerance (covered by tests/test_article_reproduction.py).
#
# Why this is xfail rather than skip
# ----------------------------------
# If a future engine change accidentally fixes the leak (e.g. someone
# changes the rebalance accounting and inadvertently closes this
# variant), the test will pass, the strict=True will make pytest fail
# the run, and the fixer will see exactly what to do next: move the
# test into tests/test_article_reproduction.py with a pinned final
# capital, document the fix in CHANGELOG.md, and delete the xfail.

EXPECTED_FINAL_CAPITAL_REASONABLE_MAX = 200_000_000  # $200M from $1M = ~33%/yr
INITIAL_CAPITAL = 1_000_000


def _make_put_strategy(schema, delta_lo, delta_hi):
    leg = StrategyLeg("leg_1", schema, option_type=OptionType.PUT, direction=Direction.BUY)
    leg.entry_filter = (
        (schema.underlying == "SPY")
        & (schema.dte >= 90) & (schema.dte <= 180)
        & (schema.delta >= delta_lo) & (schema.delta <= delta_hi)
    )
    leg.entry_sort = ("delta", False)
    leg.exit_filter = schema.dte <= 14
    s = Strategy(schema)
    s.add_leg(leg)
    s.add_exit_thresholds(profit_pct=math.inf, loss_pct=math.inf)
    return s


def _run_spitznagel(options_data, stocks_data, schema, delta_band, budget):
    bt = BacktestEngine(
        {"stocks": 1.0, "options": 0.0, "cash": 0.0},
        initial_capital=INITIAL_CAPITAL,
    )
    bt.options_budget_pct = budget
    bt.stocks = [Stock("SPY", 1.0)]
    bt.stocks_data = stocks_data
    bt.options_data = options_data
    bt.options_strategy = _make_put_strategy(schema, *delta_band)
    bt.run(rebalance_freq=1, rebalance_unit="BMS")
    return bt.balance["total capital"].iloc[-1]


@pytest.fixture(scope="module")
def options_data():
    return HistoricalOptionsData(str(OPTIONS_PARQUET))


@pytest.fixture(scope="module")
def stocks_data():
    return TiingoData(str(STOCKS_CSV))


@requires_data
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Budget-mode capital leak with non-deep-OTM puts — see module docstring. "
        "Final capital is ~$3.5B for near-ATM @ 3.3% budget on 17-year SPY, "
        "vs ~$60M for deep OTM at the same budget. The engine is overstating "
        "the SPY share count across rebalances when puts carry continuous "
        "mark-to-market value."
    ),
)
def test_near_atm_does_not_explode(options_data, stocks_data):
    """Near-ATM puts (~2% OTM) at 3.3% Spitznagel budget should not
    produce billion-dollar final capital from $1M starting capital."""
    final = _run_spitznagel(
        options_data, stocks_data, options_data.schema,
        delta_band=(-0.40, -0.25), budget=0.033,
    )
    assert final < EXPECTED_FINAL_CAPITAL_REASONABLE_MAX, (
        f"Near-ATM 3.3% Spitznagel final capital ${final:,.0f} exceeds "
        f"plausible ceiling ${EXPECTED_FINAL_CAPITAL_REASONABLE_MAX:,.0f}. "
        f"This is the budget-mode capital leak — see module docstring."
    )


@requires_data
@pytest.mark.xfail(
    strict=True,
    reason="Same leak, less dramatic. Standard OTM (~11% OTM) is also affected.",
)
def test_standard_otm_does_not_explode(options_data, stocks_data):
    """Standard OTM puts (delta -0.25 to -0.10, ~11% OTM) at 3.3% budget
    should give returns roughly bounded by the deep-OTM number, since the
    underlying convexity per dollar is less than deep OTM. Currently
    inflates to ~10x the deep-OTM final capital."""
    final = _run_spitznagel(
        options_data, stocks_data, options_data.schema,
        delta_band=(-0.25, -0.10), budget=0.033,
    )
    # Deep OTM at 3.3% is ~$60M; standard OTM should not exceed roughly that.
    assert final < EXPECTED_FINAL_CAPITAL_REASONABLE_MAX, (
        f"Standard OTM 3.3% Spitznagel final capital ${final:,.0f} exceeds "
        f"plausible ceiling. See module docstring."
    )
