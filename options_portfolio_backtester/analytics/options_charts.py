"""Options-specific tearsheet panels.

These are the charts no generic returns library provides: P&L attribution
between the equity and options legs, premium spend against the configured
budget, crash-window zooms, and the long-left-cluster / rare-huge-winner
trade distribution that deep-OTM puts produce.

All functions take the engine's ``balance`` frame and/or a *flat* trade
DataFrame (``TradeLog.to_dataframe()`` schema). Use :func:`normalize_trade_log`
to accept whatever the caller has — a :class:`TradeLog`, a flat frame, or the
legacy MultiIndex trade log returned by ``BacktestEngine.run()``.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

from options_portfolio_backtester.analytics.charts import thin_for_chart
from options_portfolio_backtester.analytics.trade_log import TradeLog

SHARES_PER_CONTRACT = 100

# Default event windows for crash zoom panels (label -> (start, end)).
DEFAULT_CRASH_WINDOWS: dict[str, tuple[str, str]] = {
    "GFC 2008-09": ("2008-09-01", "2009-06-30"),
    "COVID 2020": ("2020-02-01", "2020-06-30"),
    "2022 bear": ("2022-01-01", "2022-12-31"),
}


def normalize_trade_log(trade_log) -> pd.DataFrame:
    """Coerce any trade-log representation to the flat per-trade DataFrame.

    Accepts a :class:`TradeLog`, an already-flat DataFrame (must have a
    ``net_pnl`` column), the legacy MultiIndex frame from ``engine.run()``,
    or ``None``. Returns an empty frame when there is nothing to convert.
    """
    if trade_log is None:
        return pd.DataFrame()
    if isinstance(trade_log, TradeLog):
        return trade_log.to_dataframe()
    if isinstance(trade_log, pd.DataFrame):
        if trade_log.empty:
            return pd.DataFrame()
        if isinstance(trade_log.columns, pd.MultiIndex):
            return TradeLog.from_legacy_trade_log(trade_log).to_dataframe()
        if "net_pnl" in trade_log.columns:
            return trade_log
    raise TypeError(f"Unsupported trade log type: {type(trade_log)!r}")


def pnl_attribution_chart(balance: pd.DataFrame) -> alt.Chart:
    """Equity leg vs options leg P&L contribution over time.

    Cumulative change of each capital component relative to day one, so the
    premium-bleed-then-crash-payoff sawtooth of the options leg is visible
    instead of buried in the blended total.
    """
    cols = [c for c in ("stocks capital", "options capital", "cash") if c in balance.columns]
    if not cols:
        return alt.Chart(pd.DataFrame({"date": [], "pnl": [], "leg": []})).mark_line()
    initial_total = balance["total capital"].dropna().iloc[0]
    # melt multiplies rows by len(cols); thin the wide frame accordingly
    deltas = thin_for_chart(balance[cols].sub(balance[cols].iloc[0]).div(initial_total),
                            max_rows=2000 // len(cols))
    data = deltas.rename_axis("date").reset_index().melt(
        id_vars="date", var_name="leg", value_name="pnl")
    # Symlog y-scale: over a long sample the equity leg compounds to many
    # hundreds of percent while the options leg oscillates within a few
    # percent of zero — on a linear axis the bleed/payoff sawtooth (the
    # whole point of this panel) flattens into an invisible line.
    return alt.Chart(data).mark_line(strokeWidth=2).encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("pnl:Q", title="Cumulative P&L (share of initial capital, symlog)",
                scale=alt.Scale(type="symlog", constant=0.02),
                axis=alt.Axis(format="%")),
        color=alt.Color("leg:N", title=None,
                        scale=alt.Scale(
                            domain=["stocks capital", "options capital", "cash"],
                            range=["forestgreen", "orangered", "gray"])),
        tooltip=["date:T", "leg:N", alt.Tooltip("pnl:Q", format=".2%")],
    ).properties(width=700, height=250, title="P&L attribution by leg")


def premium_spend_chart(trade_df: pd.DataFrame,
                        balance: pd.DataFrame,
                        budget_annual_pct: float | None = None,
                        window_days: int = 252) -> alt.Chart:
    """Realized rolling annual premium spend vs the configured budget.

    Premium per trade is signed by the entry order — buys (BTO) are debits,
    sells (STO) are credits — and uses the per-trade contract multiplier when
    the frame carries one (``shares_per_contract`` column), falling back to
    the standard 100. The rolling one-year net sum is divided by total
    capital on each day. Drift away from the budget line is a config-bug
    detector.
    """
    empty = alt.Chart(pd.DataFrame({"date": [], "spend": []})).mark_line()
    if trade_df.empty or balance.empty:
        return empty
    multiplier = (trade_df["shares_per_contract"]
                  if "shares_per_contract" in trade_df.columns
                  else SHARES_PER_CONTRACT)
    sign = (trade_df["entry_order"].map(lambda o: -1.0 if str(o) in ("STO", "Order.STO") else 1.0)
            if "entry_order" in trade_df.columns else 1.0)
    premiums = (
        trade_df.assign(premium=trade_df["entry_price"].abs()
                        * trade_df["quantity"].abs() * multiplier * sign)
        .groupby("entry_date")["premium"].sum()
    )
    # Align on normalized dates so intraday timestamps still land on the
    # right balance row instead of being silently dropped.
    premiums.index = pd.to_datetime(premiums.index).normalize()
    premiums = premiums.groupby(level=0).sum()
    balance_days = pd.to_datetime(balance.index).normalize()
    daily = premiums.reindex(balance_days, fill_value=0.0)
    daily.index = balance.index
    rolling_spend = daily.rolling(f"{window_days}D").sum()
    spend_pct = (rolling_spend / balance["total capital"]).dropna()
    data = thin_for_chart(spend_pct).rename("spend").rename_axis("date").reset_index()

    line = alt.Chart(data).mark_line(color="orangered", opacity=0.8,
                                     strokeWidth=2.5).encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("spend:Q", title="Rolling 1y premium spend", axis=alt.Axis(format="%")),
        tooltip=["date:T", alt.Tooltip("spend:Q", format=".2%")],
    )
    chart = line
    if budget_annual_pct is not None:
        rule = alt.Chart(pd.DataFrame({"budget": [budget_annual_pct]})).mark_rule(
            strokeDash=[6, 4], color="steelblue", strokeWidth=2).encode(y="budget:Q")
        chart = line + rule
    return chart.properties(width=700, height=200,
                            title="Premium spend vs budget (rolling 1 year)")


def crash_window_chart(balance: pd.DataFrame,
                       benchmark_balance: pd.DataFrame | None = None,
                       windows: dict[str, tuple[str, str]] | None = None) -> alt.VConcatChart | alt.Chart | None:
    """Day-by-day zoom panels over crash windows, indexed to 100 at window start.

    Shows the strategy (and benchmark, when given) through each event so the
    put payoff and the redeploy-into-equity mechanics are visible. Windows
    not covered by the balance index are skipped; returns ``None`` when no
    window overlaps the sample.
    """
    windows = windows or DEFAULT_CRASH_WINDOWS
    panels = []
    for label, (start, end) in windows.items():
        window = balance.loc[start:end]
        if window.empty:
            continue
        frames = [pd.DataFrame({
            "date": window.index,
            "value": window["total capital"] / window["total capital"].iloc[0] * 100,
            "series": "strategy",
        })]
        if benchmark_balance is not None and not benchmark_balance.empty:
            bench = benchmark_balance.loc[start:end]
            if not bench.empty:
                frames.append(pd.DataFrame({
                    "date": bench.index,
                    "value": bench["total capital"] / bench["total capital"].iloc[0] * 100,
                    "series": "benchmark",
                }))
        data = pd.concat(frames, ignore_index=True)
        panels.append(
            alt.Chart(data).mark_line().encode(
                x=alt.X("date:T", title=None),
                y=alt.Y("value:Q", title="Indexed (window start = 100)",
                        scale=alt.Scale(zero=False)),
                color=alt.Color("series:N", title=None),
                tooltip=["date:T", "series:N", alt.Tooltip("value:Q", format=".1f")],
            ).properties(width=700, height=180, title=f"Crash window: {label}")
        )
    if not panels:
        return None
    return alt.vconcat(*panels) if len(panels) > 1 else panels[0]


def trade_pnl_chart(trade_df: pd.DataFrame) -> alt.Chart:
    """Per-trade net P&L ordered by exit date, on a symlog scale.

    A plain histogram hides the structure of deep-OTM put trades: many small
    losses and a few enormous winners. Symlog keeps both visible.
    """
    if trade_df.empty:
        return alt.Chart(pd.DataFrame({"exit_date": [], "net_pnl": []})).mark_bar()
    data = trade_df[["exit_date", "net_pnl", "contract"]].copy()
    data["outcome"] = (data["net_pnl"] > 0).map({True: "win", False: "loss"})
    return alt.Chart(data).mark_bar().encode(
        x=alt.X("exit_date:T", title="Exit date"),
        y=alt.Y("net_pnl:Q", title="Net P&L per trade ($, symlog)",
                scale=alt.Scale(type="symlog")),
        color=alt.Color("outcome:N", title=None,
                        scale=alt.Scale(domain=["win", "loss"],
                                        range=["forestgreen", "coral"])),
        tooltip=["exit_date:T", "contract:N", alt.Tooltip("net_pnl:Q", format="$,.0f")],
    ).properties(width=700, height=250, title="Per-trade net P&L (symlog scale)")


def exposure_chart(balance: pd.DataFrame) -> alt.Chart:
    """Options-leg market value as a share of total capital over time."""
    if "options capital" not in balance.columns:
        return alt.Chart(pd.DataFrame({"date": [], "exposure": []})).mark_area()
    exposure = (balance["options capital"] / balance["total capital"]).dropna()
    data = thin_for_chart(exposure).rename("exposure").rename_axis("date").reset_index()
    return alt.Chart(data).mark_area(opacity=0.7, color="steelblue").encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("exposure:Q", title="Options share of capital", axis=alt.Axis(format="%")),
        tooltip=["date:T", alt.Tooltip("exposure:Q", format=".2%")],
    ).properties(width=700, height=180, title="Options exposure over time")


__all__ = [
    "DEFAULT_CRASH_WINDOWS",
    "normalize_trade_log",
    "pnl_attribution_chart",
    "premium_spend_chart",
    "crash_window_chart",
    "trade_pnl_chart",
    "exposure_chart",
]
