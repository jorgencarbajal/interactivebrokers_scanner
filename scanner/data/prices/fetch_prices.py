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
    
    # calculate date range
    end_date = date.today()
    start_date = end_date - timedelta(days=500)

    # call client.list_aggs(...)
    bars = client.list_aggs(
        ticker=to_massive_ticker(symbol),
        multiplier=1,
        timespan="day",
        from_=start_date,
        to=end_date,
        adjusted=True,
        sort="asc",
        limit=50000,
    )

    # convert each returned bar into a dict
    # return rows
    pass


# funciton that writes the above information into a csv at output


# Main() implement all the above
def main():
    api_key = load_api_key()

    print("API key found")

    ticker_list = load_tickers()
    print(ticker_list[:10])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())