"""Regression tests for the canonical reproductions of published articles.

These tests pin the headline numbers from articles that depend on this
backtester. If an upstream change in the engine moves a published table
by more than the tolerance, the test fails and either the article needs
re-verification or the engine change needs review. The intent is to
prevent the kind of silent drift that left the Spitznagel article
publishing pre-fix numbers for an unknown period after the
externally-funded budget path was repaired.

Article-reproduction tests should:
  1. Pin SPY baseline values (annual return, max DD) so changes to the
     data pipeline or compounding math are caught directly.
  2. Pin the published table's Spitznagel-framing numbers (annual,
     max DD, Sharpe) at the budgets the article calls out.
  3. Tolerate small numerical drift (~0.5pp on returns, ~0.05 on
     Sharpe) but flag larger moves.

The companion script outside this repo,
``unbalancedparentheses/finance_research:scripts/verify_blog_numbers.py``,
exercises the same reproduction in human-readable form; this file is
the CI-friendly version.
"""

from __future__ import annotations

import math
import os
import warnings
from pathlib import Path

import numpy as np
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
OPTIONS_CSV = DATA_ROOT / "options.csv"
STOCKS_CSV = DATA_ROOT / "stocks.csv"

requires_data = pytest.mark.skipif(
    not (OPTIONS_CSV.exists() and STOCKS_CSV.exists()),
    reason=(
        "Article-reproduction tests need processed SPY data. Run "
        "'python data/fetch_data.py all --symbols SPY' before invoking them."
    ),
)


# --- Spitznagel article -----------------------------------------------------
#
# Article: https://federicocarrone.com/series/leptokurtic/the-tail-hedge-debate-spitznagel-is-right/
# Parameters: DTE 90-180, delta (-0.10, -0.02), exit DTE 14, monthly rebalance,
# external put budget (Spitznagel framing) expressed as an ANNUAL budget via
# `options_budget_annual_pct` — i.e. 0.005 = 0.5% of NAV per year, matching the
# article's "X%/yr" language. Exits are checked daily (`check_exits_daily=True`)
# so puts close at real bids around DTE 14 rather than expiring into the
# intrinsic fallback. Data window: 2008-01-02 to 2024-12-31.
#
# Numbers below are post TWO engine fixes (see CHANGELOG.md):
#   1. externally-funded exit accounting — subtract put entry cost from cash at
#      exit so lifetime per-trade cash flow equals realized P&L, not full
#      proceeds; and
#   2. intrinsic value computed from the UNADJUSTED close (raw strikes vs
#      adjusted spot previously manufactured phantom intrinsic value for
#      expired contracts).
# With both fixes the deep-OTM overlay TRACKS SPY with a small monotonic drag
# and a Sharpe essentially equal to buy-and-hold — the earlier "overlay beats
# SPY / Sharpe sweet spot" result was an artifact of those two bugs.

SPITZNAGEL_SPY_BASELINE = {
    "annual": 10.65,
    "max_dd": -51.9,
}

# Spitznagel framing (100% stocks + external annual put budget on top), engine
# post-fix. Tolerance: 0.5pp annual return, 1.0pp max DD, 0.05 Sharpe.
SPITZNAGEL_TABLE = {
    0.005: {"annual": 10.50, "max_dd": -51.9, "sharpe": 0.535},
    0.010: {"annual": 10.34, "max_dd": -51.7, "sharpe": 0.538},
    0.020: {"annual":  9.99, "max_dd": -51.4, "sharpe": 0.536},
    0.033: {"annual":  9.52, "max_dd": -51.1, "sharpe": 0.525},
}

INITIAL_CAPITAL = 1_000_000
RETURN_TOLERANCE_PP = 0.5
DRAWDOWN_TOLERANCE_PP = 1.0
SHARPE_TOLERANCE = 0.05


@pytest.fixture(scope="module")
def options_data():
    return HistoricalOptionsData(str(OPTIONS_CSV))


@pytest.fixture(scope="module")
def stocks_data():
    return TiingoData(str(STOCKS_CSV))


