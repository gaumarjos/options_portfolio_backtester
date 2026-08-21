"""Regression guards for the bug classes that have actually burned us.

Each test here encodes an *independent oracle* — a fact about the economics
or the API that must hold regardless of how the engine is implemented — so
the bug classes documented in CHANGELOG.md cannot quietly return:

- silent dead config (`check_exits_daily` attribute no-op),
- cash-flow asymmetry / phantom money (the "free puts" bug, class A),
- mispriced positions (the adjClose intrinsic bug, class B),
- budget framing confusion (per-rebalance treated as annual).

Everything in this file runs on the small bundled dataset so it executes in
the default suite (and therefore CI) on every run — unlike the opt-in bench
suite, which needs the full SPY chain.
"""

from __future__ import annotations

import numpy as np
import pytest

from options_portfolio_backtester import BacktestEngine
from tests.heavy._test_helpers import (
    DEFAULT_CAPITAL,
    ivy_stocks,
    load_small_stocks,
    load_small_options,
    buy_put_strategy,
)


def _engine(alloc, **attrs):
    from options_portfolio_backtester.execution.cost_model import NoCosts
    from options_portfolio_backtester.execution.fill_model import MarketAtBidAsk

    opts = load_small_options()
    eng = BacktestEngine(
        alloc, initial_capital=DEFAULT_CAPITAL,
        cost_model=NoCosts(), fill_model=MarketAtBidAsk(),
    )
    eng.stocks = ivy_stocks()
    eng.stocks_data = load_small_stocks()
    eng.options_data = opts
    eng.options_strategy = buy_put_strategy(opts.schema)
    for k, v in attrs.items():
        setattr(eng, k, v)
    return eng


# ── Silent dead config ─────────────────────────────────────────────────

class TestUnknownConfigRejected:
    """`engine.check_exits_daily = True` was silently ignored for months
    because run() never read the attribute. The engine is now sealed: any
    unknown attribute raises instead of becoming dead config."""

    def test_typo_raises_attribute_error(self):
        eng = BacktestEngine({"stocks": 1.0, "options": 0.0, "cash": 0.0})
        with pytest.raises(AttributeError, match="unknown config"):
            eng.check_exit_daily = True  # missing 's' — the classic typo

    def test_suggestion_in_error(self):
        eng = BacktestEngine({"stocks": 1.0, "options": 0.0, "cash": 0.0})
        with pytest.raises(AttributeError, match="check_exits_daily"):
            eng.check_exits_dailyy = True

    def test_known_attributes_still_settable(self):
        eng = BacktestEngine({"stocks": 1.0, "options": 0.0, "cash": 0.0})
        eng.check_exits_daily = True
        eng.assert_invariants = True
        eng.rebalance_stocks_on_exit = True
        eng.options_budget_annual_pct = 0.01
        assert eng.check_exits_daily and eng.assert_invariants


# ── Runtime invariants exercised on every CI run ───────────────────────

class TestRuntimeInvariantsInDefaultSuite:
    """The class-A (cash-flow) and class-B (valuation) in-engine guards must
    hold on a standard run. The SPY-scale version lives in tests/heavy; this
    small-data version makes sure every default `pytest` run exercises the
    invariant code path at all."""

    def test_self_funded_run_passes_invariants(self):
        eng = _engine({"stocks": 0.6, "options": 0.3, "cash": 0.1},
                      assert_invariants=True)
        eng.run(rebalance_freq=1, rebalance_unit="BMS")
        assert len(eng.balance) > 0

    def test_externally_funded_run_passes_invariants(self):
        eng = _engine({"stocks": 1.0, "options": 0.0, "cash": 0.0},
                      assert_invariants=True)
        eng.options_budget_pct = 0.05
        eng.run(rebalance_freq=1, rebalance_unit="BMS", check_exits_daily=True)
        assert len(eng.balance) > 0


# ── Phantom money / budget oracles ─────────────────────────────────────

