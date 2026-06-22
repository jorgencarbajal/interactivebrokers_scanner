# IMPORTS
from massive import RESTClient
from pathlib import Path
from typing import Final
from datetime import date, datetime, timedelta, timezone
from dotenv import load_dotenv

import argparse, csv, os, time
import pandas as pd
import numpy as np

# GLOBAL DEFINITIONS
PROJECT_ROOT : Final[Path] = Path(__file__).resolve().parents[3]

DEFAULT_UNIVERSE_CSV : Final[Path] = (
    PROJECT_ROOT / "scanner" / "data" / "universe" / "sp500_current.csv"
)
DEFAULT_OUTPUT_DIR : Final[Path] = (
    PROJECT_ROOT / "scanner" / "data" / "prices" / "raw"
)
DEFAULT_BAR_COUNT : Final[int] = 300
DEFAULT_CALLS_PER_MINUTE : Final[int] = 5
DEFAULT_RETRIES : Final[int] = 3
API_KEY_ENV_VAR : Final[str] = "MASSIVE_API_KEY"


def load_api_key(env_file: Path = PROJECT_ROOT / ".env") -> str:
    if env_file.exists():
        load_dotenv(env_file)
    
    api_key = os.getenv(API_KEY_ENV_VAR)

    if not api_key:
        raise RuntimeError(
            f"Missing {API_KEY_ENV_VAR}. Add it to {env_file} "
            "or set it as an environment variable."
        )

    return api_key


def load_tickers(universe_csv: Path = DEFAULT_UNIVERSE_CSV) -> list[str]:
    if not universe_csv.exists():
        raise RuntimeError(f"Path not found: {universe_csv}")
    
    universe = pd.read_csv(universe_csv)

    if "source_ticker" not in universe.columns:
        raise RuntimeError(f"Missing source column.")

    tickers = (
        universe["source_ticker"]
        .dropna()
        .astype(str)
        .str.strip()
    )

    return [ticker for ticker in tickers if ticker]


def to_massive_ticker(symbol: str) -> str:
    cleaned = symbol.strip().upper()

    return cleaned.replace("-", ".")


def fetch_daily_bars(
    client: RESTClient,
    symbol: str,
    bar_count: int = DEFAULT_BAR_COUNT,
) -> list[dict[str, object]]:
    # convert symbol to Massive ticker
    massive_ticker = to_massive_ticker(symbol)
    
    # calculate date range
    end_date = date.today()
    start_date = end_date - timedelta(days=500)

    # call client.list_aggs(...)
    bars = client.list_aggs(
        ticker=massive_ticker,
        multiplier=1,
        timespan="day",
        from_=start_date,
        to=end_date,
        adjusted=True,
        sort="asc",
        limit=50000,
    )

    rows = []

    # convert each returned bar into a dict
    for bar in bars:
        if bar.timestamp is None:
            continue

        bar_date = datetime.fromtimestamp(
            bar.timestamp / 1000,
            tz=timezone.utc,
        ).date()

        rows.append(
            {
                "date": bar_date.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
        )

    # return rows
    return rows[-bar_count:]


def fetch_daily_bars_with_retries(
    client: RESTClient,
    symbol: str,
    bar_count: int = DEFAULT_BAR_COUNT,
    max_attempts: int = DEFAULT_RETRIES,
    retry_delay_seconds: float = 12,
) -> list[dict[str, object]]:
    for attempt in range(1, max_attempts + 1):
        try:
            return fetch_daily_bars(
                client=client,
                symbol=symbol,
                bar_count=bar_count,
            )

        except Exception as exc:
            if attempt == max_attempts:
                raise

            print(
                f"{symbol} attempt {attempt}/{max_attempts} failed: {exc}. "
                f"Retrying in {retry_delay_seconds:.0f} seconds..."
            )

            time.sleep(retry_delay_seconds)

    return []


def write_price_csv(
    symbol: str,
    rows: list[dict[str, object]],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    # create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # create path like output_dir / f"{symbol}.csv"
    output_path = output_dir / f"{symbol}.csv"

    # create df and write headers
    columns = ["date", "open", "high", "low", "close", "volume"]
    prices = pd.DataFrame(rows, columns=columns)
    
    prices.to_csv(output_path, index=False)

    return output_path


def seconds_between_calls(calls_per_minute: int = DEFAULT_CALLS_PER_MINUTE) -> float:
    return 60/calls_per_minute


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch daily price bars for the current S&P 500 universe."
    )

    parser.add_argument(
        "--universe-csv",
        type=Path,
        default=DEFAULT_UNIVERSE_CSV,
        help="Path to sp500_current.csv.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where raw ticker CSV files will be written.",
    )

    parser.add_argument(
        "--bars",
        type=int,
        default=DEFAULT_BAR_COUNT,
        help="Number of daily bars to keep per ticker.",
    )

    parser.add_argument(
        "--calls-per-minute",
        type=int,
        default=DEFAULT_CALLS_PER_MINUTE,
        help="Maximum API calls per minute.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Refetch tickers even when their output CSV already exists.",
    )

    return parser


def main() -> int:
    # build the argument parser
    parser = build_argument_parser()

    # parse command line arguments
    args = parser.parse_args()

    # load the Massive API key
    api_key = load_api_key()

    # load tickers from the universe CSV
    tickers = load_tickers(args.universe_csv)

    # create the Massive REST client
    client = RESTClient(api_key=api_key)

    # calculate delay between API calls
    delay_seconds = seconds_between_calls(args.calls_per_minute)

    # create counters:
    fetched = 0
    skipped = 0
    failed = 0
    no_data = 0

    total = len(tickers)

    # loop through each ticker with its position number
    for index, symbol in enumerate(tickers, start=1):
        # build the expected output path for this ticker
        output_path = args.output_dir / f"{symbol}.csv"

        # if output file exists and force is not enabled:
        if output_path.exists() and not args.force:
            # print skipped progress message
            print(f"[{index}/{total}] {symbol} skipped, file already exists.")

            # increment skipped counter
            skipped += 1

            # continue to next ticker
            continue

        # print fetching progress message
        print(f"[{index}/{total}] {symbol} fetching...")

        # try to fetch daily bars
        try:
            # if no rows came back:
            rows = fetch_daily_bars_with_retries(
                client=client,
                symbol=symbol,
                bar_count=args.bars,
                max_attempts=DEFAULT_RETRIES,
                retry_delay_seconds=delay_seconds,
            )

            # print no-data message
            if not rows:
                print(f"[{index}/{total}] {symbol} no data returned.")
                # increment no_data counter
                no_data += 1

                if index < total:
                    time.sleep(delay_seconds)

                continue

            saved_path = write_price_csv(
                symbol=symbol,
                rows=rows,
                output_dir=args.output_dir,
            )

            print(f"[{index}/{total}] {symbol} saved {len(rows)} rows to {saved_path}")
            fetched += 1

        except Exception as exc:
            print(f"[{index}/{total}] {symbol} failed: {exc}")
            failed += 1

        if index < total:
            time.sleep(delay_seconds)

    print("Price fetch complete.")
    print(f"Fetched: {fetched}")
    print(f"Skipped: {skipped}")
    print(f"No data: {no_data}")
    print(f"Failed: {failed}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())