def _make_deep_otm_put_strategy(schema):
    leg = StrategyLeg("leg_1", schema, option_type=OptionType.PUT, direction=Direction.BUY)
    leg.entry_filter = (
        (schema.underlying == "SPY")
        & (schema.dte >= 90)
        & (schema.dte <= 180)
        & (schema.delta >= -0.10)
        & (schema.delta <= -0.02)
    )
    leg.entry_sort = ("delta", False)
    leg.exit_filter = schema.dte <= 14
    s = Strategy(schema)
    s.add_leg(leg)
    s.add_exit_thresholds(profit_pct=math.inf, loss_pct=math.inf)
    return s


def _run_spitznagel(options_data, stocks_data, schema, budget_pct):
    bt = BacktestEngine(
        {"stocks": 1.0, "options": 0.0, "cash": 0.0},
        initial_capital=INITIAL_CAPITAL,
    )
    # Annual budget framing (matches the article's "X%/yr") with daily exit
    # checks so puts close at real bids near DTE 14 rather than expiring into
    # the intrinsic fallback.
    bt.options_budget_annual_pct = budget_pct
    bt.stocks = [Stock("SPY", 1.0)]
    bt.stocks_data = stocks_data
    bt.options_data = options_data
    bt.options_strategy = _make_deep_otm_put_strategy(schema)
    bt.run(rebalance_freq=1, rebalance_unit="BMS", check_exits_daily=True)
    return bt.balance


def _compute_stats(balance):
    bal = balance["total capital"]
    years = (bal.index[-1] - bal.index[0]).days / 365.25
    total = bal.iloc[-1] / bal.iloc[0] - 1
    annual = ((1 + total) ** (1 / years) - 1) * 100
    daily = bal.pct_change().dropna()
    vol = daily.std() * math.sqrt(252) * 100
    sharpe = annual / vol if vol > 0 else 0.0
    cummax = bal.cummax()
    max_dd = ((bal - cummax) / cummax).min() * 100
    return annual, max_dd, sharpe


def _spy_series(stocks_data):
    """SPY adjusted-close series indexed by date (buy-and-hold baseline)."""
    df = stocks_data._data.sort_values("date")
    df = df[df["symbol"] == "SPY"]
    return df.set_index("date")["adjClose"]


@requires_data
def test_spitznagel_spy_baseline(stocks_data):
    """SPY buy-and-hold over the article's 2008-2024 window."""
    df = stocks_data._data.sort_values("date")
    df = df[df["symbol"] == "SPY"]
    prices = df["adjClose"].values
    years = (df["date"].iloc[-1] - df["date"].iloc[0]).days / 365.25
    annual = ((prices[-1] / prices[0]) ** (1 / years) - 1) * 100
    series = df.set_index("date")["adjClose"]
    cummax = series.cummax()
    max_dd = ((series - cummax) / cummax).min() * 100

    assert abs(annual - SPITZNAGEL_SPY_BASELINE["annual"]) < RETURN_TOLERANCE_PP, (
        f"SPY baseline annual return drifted: "
        f"expected {SPITZNAGEL_SPY_BASELINE['annual']:.2f}%, got {annual:.2f}%"
    )
    assert abs(max_dd - SPITZNAGEL_SPY_BASELINE["max_dd"]) < DRAWDOWN_TOLERANCE_PP, (
        f"SPY baseline max DD drifted: "
        f"expected {SPITZNAGEL_SPY_BASELINE['max_dd']:.1f}%, got {max_dd:.1f}%"
    )


@requires_data
@pytest.mark.parametrize("budget", sorted(SPITZNAGEL_TABLE.keys()))
def test_spitznagel_framing(options_data, stocks_data, budget):
    """One row of the article's Spitznagel-framing table."""
    schema = options_data.schema
    balance = _run_spitznagel(options_data, stocks_data, schema, budget)
    annual, max_dd, sharpe = _compute_stats(balance)
    expected = SPITZNAGEL_TABLE[budget]

    assert abs(annual - expected["annual"]) < RETURN_TOLERANCE_PP, (
        f"budget {budget*100:.2f}%: annual return drifted from article: "
        f"expected {expected['annual']:.2f}%, got {annual:.2f}%"
    )
    assert abs(max_dd - expected["max_dd"]) < DRAWDOWN_TOLERANCE_PP, (
        f"budget {budget*100:.2f}%: max DD drifted from article: "
        f"expected {expected['max_dd']:.1f}%, got {max_dd:.1f}%"
    )
    assert abs(sharpe - expected["sharpe"]) < SHARPE_TOLERANCE, (
        f"budget {budget*100:.2f}%: Sharpe drifted from article: "
        f"expected {expected['sharpe']:.3f}, got {sharpe:.3f}"
    )


