# Spitznagel SPY/SPX tail-hedge research

Reproductions and robustness studies for the tail-hedge article
([federicocarrone.com](https://federicocarrone.com/series/leptokurtic/the-tail-hedge-debate-spitznagel-is-right/)).

## Layout

```
reproduce_article.py      canonical reproduction — prints every article table
                          + a fingerprint (engine version, commit, data SHAs)
make_figures.py           regenerate the article's charts into figures/
experiments/              exploratory studies (each standalone, skips if data absent)
  spx_sweep.py            OTM-depth x DTE x budget sweep over 1996-2025
  cross_underlying.py     SPY / QQQ / IWM robustness, window-matched controls
  signal_experiments.py   signal-gated entry + monetization battery
findings/                 written-up conclusions (read these first)
  CROSS_UNDERLYING.md
  SIGNAL_EXPERIMENTS.md
  DATA_COVERAGE.md        deep-OTM puts absent from pre-2003 SPX chain
  REGIME_RESULTS_25OTM.md per-regime hedged-vs-unhedged at a fillable depth
figures/                  generated chart output (gitignored)
```

## Data

All scripts need the processed SPX/ETF parquet under `data/processed/`
(see [`../../data/DATA_NOTICE.md`](../../data/DATA_NOTICE.md)). The SPX series
is purchased DeltaNeutral ALLSPX — **local-only, never committed**. Every
script resolves the repo root by searching upward for `pyproject.toml` and
**skips cleanly if the data is absent**, so the repo stays runnable without it.

```
python research/spitznagel_spy/reproduce_article.py
python research/spitznagel_spy/experiments/spx_sweep.py [regime]
python research/spitznagel_spy/experiments/signal_experiments.py
```

## Key findings (one line each — details in `findings/`)

1. **Crash *shape* decides it.** Deep-OTM hedging wins big in fast crashes
   (GFC +6pp, COVID +11pp) and loses in slow grinds (dot-com −1.7pp at
   25–30% OTM — **the 40–45% depth is not listed in the 2000–2002 SPX chain**,
   so that band's dot-com number is a coverage artifact; see
   [`findings/DATA_COVERAGE.md`](findings/DATA_COVERAGE.md)).
2. **Over the full 1996-2025 it's ~neutral** (+0.95pp at best) — the article's
   strong result is a 2008-start effect; the dot-com grind + calm 2010s offset
   the crash wins.
3. **No timing signal beats always-on** risk-adjusted — reproduces "you can't
   time tail events; hold the cheap hedge." (Includes a documented +12pp false
   discovery caught by decomposition — see `findings/SIGNAL_EXPERIMENTS.md`.)
4. **Monetization matters** — un-monetized ITM LEAPs ride their gains back to
   zero; flat profit-taking, conversely, sells the crash too early.
