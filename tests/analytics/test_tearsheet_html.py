"""Tests for the chart-embedding tearsheet HTML and the returns adapter."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from options_portfolio_backtester.analytics.results import (
    BacktestResults,
    returns_from_balance,
)
from options_portfolio_backtester.analytics.tearsheet import (
    build_tearsheet,
    top_drawdowns,
)


def _balance(start: str = "2020-01-01", periods: int = 200) -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq="B")
    rng = np.random.default_rng(11)
    total = 100_000 * np.cumprod(1 + rng.normal(0.0004, 0.01, periods))
    bal = pd.DataFrame({"total capital": total}, index=idx)
    bal["options capital"] = total * 0.02
    bal["cash"] = total * 0.03
    bal["stocks capital"] = total * 0.95
    bal["% change"] = bal["total capital"].pct_change()
    return bal


# ---------------------------------------------------------------------------
# Phase 1: returns adapter
# ---------------------------------------------------------------------------

def test_returns_from_balance_shape():
    rets = returns_from_balance(_balance())
    assert isinstance(rets.index, pd.DatetimeIndex)
    assert rets.name == "strategy"
    assert not rets.isna().any()
    assert len(rets) == 199  # pct_change drops the first row


def test_returns_from_balance_empty_and_missing_column():
    assert returns_from_balance(pd.DataFrame()).empty
    bad = pd.DataFrame({"other": [1.0]}, index=pd.date_range("2020-01-01", periods=1))
    assert returns_from_balance(bad, name="x").name == "x"


def test_backtest_results_returns_property():
    results = BacktestResults(balance=_balance(), trade_log=None, config={})
    rets = results.returns
    assert rets.name == "strategy"
    assert len(rets) > 0


def test_quantstats_accepts_returns():
    qs = pytest.importorskip("quantstats")
    results = BacktestResults(balance=_balance(), trade_log=None, config={})
    sharpe = qs.stats.sharpe(results.returns)
    assert np.isfinite(sharpe)


# ---------------------------------------------------------------------------
# Phase 2: top_drawdowns
# ---------------------------------------------------------------------------

def test_top_drawdowns_known_episode():
    idx = pd.date_range("2024-01-01", periods=7, freq="B")
    bal = pd.DataFrame(
        {"total capital": [100, 100, 80, 90, 100, 110, 105]}, index=idx)
    table = top_drawdowns(bal)
    assert len(table) == 2  # the -20% episode and the open -4.5% one
    worst = table.iloc[0]
    assert worst["depth"] == -20.0
    assert worst["trough"] == idx[2]
    assert worst["recovery"] == idx[4]


def test_top_drawdowns_open_episode_has_nat_recovery():
    idx = pd.date_range("2024-01-01", periods=4, freq="B")
    bal = pd.DataFrame({"total capital": [100, 110, 90, 95]}, index=idx)
    table = top_drawdowns(bal)
    assert pd.isna(table.iloc[0]["recovery"])


def test_top_drawdowns_flat_and_empty():
    assert top_drawdowns(None).empty
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    flat = pd.DataFrame({"total capital": [100.0] * 5}, index=idx)
    assert top_drawdowns(flat).empty


# ---------------------------------------------------------------------------
# Phase 2/3: chart assembly and HTML embedding
# ---------------------------------------------------------------------------

def test_charts_assembles_options_panels():
    report = build_tearsheet(_balance())
    panels = report.charts()
    for expected in ("Equity curve", "Underwater plot", "Rolling Sharpe",
                     "Capital allocation", "P&L attribution", "Options exposure",
                     "Crash windows"):
        assert expected in panels, expected


def test_charts_skips_unavailable_panels():
    bal = _balance()[["total capital", "% change"]]
    panels = build_tearsheet(bal).charts()
    assert "P&L attribution" not in panels
    assert "Per-trade P&L" not in panels
    assert "Equity curve" in panels


def test_charts_empty_without_balance():
    from options_portfolio_backtester.analytics.tearsheet import TearsheetReport
    from options_portfolio_backtester.analytics.stats import BacktestStats
    report = build_tearsheet(_balance())
    bare = TearsheetReport(
        stats=report.stats, stats_table=report.stats_table,
        monthly_returns=report.monthly_returns,
        drawdown_series=report.drawdown_series)
    assert bare.charts() == {}


def test_to_html_embeds_charts():
    html = build_tearsheet(_balance()).to_html()
    assert "<html>" in html
    assert "stats-table" in html
    assert "Equity curve" in html
    # charts present either as inline SVG or vega-embed divs
    assert "<svg" in html or "vegaEmbed" in html


def test_to_html_without_charts_is_tables_only():
    html = build_tearsheet(_balance()).to_html(include_charts=False)
    assert "stats-table" in html
    assert "vegaEmbed" not in html and "<svg" not in html


def test_to_file_writes_report(tmp_path):
    path = build_tearsheet(_balance()).to_file(tmp_path / "sub" / "report.html")
    assert path.exists()
    assert "<html>" in path.read_text()


def test_benchmark_appears_in_equity_curve():
    bal = _balance()
    bench = bal.copy()
    bench["total capital"] *= 0.95
    report = build_tearsheet(bal, benchmark_balance=bench)
    chart = report.charts()["Equity curve"]
    lines = chart.layer[0]  # layer 0 = series lines, layer 1 = 1.0 reference rule
    assert set(lines.data["series"]) == {"strategy", "benchmark"}
    spec = chart.to_dict()
    color_scale = spec["layer"][0]["encoding"]["color"]["scale"]
    assert color_scale["range"] == ["forestgreen", "gray"]  # pyfolio palette


def test_trade_log_supplies_pnls_and_panels():
    from options_portfolio_backtester.analytics.trade_log import TradeLog, Trade
    from options_portfolio_backtester.core.types import Order
    tl = TradeLog()
    tl.add_trade(Trade(
        contract="SPY200417P00200000", underlying="SPY", option_type="put",
        strike=200.0, entry_date=pd.Timestamp("2020-02-03"),
        exit_date=pd.Timestamp("2020-03-20"), entry_price=1.0, exit_price=20.0,
        quantity=5, shares_per_contract=100,
        entry_order=Order.BTO, exit_order=Order.STC))
    report = build_tearsheet(_balance(), trade_log=tl, budget_annual_pct=0.033)
    assert report.stats.total_trades == 1
    panels = report.charts()
    assert "Per-trade P&L" in panels
    assert "Premium spend" in panels


# ---------------------------------------------------------------------------
# thinning keeps long backtests under altair's row limit
# ---------------------------------------------------------------------------

def test_long_backtest_charts_serialize():
    bal = _balance(periods=6000)
    bench = bal.copy()
    report = build_tearsheet(bal, benchmark_balance=bench)
    for title, chart in report.charts().items():
        chart.to_json()  # raises MaxRowsError if thinning failed


def test_thin_for_chart_keeps_endpoints():
    from options_portfolio_backtester.analytics.charts import thin_for_chart
    s = pd.Series(range(10_000), index=pd.date_range("2000-01-03", periods=10_000, freq="B"))
    thinned = thin_for_chart(s)
    assert len(thinned) <= 2001
    assert thinned.index[0] == s.index[0]
    assert thinned.index[-1] == s.index[-1]