class TestBudgetOracles:

    def test_zero_budget_equals_stock_only(self):
        """An options budget of zero must produce *exactly* the stock-only
        result. Any divergence means option positions created value or cash
        out of nothing — the phantom-money class."""
        base = _engine({"stocks": 1.0, "options": 0.0, "cash": 0.0})
        base.run(rebalance_freq=1, rebalance_unit="BMS")

        zero = _engine({"stocks": 1.0, "options": 0.0, "cash": 0.0})
        zero.options_budget_annual_pct = 0.0
        zero.run(rebalance_freq=1, rebalance_unit="BMS")

        a = base.balance["total capital"].to_numpy(dtype=float)
        b = zero.balance["total capital"].to_numpy(dtype=float)
        assert a.shape == b.shape
        assert np.allclose(a, b, rtol=1e-9, atol=1e-6), (
            "zero options budget diverged from stock-only run"
        )

    def test_unfilled_budget_is_fully_clawed_back(self):
        """A positive external budget whose entry filter never matches must
        leave the portfolio EXACTLY equal to the stock-only run. The engine
        temporarily injects the budget into cash before attempting entries
        and must claw back every cent on no-fill — a leak in that branch is
        free money every rebalance (the cash-flow bug class)."""
        base = _engine({"stocks": 1.0, "options": 0.0, "cash": 0.0})
        base.run(rebalance_freq=1, rebalance_unit="BMS")

        nofill = _engine({"stocks": 1.0, "options": 0.0, "cash": 0.0})
        nofill.options_budget_pct = 0.05
        # Impossible entry filter: nothing has 10,000+ days to expiry.
        schema = nofill.options_data.schema
        for leg in nofill.options_strategy.legs:
            leg.entry_filter = schema.dte >= 10_000
        nofill.run(rebalance_freq=1, rebalance_unit="BMS")

        a = base.balance["total capital"].to_numpy(dtype=float)
        b = nofill.balance["total capital"].to_numpy(dtype=float)
        assert np.allclose(a, b, rtol=1e-9, atol=1e-6), (
            "unfilled external budget leaked into the portfolio: "
            f"final {b[-1]:,.2f} vs stock-only {a[-1]:,.2f}"
        )

    def test_per_rebalance_vs_annual_budget_distinct(self):
        """`options_budget_pct` is per-rebalance; `options_budget_annual_pct`
        is per-year. With monthly rebalancing the same numeric value must
        spend ~12x more premium in per-rebalance mode. If the two runs come
        out (near-)identical, one knob has been silently rewired to the
        other's semantics."""
        per_reb = _engine({"stocks": 1.0, "options": 0.0, "cash": 0.0})
        per_reb.options_budget_pct = 0.05
        per_reb.run(rebalance_freq=1, rebalance_unit="BMS")

        annual = _engine({"stocks": 1.0, "options": 0.0, "cash": 0.0})
        annual.options_budget_annual_pct = 0.05
        annual.run(rebalance_freq=1, rebalance_unit="BMS")

        per_reb_trades = len(per_reb.trade_log)
        annual_trades = len(annual.trade_log)
        # The per-rebalance run has 12x the budget per rebalance; on the
        # small dataset that must show up as at least as many trades and a
        # different balance path.
        assert per_reb_trades >= annual_trades
        a = per_reb.balance["total capital"].to_numpy(dtype=float)
        b = annual.balance["total capital"].to_numpy(dtype=float)
        assert not np.allclose(a, b, rtol=1e-6), (
            "per-rebalance and annual budgets produced identical runs — "
            "one knob is mis-wired to the other's semantics"
        )


# ── Balance-series look-ahead (backfill class) ─────────────────────────

def _engine_with_midwindow_exits():
    """Engine whose positions close BETWEEN rebalance dates.

    The bundled option chain has DTE 462-550, so the usual `dte <= 30` exit
    filter never fires and nothing ever changes mid-window — which is exactly
    the condition under which the backfill bug is invisible. Profit/loss
    thresholds give us exits on non-rebalance days instead (2014-12-16,
    2015-01-05, 2015-02-03, 2015-03-03 against month-start rebalances).
    """
    eng = _engine({"stocks": 1.0, "options": 0.0, "cash": 0.0},
                  rebalance_stocks_on_exit=True)
    eng.options_budget_annual_pct = 0.05
    eng.options_strategy.add_exit_thresholds(profit_pct=0.2, loss_pct=0.2)
    eng.run(rebalance_freq=1, rebalance_unit="BMS", check_exits_daily=True)
    return eng