@requires_data
def test_spitznagel_monotone_drag_and_tracking(options_data, stocks_data):
    """Corrected qualitative shape (post exit-accounting + unadjusted-intrinsic
    fixes): under realistic accounting the deep-OTM overlay has NO Sharpe
    sweet spot. A larger annual put budget is a larger premium drag, so annual
    return decreases monotonically with budget, while Sharpe stays essentially
    equal to buy-and-hold (the puts neither add meaningful alpha nor move the
    full-period risk-adjusted return at these budgets). The pre-fix "Sharpe
    peaks at 0.5%-1.0%" claim was an artifact of treating put proceeds as pure
    profit; if it reappears, an accounting regression has crept back in.
    """
    schema = options_data.schema
    spy_sharpe = _compute_stats(_spy_series(stocks_data).to_frame("total capital"))[2]

    annuals, sharpes = {}, {}
    for budget in (0.005, 0.010, 0.020, 0.033):
        balance = _run_spitznagel(options_data, stocks_data, schema, budget)
        annual, _, sharpe = _compute_stats(balance)
        annuals[budget], sharpes[budget] = annual, sharpe

    budgets = [0.005, 0.010, 0.020, 0.033]
    for lo, hi in zip(budgets, budgets[1:]):
        assert annuals[lo] > annuals[hi], (
            f"annual return should fall as budget rises (premium drag): "
            f"{lo*100:.1f}% gave {annuals[lo]:.2f}% but {hi*100:.1f}% gave "
            f"{annuals[hi]:.2f}%"
        )
    for budget, sharpe in sharpes.items():
        assert abs(sharpe - spy_sharpe) < SHARPE_TOLERANCE, (
            f"Sharpe at {budget*100:.1f}% ({sharpe:.3f}) should track SPY "
            f"({spy_sharpe:.3f}) within {SHARPE_TOLERANCE} — no sweet spot"
        )


# --- Fast smoke variant -----------------------------------------------------
# The tests above need the full 17-year SPY chain and take ~3 minutes to run.
# This fast variant runs only the 0.5%/yr Spitznagel budget against the full
# sample and asserts the corrected qualitative shape — overlay TRACKS SPY on
# return and is no worse on max drawdown — without pinning specific numbers.
# Suitable as a pre-commit / fast-CI smoke that catches "Spitznagel framing
# fundamentally broken" without paying for the full parametrized run.

@requires_data
@pytest.mark.smoke
def test_spitznagel_smoke_qualitative(options_data, stocks_data):
    """Single-budget qualitative check: 0.5%/yr deep OTM tracks SPY on annual
    return (within 1pp) and is no worse than SPY on full-period max drawdown.

    Under realistic accounting (exit-cost and unadjusted-intrinsic fixes) the
    overlay neither beats SPY on return nor materially improves the full-period
    max drawdown at a 0.5%/yr budget — the pre-fix "beats SPY / big drawdown
    improvement" headline was an artifact of phantom put proceeds. What remains
    true and worth guarding: the strategy tracks the underlying closely and
    does not silently flip into a return- or risk-destroying regime.
    """
    schema = options_data.schema

    series = _spy_series(stocks_data)
    spy_annual, spy_max_dd, _ = _compute_stats(series.to_frame("total capital"))

    # 0.5%/yr Spitznagel overlay
    balance = _run_spitznagel(options_data, stocks_data, schema, 0.005)
    annual, max_dd, _ = _compute_stats(balance)

    assert abs(annual - spy_annual) < 1.0, (
        f"0.5%/yr Spitznagel annual ({annual:.2f}%) should track "
        f"SPY annual ({spy_annual:.2f}%) within 1pp"
    )
    assert max_dd > spy_max_dd - 0.5, (  # less negative is better
        f"0.5%/yr Spitznagel max DD ({max_dd:.1f}%) should be no worse "
        f"than SPY max DD ({spy_max_dd:.1f}%)"
    )
