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
# external put budget (Spitznagel framing). Data window: 2008-01-02 to 2024-12-31.

SPITZNAGEL_SPY_BASELINE = {
    "annual": 10.65,
    "max_dd": -51.9,
}

# Spitznagel framing (100% stocks + external put budget on top).
# Tolerance on annual return: 0.5pp; on max DD: 1.0pp; on Sharpe: 0.05.
SPITZNAGEL_TABLE = {
    0.005: {"annual": 13.54, "max_dd": -46.4, "sharpe": 0.721},
    0.010: {"annual": 16.29, "max_dd": -44.4, "sharpe": 0.708},
    0.020: {"annual": 21.34, "max_dd": -64.1, "sharpe": 0.633},
    0.033: {"annual": 27.23, "max_dd": -75.4, "sharpe": 0.591},
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
    bt.options_budget_pct = budget_pct
    bt.stocks = [Stock("SPY", 1.0)]
    bt.stocks_data = stocks_data
    bt.options_data = options_data
    bt.options_strategy = _make_deep_otm_put_strategy(schema)
    bt.run(rebalance_freq=1, rebalance_unit="BMS")
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
def test_spitznagel_sweet_spot_shape(options_data, stocks_data):
    """The article's central qualitative claim: Sharpe peaks near 0.5%-1.0%
    budget and degrades on either side. If the engine ever lets a budget
    above 1% produce a higher Sharpe than the 0.5%-1.0% range, the
    article's sweet-spot framing breaks and the test should catch it.
    """
    schema = options_data.schema
    sharpes = {}
    for budget in (0.005, 0.010, 0.020, 0.033):
        balance = _run_spitznagel(options_data, stocks_data, schema, budget)
        _, _, sharpe = _compute_stats(balance)
        sharpes[budget] = sharpe

    assert sharpes[0.005] > sharpes[0.020], (
        f"Sharpe at 0.5% ({sharpes[0.005]:.3f}) should exceed "
        f"Sharpe at 2.0% ({sharpes[0.020]:.3f}); sweet-spot shape lost"
    )
    assert sharpes[0.010] > sharpes[0.033], (
        f"Sharpe at 1.0% ({sharpes[0.010]:.3f}) should exceed "
        f"Sharpe at 3.3% ({sharpes[0.033]:.3f}); sweet-spot shape lost"
    )


# --- Fast smoke variant -----------------------------------------------------
# The tests above need the full 17-year SPY chain and take ~3 minutes to run.
# This fast variant runs only the 0.5% Spitznagel budget against the full
# sample and asserts the qualitative shape — overlay beats SPY on return and
# Sharpe — without pinning specific numbers. Suitable as a pre-commit /
# fast-CI smoke that catches "Spitznagel framing fundamentally broken"
# without paying for the full parametrized run.

@requires_data
@pytest.mark.smoke
def test_spitznagel_smoke_qualitative(options_data, stocks_data):
    """Single-budget qualitative check: 0.5% deep OTM beats SPY on annual
    return and Sharpe, and improves max drawdown. Faster than the full
    parametrized table and catches engine-side regressions that flip the
    sign of the trade.
    """
    schema = options_data.schema

    # SPY baseline
    df = stocks_data._data.sort_values("date")
    df = df[df["symbol"] == "SPY"]
    series = df.set_index("date")["adjClose"]
    years = (series.index[-1] - series.index[0]).days / 365.25
    spy_annual = ((series.iloc[-1] / series.iloc[0]) ** (1 / years) - 1) * 100
    spy_daily = series.pct_change().dropna()
    spy_vol = spy_daily.std() * math.sqrt(252) * 100
    spy_sharpe = spy_annual / spy_vol if spy_vol > 0 else 0.0
    spy_cummax = series.cummax()
    spy_max_dd = ((series - spy_cummax) / spy_cummax).min() * 100

    # 0.5% Spitznagel overlay
    balance = _run_spitznagel(options_data, stocks_data, schema, 0.005)
    annual, max_dd, sharpe = _compute_stats(balance)

    assert annual > spy_annual, (
        f"0.5% Spitznagel annual ({annual:.2f}%) should exceed "
        f"SPY annual ({spy_annual:.2f}%)"
    )
    assert sharpe > spy_sharpe, (
        f"0.5% Spitznagel Sharpe ({sharpe:.3f}) should exceed "
        f"SPY Sharpe ({spy_sharpe:.3f})"
    )
    assert max_dd > spy_max_dd, (  # less negative is better
        f"0.5% Spitznagel max DD ({max_dd:.1f}%) should be less severe "
        f"than SPY max DD ({spy_max_dd:.1f}%)"
    )