def _open_qty_from_trades(eng):
    """Independent reconstruction of daily open contracts from the trade log.

    Walks the log chronologically as a running position: BTO adds, STC
    subtracts, each taking effect at the close of its own day (so a contract
    bought and sold the same day nets to zero, matching a balance row written
    at end of day).

    Deliberately NOT keyed on contract id: the bundled chain has a single
    contract that is re-entered four times, so pairing per contract silently
    collapses three of the four round trips.
    """
    import pandas as pd

    days = pd.to_datetime(eng.balance.index)
    tl = eng.trade_log.copy()
    if isinstance(tl.columns, pd.MultiIndex):
        tl.columns = ["_".join(c) for c in tl.columns]
    tl["date"] = pd.to_datetime(tl["totals_date"])
    order_col = next(c for c in tl.columns if c.endswith("_order"))

    delta = pd.Series(0.0, index=days)
    for _i, row in tl.iterrows():
        sign = 1.0 if row[order_col] == "BTO" else -1.0
        d = row["date"]
        if d in delta.index:
            delta.loc[d] += sign * float(row["totals_qty"])
    return delta.cumsum()


class TestBalanceSeriesHasNoLookAhead:
    """`compute_balance_period` backfilled every day in
    [prev_rebalance, rebalance) from ONE snapshot taken at the END of that
    window. With check_exits_daily=True the portfolio changes inside the
    window, so exits — and the stock reinvestment they trigger — were stamped
    onto days BEFORE they happened.

    Symptoms on the 2008-2025 SPY chain: 29% of days carried a wrong NAV, the
    equity curve showed one-day jumps of +45.4% (2008-11-03) and +26.9%
    (2020-03-02) on dates with no trade at all, and `options qty` read 0 on
    385 days against 129 genuinely uncovered ones. A phantom +45% spike set a
    fake running peak that then exaggerated every later drawdown.

    Terminal capital was always correct — only the path was wrong — so every
    return-based oracle passed throughout. These guards watch the path.
    """

    def test_scenario_actually_exits_between_rebalances(self):
        """Guard-the-guard: if nothing closes mid-window the checks below are
        vacuous (as they silently were on the stock `dte <= 30` strategy,
        which never fires on a 462-DTE chain)."""
        import pandas as pd

        eng = _engine_with_midwindow_exits()
        tl = eng.trade_log.copy()
        if isinstance(tl.columns, pd.MultiIndex):
            tl.columns = ["_".join(c) for c in tl.columns]
        order_col = next(c for c in tl.columns if c.endswith("_order"))
        assert (tl[order_col] == "STC").sum() >= 2, (
            "scenario produced no mid-window exits — the look-ahead guards "
            "below would pass trivially"
        )

    def test_options_qty_matches_trade_log_day_by_day(self):
        """`options qty` must agree with an independent trade-log
        reconstruction on every day. Backfilling breaks this: a position
        opened and closed inside one rebalance window vanishes entirely."""
        eng = _engine_with_midwindow_exits()

        reported = eng.balance["options qty"].fillna(0.0)
        expected = _open_qty_from_trades(eng)
        # Row 0 is the synthetic pre-start row added in Python; skip it.
        mismatch = ~np.isclose(reported.to_numpy(dtype=float)[1:],
                               expected.to_numpy(dtype=float)[1:],
                               rtol=0, atol=1e-9)
        assert not mismatch.any(), (
            f"{mismatch.sum()} day(s) where balance 'options qty' disagrees "
            "with the trade log — balance rows are not written from the state "
            f"of that day. First: {reported.index[1:][mismatch][:3].tolist()}"
        )

    def test_options_capital_zero_iff_no_position(self):
        """Marked option value and reported contract count must agree about
        whether a position exists. Backfilling desynchronises them: value gets
        priced per-day while the composition is frozen at end-of-window."""
        eng = _engine_with_midwindow_exits()
        qty = eng.balance["options qty"].fillna(0.0).to_numpy(dtype=float)[1:]
        cap = eng.balance["options capital"].fillna(0.0).to_numpy(dtype=float)[1:]
        bad = (np.isclose(qty, 0.0) & ~np.isclose(cap, 0.0)) | \
              (~np.isclose(qty, 0.0) & np.isclose(cap, 0.0))
        assert not bad.any(), (
            f"{bad.sum()} day(s) where 'options qty' and 'options capital' "
            "disagree on whether a position is held"
        )
