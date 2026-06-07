# Changelog

All notable changes to this project are documented here. Entries are
grouped by the kind of change so a reader can quickly find what
matters to them:

- **Behavioral changes** move documented backtest outputs (annual
  return, max drawdown, Sharpe, etc.). If you depend on a published
  reproduction, check this section first when upgrading.
- **API changes** add, remove, or rename public functions, classes, or
  attributes.
- **Tooling** changes the build, install, or CI surface.
- **Performance** changes runtime characteristics without changing
  results (within numeric noise).
- **Internal** refactors, formatting, and documentation that should not
  affect users.

The format follows [Keep a Changelog](https://keepachangelog.com/);
this project does not currently emit version tags, so each section is
anchored on the commit hash that introduced the change.

## Unreleased

### Behavioral changes
- *(none)*

### API changes
- `BacktestEngine.use_external_budget(annual_pct)` and
  `BacktestEngine.use_allocation(stocks, options, cash)` —
  first-class helpers that configure the two put-overlay framings in
  the literature's vocabulary. `use_external_budget` is the
  Spitznagel framing (100% stocks + external put budget);
  `use_allocation` is the AQR / allocation-reducing framing.
  Equivalent to the existing attribute-level configuration but
  self-documenting at the call site. (commit `60e6e91`)
- `options_portfolio_backtester.results.BacktestResults` —
  dataclass returned by `BacktestEngine.get_results()`. Bundles
  balance, trade log, config, engine version (read from
  `importlib.metadata`), and an optional data hash. Exposes computed
  properties for annual return, max drawdown, annualized volatility,
  and Sharpe ratio, plus a `summary()` dict. The companion
  `hash_data_file` helper computes the SHA-256 used in `data_hash`.
  (commit `e6605ec`)
- `options_portfolio_backtester.strategy.presets.deep_otm_put` and
  `near_atm_put_protection` — function-style presets for the two
  canonical tail-hedge configurations. `deep_otm_put` matches the
  Spitznagel configuration (delta -0.10 to -0.02, DTE 90-180, exit
  DTE 14). `near_atm_put_protection` matches AQR's PPUT-style
  configuration (~5% OTM, monthly DTE). Compose with the framing
  helpers above. (commit `e6605ec`)
- `HistoricalOptionsData` and `TiingoData` now accept `.parquet`
  files in addition to `.csv` and `.h5`. The SPY option chain loads
  in ~0.4s as parquet vs ~15s as CSV. (commit `e6605ec`)
- `data/fetch_data.py` writes both `processed/options.csv` and
  `processed/options.parquet`. Existing CSV-using code continues to
  work unchanged. Pass `--allow-fallback` to permit the secondary
  mirrors (options-data CDN, dataset-hist repo, yfinance) when the
  canonical GitHub Releases source is unreachable; default behaviour
  is now to fail loudly rather than silently substitute different
  bytes. The canonical SPY parquets are pinned by SHA-256 and the
  downloader warns on hash mismatch. (commit `60e6e91`)

### Tooling
- `PyO3 abi3-py311` feature enabled in `rust/ob_python/Cargo.toml`.
  The same extension now runs on Python 3.11+ including 3.14. The
  `make install-dev` target also sets
  `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` as a belt-and-braces fix
  for users on the latest Pythons. (commit `60e6e91`)
- `tests/test_article_reproduction.py` — pins the published
  Spitznagel article's SPY baseline and Spitznagel-framing budget
  table (0.5%, 1.0%, 2.0%, 3.3%) at the engine's current output,
  with tolerance 0.5pp on annual return, 1.0pp on max drawdown, and
  0.05 on Sharpe. Includes a sweet-spot shape test that asserts
  Sharpe peaks at 0.5%-1.0% budget. The CI workflow runs this as a
  dedicated step after the regular pytest pass. `make
  verify-articles` and `make verify-articles-smoke` run the full
  table and the fast qualitative check respectively from the shell.
  (commits `60e6e91`, `e6605ec`)
- `tests/test_results.py` — 8 unit tests for `BacktestResults` and
  `hash_data_file`. Synthetic balance series, no engine or data
  dependencies, runs in ~0.4s. (commit `00070d1`)
- `README.md` first-backtest example switched to the new ergonomic
  API: `deep_otm_put` preset + `use_external_budget` framing +
  `get_results()`. Roughly half the lines of the previous example,
  and every step names its own intent. (commit `6324a32`)

### Performance
- Parquet loading: a 17-year SPY option chain (22M rows) loads in
  ~0.4 seconds via `HistoricalOptionsData("options.parquet")`
  versus ~15.4 seconds via `options.csv`. Disk footprint drops from
  3.2 GB to 593 MB. CI / smoke runs against article reproductions
  speed up accordingly. (commit `e6605ec`)

### Internal
- Module-level logger added to `options_portfolio_backtester.data.providers`.
  Foundation for follow-up structured-logging conversions; the
  package itself does not emit `print()` calls and behaviour is
  unchanged. (commit `e6605ec`)

---

## Behavioral changes pre-Unreleased (historical, from git log)

These are the engine commits that moved documented backtest outputs
in the period before this CHANGELOG was started. Listed here so
downstream reproductions can audit which engine they were generated
against.

- `523ba10` **Fix cash leakage in externally-funded budget path.**
  The externally-funded budget path (Spitznagel framing) was
  inflating returns due to cash leaking in across rebalances. The
  fix correctly accounts cash; post-fix annual returns for typical
  budgets dropped by 2-20 percentage points relative to the pre-fix
  values. Articles that depended on pre-fix numbers — notably the
  Spitznagel tail-hedge piece at federicocarrone.com — have since
  been updated against the corrected engine, and
  `tests/test_article_reproduction.py` pins the post-fix numbers.
- `d42eec0` **Fix budget mode: 100% stock allocation + credit sale
  proceeds.** Earlier the budget mode misallocated proceeds from
  option sales; the fix credits them correctly into the cash bucket.
  Affects any backtest using `options_budget_pct`.
- `5840620` **Fix budget-mode stock allocation: use liquid capital,
  not total capital.** The stock-position sizing in budget mode
  previously sized off total capital including the value of open
  option positions, which double-counted. The fix uses liquid
  capital. Small effect at small budgets, larger as budget grows.
- `b78602d` **Fix budget-mode double-counting of options capital in
  Python engine.** Companion to `5840620`, in the Python engine
  rather than the Rust path. (Now obsolete since the Python engine
  was removed in `0951478` — Rust is the only backend.)
- `ffdfd1d` **Revert full liquidation, fix accounting with cash =
  total - options_capital.** The earlier "full liquidation at
  rebalance" behaviour was reverted in favour of a partial trim;
  cash accounting was also corrected. Affects any multi-rebalance
  backtest.
- `62c4fd5` **Restore `_sell_some_options` to trim excess puts at
  rebalance.** Restores incremental trim behaviour that was lost
  during the Rust port.
- `264e440` **Full options liquidation at rebalance.** The earlier
  step before `ffdfd1d` reverted this. Listed for completeness.

For complete history, see `git log`. The convention going forward
is: any commit that moves a documented backtest output gets a
`Behavioral changes` entry above and a `tests/test_article_reproduction.py`
update in the same PR.
