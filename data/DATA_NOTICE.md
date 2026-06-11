# Data notice: provenance, redistribution posture, and mirrors

## What the dataset is

`data-v1` is six parquet files of **historical end-of-day US options chains
and underlying prices** (SPY 2008–2025; QQQ 2011–2025; IWM 2008–2025),
redistributed solely to make the published research reproductions in this
repository verifiable bit-for-bit. SPY is the primary asset — it is the
dataset every published article table pins.

Canonical SHA-256 hashes for all six files live in
[`scripts/fetch_data.py`](../scripts/fetch_data.py) (`CANONICAL_HASHES`).
Run `python scripts/fetch_data.py verify` against any copy to prove it is
byte-identical to the canonical dataset.

## Provenance

The files were originally mirrored from a publicly distributed dataset
(philippdubach/options-data, "Historical Options Chain Data for 100+ US
Equities, 2008–2025"). That upstream — both its CDN and its GitHub
repository — disappeared in 2026; these copies are therefore now a primary
source rather than a cache. The upstream's own sourcing was not documented.

## Redistribution posture

- This data is redistributed **for research and educational reproducibility
  only** — it backs published article reproductions whose correctness this
  repository exists to verify. It is **not** sold, not offered for
  commercial redistribution, and not real-time (the youngest quote is over a
  year old).
- Historical price quotations are factual market data. We make no claim of
  ownership over the underlying facts and assert no license over them.
- Provided **as-is, with no warranty** of accuracy, completeness, or fitness
  for any purpose. Known gaps are documented (e.g. IWM `underlying.parquet`
  ships `adjClose` as all-NaN; QQQ's chain begins 2011-03-23).
- **If you hold rights in this data and want it removed, open an issue or
  contact the repository owner — it will be taken down promptly.**

## Build it yourself instead (cleanest legal posture)

If you prefer not to rely on redistributed data, you can assemble an
equivalent dataset under your own account/terms:

1. Register (free) at [optionsdx.com](https://www.optionsdx.com/) and
   download EOD option chains (2010+ for major ETFs/indices).
2. Convert with [`scripts/convert_optionsdx.py`](../scripts/convert_optionsdx.py).
3. Underlying prices: `scripts/fetch_data.py` falls back to yfinance for
   stocks.

Note that OptionsDX coverage starts in 2010, so 2008–2009 (the GFC — the
window that drives the published results) is not reproducible from that
source; see `research/spitznagel_spy/CROSS_UNDERLYING.md` for why the window
matters.

## Mirrors

Downloads try each entry of `CANONICAL_MIRRORS` in `scripts/fetch_data.py`
in order, and every file is verified against the pinned hashes — a mirror
cannot silently serve different bytes.

| Mirror | Status |
|---|---|
| GitHub Release [`data-v1`](https://github.com/lambdaclass/options_portfolio_backtester/releases/tag/data-v1) | live (primary) |
| Zenodo (DOI-pinned archival) | **pending — see below** |
| Hugging Face dataset | optional |

### Setting up the Zenodo mirror (maintainer steps, ~20 min)

1. Log in at [zenodo.org](https://zenodo.org) (GitHub login works).
2. New upload → add the six files from `data/raw/release/` (SPY first).
3. Metadata — suggested values:
   - **Title:** "Historical EOD US options chains and underlying prices
     (SPY 2008–2025, QQQ 2011–2025, IWM 2008–2025) — options_portfolio_backtester data-v1"
   - **Description:** paste the *What the dataset is*, *Provenance*, and
     *Redistribution posture* sections above, plus the six SHA-256 hashes.
   - **License:** "Other (Open)" with a note: factual market data
     redistributed for research reproducibility; no ownership claimed.
   - **Related identifiers:** this repository URL; the article URL.
4. Publish → note the record id (the number in `zenodo.org/records/<id>`).
5. Uncomment the Zenodo line in `CANONICAL_MIRRORS` and substitute the id.
6. `python scripts/fetch_data.py verify` after a test download.

Zenodo records are immutable and DOI-citable — cite the DOI in the article
to make the data reference permanent.

## Alternative free sources evaluated (2026-06-11)

So they are not re-investigated from scratch:

- **Upstream (philippdubach options-data, 104 symbols 2008+):** permanently
  gone — CDN 404s for every symbol, GitHub repo deleted, no relocation
  notice on the author's site, nothing usable in the Wayback Machine. The
  data-v1 mirror here is the surviving copy.
- **DoltHub `post-no-preference/options`** (free, ~2,100 symbols): chains
  start ~2019/2020 and carry only ~3 near-dated expirations (DTE ≤ ~60)
  with strikes within ±20% of spot — no DTE 90-180, no 40-45% OTM strikes,
  and no GLD/TLT/EEM coverage. Unusable for the tail-hedge configuration;
  possibly useful for short-dated research.
- **OptionsDX** (free with registration): full chains incl. long-dated,
  2010+ (no GFC), for major indices/ETFs. The only viable free expansion
  path; requires a per-user account, so it cannot be fetched headlessly —
  see the build-it-yourself section above.
- **Kaggle:** SPY-only 2010+ snapshots, no breadth.

## Private backups

The raw assets live in `data/raw/release/` after any fetch. Copy that
directory to offline storage and run
`python scripts/fetch_data.py verify` on the copy (with the repo checked
out) to confirm integrity. Because the hashes are pinned in-code, any
verified copy — yours or anyone's — is as canonical as the original.
