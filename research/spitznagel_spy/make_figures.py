"""Generate the Spitznagel article's figures from the pinned configuration.

Usage:
    python research/spitznagel_spy/make_figures.py [output_dir]

Runs the article-default strategy (3.3%/yr budget) and the SPY baseline via
the exact engine configuration in reproduce_article.py, then writes:

    figures/tearsheet.html   one self-contained report with every panel
    figures/*.json           each chart's vega-lite spec, for re-styling
                             (e.g. the blog regenerates its charts from these)

Requires the processed SPY data; see reproduce_article.py. Adds roughly one
backtest (~1 min) on top of nothing — the SPY baseline and strategy run once.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproduce_article import (  # noqa: E402
    DATA,
    OPTIONS_PATH,
    STOCKS_PATH,
    build_article_engine,
    build_spy_engine,
)

from options_portfolio_backtester.analytics.charts import apply_pyfolio_style  # noqa: E402
from options_portfolio_backtester.analytics.tearsheet import build_tearsheet  # noqa: E402
from options_portfolio_backtester.data.providers import (  # noqa: E402
    HistoricalOptionsData,
    TiingoData,
)

ARTICLE_BUDGET = 0.033


def _balance_of(engine) -> pd.DataFrame:
    bal = engine.balance.copy()
    bal.index = pd.to_datetime(bal.index)
    return bal


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent / "figures")
    if not OPTIONS_PATH.exists() or not STOCKS_PATH.exists():
        raise SystemExit(
            f"Need processed SPY data at {DATA}. Run:\n"
            f"    python scripts/fetch_data.py all --symbols SPY"
        )

    opts_data = HistoricalOptionsData(str(OPTIONS_PATH))
    stocks_data = TiingoData(str(STOCKS_PATH))
    schema = opts_data.schema

    print("Running SPY baseline …")
    spy = build_spy_engine(opts_data, stocks_data, schema)
    spy.run(rebalance_freq=1, rebalance_unit="BMS")

    print(f"Running article strategy ({ARTICLE_BUDGET:.1%}/yr budget) …")
    strat = build_article_engine(opts_data, stocks_data, schema,
                                 budget=ARTICLE_BUDGET)
    strat.run(rebalance_freq=2, rebalance_unit="BMS")

    report = build_tearsheet(
        _balance_of(strat),
        benchmark_balance=_balance_of(spy),
        trade_log=getattr(strat, "trade_log", None),
        budget_annual_pct=ARTICLE_BUDGET,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = report.to_file(out_dir / "tearsheet.html")
    print(f"Wrote {path}")

    for title, chart in report.charts().items():
        slug = title.lower().replace(" ", "-").replace("&", "and")
        spec_path = out_dir / f"{slug}.json"
        spec_path.write_text(apply_pyfolio_style(chart).to_json(), encoding="utf-8")
        print(f"Wrote {spec_path}")

    print("\nDone. Figures derive from the same engine configuration the "
          "article-reproduction test pins (tests/oracles/test_article_reproduction.py).")


if __name__ == "__main__":
    main()
