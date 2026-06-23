# imports
import pandas as pd


def calc_sma(candle: pd.DataFrame, window: int) -> float:
    return candle["close"].tail(window).mean()


def passes_trend_filters(
    current_price: float,
    sma20: float,
    sma50: float,
    sma200: float,
) -> bool:
    return current_price > sma20 > sma50 > sma200