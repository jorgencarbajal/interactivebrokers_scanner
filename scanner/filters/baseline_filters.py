# imports
import pandas as pd
from typing import Final
from pathlib import Path

# global variable
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
OHLCV_PATH : Final[Path] = (
    PROJECT_ROOT / "scanner" / "data" / "prices" / "raw"
)

def calc_average_volume(candles: pd.DataFrame) -> float:
    # select everything except the last row
    return candles["volume"].iloc[:-1].tail(20).mean()


def calc_relative_volume(candles: pd.DataFrame, average_volume: float) -> float:
    # todays volume candle
    current_volume = candles["volume"].iloc[-1]
    return current_volume/average_volume


def calc_average_true_range(candles: pd.DataFrame) -> float:
    high_low = candles["high"] - candles["low"]
    high_prev_close = (candles["high"] - candles["close"].shift(1)).abs()
    low_prev_close = (candles["low"] - candles["close"].shift(1)).abs()

    true_range = pd.concat(
        [high_low, high_prev_close, low_prev_close],
        axis=1,
    ).max(axis=1)

    return true_range.tail(14).mean()


def get_historical_daily_candles(symbol: str) -> pd.DataFrame:
    path = OHLCV_PATH / f"{symbol}.csv"
    df = pd.read_csv(path)

    return df


def passes_baseline_filters(
    average_volume: float,
    relative_volume: float,
    average_true_range: float,
) -> bool:
    if (
        average_volume > 2000000
        and relative_volume > 1
        and average_true_range > 1
    ):
        return True
    
    else:
        return False