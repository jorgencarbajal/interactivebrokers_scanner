# SP500 UPTREND SCANNER

The repo takes the universe of sp500 stock and applies basic filters that meet
"uptrend" criteria. The goal is to extend and modify to meet specific criteria
that a user finds reasonable. Those types of specific changes can be done in the
`scanner/filters` folder. Any changes would then need to be made in the
`scanner/scan.py` file.

The whole pipeline runs unattended on GitHub Actions and commits its results
back to this repository.

## How it works

The project runs in three stages, each of which can run on its own or as part of
the scheduled pipeline:

1. **Build the universe** — `scanner/data/universe/holdings.py`
   Downloads the official SPY ETF holdings file (State Street / SSGA), cleans and
   normalizes the tickers (e.g. `BRK.B` → `BRK-B`), and writes the current
   membership to `scanner/data/universe/sp500_current.csv`. A dated raw snapshot
   (`holdings_YYYY-MM-DD.xlsx`) is saved alongside it.

2. **Fetch prices** — `scanner/data/prices/fetch_prices.py`
   Reads the universe file and pulls ~300 daily bars per ticker (enough history
   for a 200-day SMA) from the Massive market-data API. Each ticker is written to
   its own file at `scanner/data/prices/raw/{TICKER}.csv` with
   `date, open, high, low, close, volume` columns. Calls are rate-limited, so a
   full run over ~500 tickers takes roughly 100 minutes.

3. **Scan** — `scanner/scan.py`
   Loads the raw price files, computes the indicators below, applies the filters,
   and writes the survivors to `scanner/uptrend.csv`. A ticker whose price file is
   missing or unreadable is skipped and logged rather than failing the whole run.

## What counts as an "uptrend"

A ticker is kept only if it passes **both** filter groups.

**Baseline filters** (`scanner/filters/baseline_filters.py`):

| Filter             | Condition   | Definition                           |
| ------------------ | ----------- | ------------------------------------ |
| Average volume     | > 2,000,000 | Mean volume of the prior 20 days     |
| Relative volume    | > 1         | Latest day's volume ÷ average volume |
| Average true range | > 1         | 14-day ATR                           |

**Trend filters** (`scanner/filters/trend_filters.py`):

- `price > SMA(20) > SMA(50) > SMA(200)` — price and the moving averages stacked
  in bullish order.

To adjust what "uptrend" means, edit the thresholds and indicator functions in
`scanner/filters/`, then wire any new values into the loop in `scanner/scan.py`.

## Output

`scanner/uptrend.csv`, one row per qualifying ticker:

`symbol, last_price, average_volume, relative_volume, average_true_range, sma_20, sma_50, sma_200`

## Project structure

```
scanner/
├── scan.py                       # Stage 3: run the filters, write uptrend.csv
├── uptrend.csv                   # Scan output
├── data/
│   ├── universe/
│   │   ├── holdings.py           # Stage 1: build sp500_current.csv
│   │   └── sp500_current.csv     # Current S&P 500 membership
│   └── prices/
│       ├── fetch_prices.py       # Stage 2: download daily bars
│       └── raw/                  # One CSV of daily bars per ticker
└── filters/
    ├── baseline_filters.py       # Volume / relative-volume / ATR filters
    └── trend_filters.py          # SMA stacking filter
```

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

The price fetcher needs a Massive API key. For local runs, create a `.env` file
in the project root:

```
MASSIVE_API_KEY=your_key_here
```

(`.env` is gitignored. In CI the key is provided by the `MASSIVE_API_KEY`
GitHub Actions secret instead.)

## Running manually

Each stage is a runnable module:

```bash
# Stage 1 — refresh the universe
uv run python -m scanner.data.universe.holdings

# Stage 2 — fetch daily bars (--force re-fetches even if a file already exists)
uv run python -m scanner.data.prices.fetch_prices --force

# Stage 3 — run the scan
uv run python -m scanner.scan
```

Useful flags for `fetch_prices.py`: `--bars` (bars to keep per ticker, default
300), `--calls-per-minute` (rate limit, default 5), and `--force` (re-fetch
tickers that already have a file).

## Automation

Three GitHub Actions workflows in `.github/workflows/` run the pipeline on a
schedule and commit the refreshed data back to the repo. Cron times are UTC and
do **not** shift for daylight saving.

| Workflow                | File               | Schedule (UTC) | What it does                      |
| ----------------------- | ------------------ | -------------- | --------------------------------- |
| Update S&P 500 Universe | `holdings.yml`     | Sundays 12:00  | Refresh `sp500_current.csv`       |
| Fetch Daily Prices      | `fetch-prices.yml` | Weekdays 09:00 | Download daily bars into `raw/`   |
| Run Scanner             | `scan.yml`         | Weekdays 13:00 | Run the scan, write `uptrend.csv` |

The weekly universe refresh feeds the daily price fetch, which in turn feeds the
daily scan. All three can also be triggered manually from the **Actions** tab
via **Run workflow**.

For the automation to work, the repository needs:

- A `MASSIVE_API_KEY` secret (Settings → Secrets and variables → Actions).
- Read and write workflow permissions (Settings → Actions → General → Workflow
  permissions), so each run can commit its results back.
