# Data coverage: deep-OTM puts are not listed in the early-2000s SPX chain

The article's headline configuration buys **40–45% OTM** puts at **90–180 DTE**.
On the purchased DeltaNeutral ALLSPX data that depth is **not reliably listed
before ~2003**, so any dot-com (2000–2002) result *at that depth* is largely a
no-hedge artifact, not a hedged outcome. This was found by the engine's hedge
fill-rate diagnostic (`engine.option_fill_rate`; `HedgeFillWarning`).

## Fill rate by OTM band, 2000–2003 (24 bi-monthly rebalances, DTE 90–180)

| OTM band | fills/24 | tradeable (bid>0) |
|---|---|---|
| 10–15% | 24 | 24 |
| 15–20% | 24 | 24 |
| 20–25% | 23 | 23 |
| **25–30%** | **24** | **24** ✅ |
| 30–35% | 19 | 18 |
| 35–40% | 16 | 16 |
| **40–45%** | **13** | **11** ❌ |

At 40–45% the engine attempts 24 entries and **13 go unfilled (46% fill rate)**,
including a contiguous **20-month gap (2001-01 → 2002-09)** that straddles the
core −38% leg of the decline. On several rebalances the chain's deepest listed
90–180-DTE put is only ~38–40% OTM, so a 40–45% strike simply does not exist.

## Consequence for the findings

- **The "dot-com slow grind loses (−1.7pp)" claim is only trustworthy at
  ≤ 25–30% OTM**, where the chain fills every rebalance with sane prices. The
  signal battery (`SIGNAL_EXPERIMENTS.md`) already uses 25–30%, so those
  conclusions stand. The crash-*shape* thesis survives qualitatively, but the
  specific 40–45% dot-com number should be treated as **data-limited**, not a
  clean hedged-vs-unhedged comparison.
- **The GFC and COVID windows are unaffected** — by 2008+ the chain lists the
  full deep-OTM ladder, and those runs fill ≥ 95%.

## How to detect this yourself

```python
eng.run(...)
print(eng.option_fill_rate, eng.option_entry_unfilled, "/", eng.option_entry_attempts)
```

A `HedgeFillWarning` fires automatically when > 10% of entry attempts match no
contract. Treat a low fill rate as "the data can't express this strategy in
this window" — widen the band, shorten the DTE, or restrict the window.
