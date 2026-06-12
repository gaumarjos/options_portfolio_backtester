"""Tearsheet report: stats tables plus an embedded-chart HTML document.

``build_tearsheet(...)`` returns a :class:`TearsheetReport`;
``report.to_file("report.html")`` writes a single document with every panel —
the pyfolio experience, one call, one file.

Chart embedding: when ``vl-convert-python`` is installed (the ``charts``
extra), charts are inlined as static SVG and the HTML is fully offline.
Otherwise charts render interactively through the vega-embed CDN scripts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from options_portfolio_backtester.analytics.results import returns_from_balance
from options_portfolio_backtester.analytics.stats import BacktestStats, extended_stats


@dataclass
class TearsheetReport:
    """Container for common report artifacts."""

    stats: BacktestStats
    stats_table: pd.DataFrame
    monthly_returns: pd.DataFrame
    drawdown_series: pd.Series
    balance: Optional[pd.DataFrame] = None
    benchmark_balance: Optional[pd.DataFrame] = None
    trade_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    budget_annual_pct: Optional[float] = None

    def to_dict(self) -> dict[str, object]:
        return {
            "stats": self.stats,
            "stats_table": self.stats_table,
            "monthly_returns": self.monthly_returns,
            "drawdown_series": self.drawdown_series,
        }

    def to_csv(self, directory: str | Path) -> dict[str, Path]:
        out_dir = Path(directory)
        out_dir.mkdir(parents=True, exist_ok=True)
        stats_path = out_dir / "stats_table.csv"
        monthly_path = out_dir / "monthly_returns.csv"
        drawdown_path = out_dir / "drawdown_series.csv"
        self.stats_table.to_csv(stats_path)
        self.monthly_returns.to_csv(monthly_path)
        self.drawdown_series.rename("drawdown").to_frame().to_csv(drawdown_path)
        return {
            "stats_table": stats_path,
            "monthly_returns": monthly_path,
            "drawdown_series": drawdown_path,
        }

    def to_markdown(self) -> str:
        lines = ["# Tearsheet", "", "## Summary", ""]
        try:
            lines.extend(self.stats_table.to_markdown().splitlines())
        except Exception:
            lines.extend(self.stats_table.to_string().splitlines())
        lines.extend(["", "## Monthly Returns", ""])
        if self.monthly_returns.empty:
            lines.append("_No monthly returns available._")
        else:
            try:
                lines.extend(self.monthly_returns.to_markdown().splitlines())
            except Exception:
                lines.extend(self.monthly_returns.to_string().splitlines())
        return "\n".join(lines)

    # ------------------------------------------------------------- charts
    def charts(self) -> dict[str, Any]:
        """Assemble every chart panel whose inputs are available.

        Returns an ordered ``{section title: alt.Chart}`` dict. Panels whose
        inputs are missing (no balance, no trade log, no capital-split
        columns) are silently skipped so the report degrades gracefully.
        """
        from options_portfolio_backtester.analytics import charts as c
        from options_portfolio_backtester.analytics import options_charts as oc

        if self.balance is None or self.balance.empty:
            return {}
        out: dict[str, Any] = {}
        # Log scale: over a long sample, linear growth-of-$1 visually
        # exaggerates the recent years and compresses the early crashes.
        out["Equity curve"] = c.equity_curve_chart(
            self.balance, self.benchmark_balance, log_scale=True,
            drawdown_periods=top_drawdowns(self.balance))
        if not self.drawdown_series.empty:
            out["Underwater plot"] = c.underwater_chart(self.drawdown_series)
        out["Rolling Sharpe"] = c.rolling_sharpe_chart(self.balance)
        out["Rolling volatility"] = c.rolling_volatility_chart(self.balance)
        if "% change" in self.balance.columns:
            out["Return distribution"] = c.returns_histogram(
                self.balance[["% change"]].dropna())
        if "total capital" in self.balance.columns:
            out["Annual returns"] = c.annual_returns_chart(self.balance)
            out["Monthly returns heatmap"] = c.monthly_returns_heatmap(self.balance)
        if "options capital" in self.balance.columns:
            out["Options exposure"] = oc.exposure_chart(self.balance)
        crash = oc.crash_window_chart(self.balance, self.benchmark_balance)
        if crash is not None:
            out["Crash windows"] = crash
        if not self.trade_df.empty:
            out["Options P&L decomposition"] = oc.options_pnl_decomposition_chart(
                self.trade_df, self.balance)
            out["Per-trade P&L"] = oc.trade_pnl_chart(self.trade_df)
            out["Trade payoff distribution"] = oc.trade_return_histogram(self.trade_df)
            out["Premium spend"] = oc.premium_spend_chart(
                self.trade_df, self.balance, self.budget_annual_pct)
        return out

    def to_html(self, include_charts: bool = True) -> str:
        summary = self.stats_table.to_html(classes="stats-table")
        monthly = (
            self.monthly_returns.to_html(classes="monthly-returns")
            if not self.monthly_returns.empty
            else "<p>No monthly returns available.</p>"
        )
        dd_table = top_drawdowns(self.balance) if self.balance is not None else pd.DataFrame()
        drawdowns = (
            dd_table.to_html(classes="top-drawdowns", index=False)
            if not dd_table.empty
            else ""
        )

        sections = [
            "<h1>Tearsheet</h1>",
            "<h2>Summary</h2>", summary,
            "<h2>Monthly Returns</h2>", monthly,
        ]
        if drawdowns:
            sections += ["<h2>Top Drawdowns</h2>", drawdowns]
        if self.balance is not None:
            stress = stress_events_table(self.balance, self.benchmark_balance)
            if not stress.empty:
                formatted = stress.copy()
                for col in formatted.columns:
                    if col != "event":
                        formatted[col] = formatted[col].map(
                            lambda v: f"{v:+.1%}" if pd.notna(v) else "")
                sections += ["<h2>Stress Events</h2>",
                             formatted.to_html(classes="stress-events", index=False)]

        head_extra = ""
        if include_charts:
            charts = self.charts()
            rendered, needs_vega = _render_charts(charts)
            sections += rendered
            if needs_vega:
                head_extra = (
                    '<script src="https://cdn.jsdelivr.net/npm/vega@5"></script>'
                    '<script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>'
                    '<script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>'
                )

        style = (
            "<style>"
            "body{font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;"
            "color:#333;max-width:880px;margin:2.5rem auto;padding:0 1.25rem;"
            "line-height:1.45}"
            "h1{font-size:1.7rem;font-weight:600;border-bottom:2px solid #333;"
            "padding-bottom:.4rem;margin-bottom:1.5rem}"
            "h2{font-size:1.1rem;font-weight:600;color:#444;margin:2.5rem 0 .75rem;"
            "border-bottom:1px solid #ddd;padding-bottom:.25rem}"
            "table{border-collapse:collapse;font-size:.85rem;margin:.5rem 0}"
            "th{background:#f5f5f5;font-weight:600}"
            "td,th{border:1px solid #e0e0e0;padding:5px 10px;text-align:right}"
            "tbody tr:nth-child(even){background:#fafafa}"
            "svg{max-width:100%;height:auto}"
            "</style>"
        )
        return (
            "<html><head><meta charset='utf-8'><title>Tearsheet</title>"
            f"{style}{head_extra}</head><body>"
            + "".join(sections)
            + "</body></html>"
        )

    def to_file(self, path: str | Path, include_charts: bool = True) -> Path:
        """Write the HTML report to ``path`` and return it."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.to_html(include_charts=include_charts), encoding="utf-8")
        return out


