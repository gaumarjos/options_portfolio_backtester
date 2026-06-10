"""Balance sheet and trade log invariants.

Tests run each backtest ONCE and verify structural invariants.
Covers small, generated, and production datasets.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.bench._test_helpers import (
    RUST_AVAILABLE,
    DEFAULT_ALLOC,
    DEFAULT_CAPITAL,
    IVY_STOCKS_TUPLES,
    ivy_stocks,
    generated_stocks,
    prod_spy_stocks,
    load_generated_stocks,
    load_generated_options,
    load_prod_stocks,
    load_prod_options,
    buy_put_strategy,
    sell_put_strategy,
    strangle_strategy,
    run_backtest,
    assert_invariants,
)

pytestmark = pytest.mark.skipif(
    not RUST_AVAILABLE, reason="Rust extension not installed"
)


# ── Small dataset invariants ───────────────────────────────────────────

class TestBalanceSheetInvariants:

    @pytest.fixture(autouse=True)
    def _engine(self):
        self.eng = run_backtest()

    def test_total_capital_equals_parts(self):
        assert_invariants(self.eng)

    def test_capital_never_negative(self):
        tc = self.eng.balance["total capital"]
        assert (tc >= -1.0).all()

    def test_initial_capital_correct(self):
        first_tc = self.eng.balance["total capital"].iloc[0]
        assert abs(first_tc - DEFAULT_CAPITAL) < 1.0

    def test_balance_dates_monotonic(self):
        assert self.eng.balance.index.is_monotonic_increasing

    def test_balance_not_empty(self):
        assert len(self.eng.balance) > 1

    def test_cash_column_exists(self):
        assert "cash" in self.eng.balance.columns


class TestTradeLogInvariants:

    @pytest.fixture(autouse=True)
    def _engine(self):
        self.eng = run_backtest()

    def test_trade_log_not_empty(self):
        assert not self.eng.trade_log.empty

    def test_entry_costs_nonzero(self):
        if self.eng.trade_log.empty:
            pytest.skip("No trades")
        costs = self.eng.trade_log["totals"]["cost"].values
        assert all(c != 0 for c in costs)

    def test_qty_positive_on_entry(self):
        if self.eng.trade_log.empty:
            pytest.skip("No trades")
        qtys = self.eng.trade_log["totals"]["qty"].values
        assert all(q > 0 for q in qtys)

    def test_trade_dates_within_data_range(self):
        if self.eng.trade_log.empty:
            pytest.skip("No trades")
        trade_dates = pd.to_datetime(self.eng.trade_log["totals"]["date"]).unique()
        data_start = pd.Timestamp(self.eng.options_data._data["quotedate"].min())
        data_end = pd.Timestamp(self.eng.options_data._data["quotedate"].max())
        for td in trade_dates:
            assert data_start <= td <= data_end


class TestBalanceColumns:

    @pytest.fixture(autouse=True)
    def _engine(self):
        self.eng = run_backtest()

    def test_required_columns(self):
        required = {
            "cash", "stocks capital", "options capital",
            "total capital", "calls capital", "puts capital",
            "% change", "accumulated return",
        }
        actual = set(self.eng.balance.columns)
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"

    def test_per_stock_columns(self):
        for sym, _ in IVY_STOCKS_TUPLES:
            assert sym in self.eng.balance.columns
            assert f"{sym} qty" in self.eng.balance.columns


# ── Generated dataset invariants ───────────────────────────────────────

class TestGeneratedDataInvariants:

    @pytest.fixture(autouse=True)
    def _engine(self):
        self.eng = run_backtest(
            stocks=generated_stocks(),
            stocks_data=load_generated_stocks(),
            options_data=load_generated_options(),
        )

    def test_invariants(self):
        assert_invariants(self.eng, min_trades=5, label="generated")

    def test_many_balance_rows(self):
        assert len(self.eng.balance) >= 10

    def test_initial_capital(self):
        first_tc = self.eng.balance["total capital"].iloc[0]
        assert abs(first_tc - DEFAULT_CAPITAL) < 1.0


# ── Production SPY invariants ──────────────────────────────────────────

class TestProductionDataInvariants:

    @pytest.fixture(autouse=True)
    def _engine(self):
        self.eng = run_backtest(
            strategy_fn=lambda schema: buy_put_strategy(schema, underlying="SPY"),
            stocks=prod_spy_stocks(),
            stocks_data=load_prod_stocks(),
            options_data=load_prod_options(),
        )

    def test_invariants(self):
        assert_invariants(self.eng, min_trades=3, label="production")

    def test_capital_never_negative(self):
        tc = self.eng.balance["total capital"]
        assert (tc >= -1.0).all()


# ── Runtime invariant self-checks (assert_invariants flag) ─────────────
#
# Exercise the in-engine cash-flow (class A) and valuation (class B)
# invariants by enabling `assert_invariants` and confirming the CORRECTED
# engine does not trip them across the configurations where the "free puts"
# (class A) and adjClose-intrinsic (class B) bugs originally lived. If a
# regression reintroduces either bug the Rust engine returns an error, which
# surfaces here as an exception and fails the test.

import math as _math
import os as _os

from options_portfolio_backtester.engine.engine import BacktestEngine
from options_portfolio_backtester.execution.cost_model import NoCosts
from options_portfolio_backtester.execution.fill_model import MarketAtBidAsk
from options_portfolio_backtester.core.types import OptionType as _OptType, Direction as _Dir
from options_portfolio_backtester.strategy.strategy import Strategy as _Strategy
from options_portfolio_backtester.strategy.strategy_leg import StrategyLeg as _Leg
from options_portfolio_backtester.data.providers import (
    HistoricalOptionsData as _Opts, TiingoData as _Stx,
)
from options_portfolio_backtester.core.types import Stock as _Stock

_PROCESSED = _os.path.join(_os.path.dirname(__file__), "..", "..", "data", "processed")
# CSV pair (not parquet): these are the date-aligned outputs the article
# reproduction uses; the parquet carries one extra quotedate that trips the
# engine's stock/option date-alignment assert.
_SPY_OPTS = _os.path.join(_PROCESSED, "options.csv")
_SPY_STX = _os.path.join(_PROCESSED, "stocks.csv")
_needs_spy = pytest.mark.skipif(
    not (_os.path.exists(_SPY_OPTS) and _os.path.exists(_SPY_STX)),
    reason="needs processed SPY data: python data/fetch_data.py all --symbols SPY",
)


def _deep_otm_put(schema):
    leg = _Leg("leg_1", schema, option_type=_OptType.PUT, direction=_Dir.BUY)
    leg.entry_filter = (
        (schema.underlying == "SPY") & (schema.dte >= 90) & (schema.dte <= 180)
        & (schema.delta >= -0.10) & (schema.delta <= -0.02)
    )
    leg.entry_sort = ("delta", False)
    leg.exit_filter = schema.dte <= 14
    s = _Strategy(schema)
    s.add_leg(leg)
    s.add_exit_thresholds(profit_pct=_math.inf, loss_pct=_math.inf)
    return s


class TestRuntimeInvariantChecks:
    """The corrected engine must satisfy its own cash-flow and valuation
    invariants. These tests turn the checks on and assert no violation."""

    @pytest.fixture(scope="class")
    def spy_data(self):
        # Load the 3.3 GB option chain once for the whole class.
        return _Opts(_SPY_OPTS), _Stx(_SPY_STX)

    def _budget_engine(self, spy_data):
        opts, stx = spy_data
        eng = BacktestEngine(
            {"stocks": 1.0, "options": 0.0, "cash": 0.0},
            initial_capital=1_000_000,
            cost_model=NoCosts(),
            fill_model=MarketAtBidAsk(),
        )
        eng.assert_invariants = True
        eng.stocks = [_Stock("SPY", 1.0)]
        eng.stocks_data = stx
        eng.options_data = opts
        eng.options_strategy = _deep_otm_put(opts.schema)
        return eng

    def test_small_dataset_invariants_hold(self):
        # Fast self-funded-path check on the bundled small dataset: enabling the
        # invariants must not false-positive on a standard backtest.
        from tests.bench._test_helpers import (
            load_small_stocks, load_small_options, ivy_stocks, buy_put_strategy,
        )
        opts = load_small_options()
        eng = BacktestEngine(
            DEFAULT_ALLOC, initial_capital=DEFAULT_CAPITAL,
            cost_model=NoCosts(), fill_model=MarketAtBidAsk(),
        )
        eng.assert_invariants = True
        eng.stocks = ivy_stocks()
        eng.stocks_data = load_small_stocks()
        eng.options_data = opts
        eng.options_strategy = buy_put_strategy(opts.schema)
        eng.run(rebalance_freq=1, rebalance_unit="BMS")
        assert len(eng.balance) > 0

    @_needs_spy
    @pytest.mark.parametrize("annual_budget", [0.005, 0.020, 0.033])
    def test_spy_externally_funded_annual_invariants_hold(self, spy_data, annual_budget):
        eng = self._budget_engine(spy_data)
        eng.options_budget_annual_pct = annual_budget
        # No exception == both invariants held across the whole run.
        eng.run(rebalance_freq=1, rebalance_unit="BMS", check_exits_daily=True)
        assert len(eng.balance) > 1

    @_needs_spy
    def test_spy_per_rebalance_budget_invariants_hold(self, spy_data):
        # The per-rebalance framing (heavier premium spend) exercises far more
        # exits and intrinsic fallbacks — the regime where the bugs were loudest.
        eng = self._budget_engine(spy_data)
        eng.options_budget_pct = 0.033
        eng.run(rebalance_freq=1, rebalance_unit="BMS", check_exits_daily=False)
        assert len(eng.balance) > 1