def _render_charts(charts: dict[str, Any]) -> tuple[list[str], bool]:
    """Render charts to HTML fragments.

    Prefers static inline SVG via vl-convert (fully offline document); falls
    back to vega-embed divs that need the CDN scripts. Returns the fragments
    and whether the CDN scripts are required.
    """
    from options_portfolio_backtester.analytics.charts import apply_pyfolio_style

    try:
        import vl_convert  # type: ignore
        have_vl = True
    except ImportError:
        have_vl = False

    fragments: list[str] = []
    needs_vega = False
    for i, (title, chart) in enumerate(charts.items()):
        fragments.append(f"<h2>{title}</h2>")
        spec = apply_pyfolio_style(chart).to_json()
        if have_vl:
            try:
                svg = vl_convert.vegalite_to_svg(spec)
                fragments.append(svg)
                continue
            except Exception:
                pass  # fall through to vega-embed for this chart
        needs_vega = True
        div_id = f"chart-{i}"
        fragments.append(
            f'<div id="{div_id}"></div>'
            f"<script>vegaEmbed('#{div_id}', {spec});</script>"
        )
    return fragments, needs_vega


def monthly_return_table(balance: pd.DataFrame) -> pd.DataFrame:
    if balance.empty or "% change" not in balance.columns:
        return pd.DataFrame()
    rets = balance["% change"].dropna()
    if rets.empty:
        return pd.DataFrame()
    monthly = (1.0 + rets).groupby(pd.Grouper(freq="ME")).prod() - 1.0
    out = monthly.to_frame(name="return")
    out["year"] = out.index.year
    out["month"] = out.index.month
    return out.pivot(index="year", columns="month", values="return").sort_index()


def drawdown_series(balance: pd.DataFrame) -> pd.Series:
    if balance.empty or "total capital" not in balance.columns:
        return pd.Series(dtype=float)
    total = balance["total capital"].dropna()
    if total.empty:
        return pd.Series(dtype=float)
    peak = total.cummax()
    return (total - peak) / peak


def stress_events_table(balance: pd.DataFrame,
                        benchmark_balance: pd.DataFrame | None = None,
                        windows: dict[str, tuple[str, str]] | None = None) -> pd.DataFrame:
    """pyfolio's "interesting times" analysis: return and max drawdown per
    stress event window, strategy vs benchmark. Windows outside the sample
    are skipped."""
    from options_portfolio_backtester.analytics.options_charts import DEFAULT_CRASH_WINDOWS

    windows = windows or DEFAULT_CRASH_WINDOWS
    rows = []
    for label, (start, end) in windows.items():
        window = balance.loc[start:end]
        if window.empty:
            continue
        total = window["total capital"].dropna()
        row = {
            "event": label,
            "strategy return": total.iloc[-1] / total.iloc[0] - 1,
            "strategy max DD": ((total - total.cummax()) / total.cummax()).min(),
        }
        if benchmark_balance is not None and not benchmark_balance.empty:
            bench = benchmark_balance.loc[start:end]["total capital"].dropna()
            if not bench.empty:
                row["benchmark return"] = bench.iloc[-1] / bench.iloc[0] - 1
                row["benchmark max DD"] = ((bench - bench.cummax()) / bench.cummax()).min()
        rows.append(row)
    return pd.DataFrame(rows)


def top_drawdowns(balance: pd.DataFrame | None, n: int = 5) -> pd.DataFrame:
    """The ``n`` worst drawdown episodes: peak, trough, recovery, depth, duration.

    Recovery is NaT for a drawdown still open at the end of the sample.
    """
    if balance is None:
        return pd.DataFrame()
    dd = drawdown_series(balance)
    if dd.empty:
        return pd.DataFrame()

    episodes = []
    in_dd = False
    peak_date = dd.index[0]
    for date, value in dd.items():
        if not in_dd and value < 0:
            in_dd = True
            start = peak_date
        elif in_dd and value == 0:
            segment = dd.loc[start:date]
            episodes.append((start, segment.idxmin(), date, segment.min()))
            in_dd = False
        if value == 0:
            peak_date = date
    if in_dd:
        segment = dd.loc[start:]
        episodes.append((start, segment.idxmin(), pd.NaT, segment.min()))

    if not episodes:
        return pd.DataFrame()
    table = pd.DataFrame(episodes, columns=["peak", "trough", "recovery", "depth"])
    table["depth"] = (table["depth"] * 100).round(2)
    end_date = dd.index[-1]
    table["duration_days"] = (
        table["recovery"].fillna(end_date) - table["peak"]
    ).dt.days
    return table.nsmallest(n, "depth").reset_index(drop=True)


def build_tearsheet(
    balance: pd.DataFrame,
    trade_pnls=None,
    risk_free_rate: float = 0.0,
    *,
    benchmark_balance: pd.DataFrame | None = None,
    trade_log=None,
    budget_annual_pct: float | None = None,
) -> TearsheetReport:
    """Build a :class:`TearsheetReport` from a backtest's outputs.

    ``trade_log`` accepts a :class:`TradeLog`, a flat per-trade DataFrame, or
    the legacy MultiIndex frame from ``engine.run()``. When given, it powers
    the per-trade and premium-spend panels, and supplies ``trade_pnls`` for
    the stats block unless those were passed explicitly.
    """
    from options_portfolio_backtester.analytics.options_charts import normalize_trade_log

    trade_df = normalize_trade_log(trade_log)
    if trade_pnls is None and not trade_df.empty:
        trade_pnls = trade_df["net_pnl"].to_numpy()
    trade_arr = None if trade_pnls is None else np.asarray(trade_pnls, dtype=float)
    stats = BacktestStats.from_balance(balance, trade_pnls=trade_arr, risk_free_rate=risk_free_rate)
    table = stats.to_dataframe()

    # pyfolio-parity extras (stability, omega, VaR, alpha/beta) plus a
    # side-by-side benchmark column when a benchmark is supplied.
    rets = returns_from_balance(balance)
    bench_rets = (returns_from_balance(benchmark_balance, name="benchmark")
                  if benchmark_balance is not None else None)
    for label, value in extended_stats(rets, bench_rets).items():
        table.loc[label, "Value"] = value
    if benchmark_balance is not None and not benchmark_balance.empty:
        bench_table = BacktestStats.from_balance(benchmark_balance) \
            .to_dataframe().rename(columns={"Value": "Benchmark"})
        for label, value in extended_stats(bench_rets).items():
            bench_table.loc[label, "Benchmark"] = value
        table = table.join(bench_table, how="left")

    monthly = monthly_return_table(balance)
    dd = drawdown_series(balance)
    return TearsheetReport(
        stats=stats,
        stats_table=table,
        monthly_returns=monthly,
        drawdown_series=dd,
        balance=balance,
        benchmark_balance=benchmark_balance,
        trade_df=trade_df,
        budget_annual_pct=budget_annual_pct,
    )
