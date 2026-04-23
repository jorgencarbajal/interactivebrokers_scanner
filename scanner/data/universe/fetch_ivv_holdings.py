from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import io
from pathlib import Path
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

# set up the default webaddress, this can change
IVV_HOLDINGS_URL: Final[str] = (
    "https://www.ishares.com/us/products/239726/"
    "ishares-core-sp-500-etf/1467271812596.ajax"
    "?fileType=csv&fileName=IVV_holdings&dataType=fund"
)
# set up the default folder output
DEFAULT_OUTPUT_DIR: Final[Path] = Path(__file__).resolve().parent
# setting up and output name, ensuring the collected data falls into a range we expect, and ensure we have the most necessary columns
DEFAULT_CLEAN_FILENAME: Final[str] = "sp500_current.csv"
EXPECTED_MIN_SYMBOLS: Final[int] = 450
EXPECTED_MAX_SYMBOLS: Final[int] = 550
REQUIRED_HEADER_COLUMNS: Final[set[str]] = {
    "Ticker",
    "Name",
    "Sector",
    "Asset Class",
}


# goes to the ishares website and downloads the ivv holdings
def fetch_csv_bytes(url: str = IVV_HOLDINGS_URL, timeout_seconds: int = 30) -> bytes:
    # package up the webrequest
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/csv,*/*;q=0.9",
        },
    )

    try:
        # attempt to make the request
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(
            f"iShares returned HTTP {exc.code} while fetching IVV holdings."
        # exception chaining: remember both the original low-level problems with the new higher-level problem (RuntimeError)
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            "Unable to reach iShares for the IVV holdings CSV. "
            "If you already downloaded the file, rerun with --input <path>."
        ) from exc


# this function loops through the entire list of list to look for the row that contains the headers
def find_header_row(rows: list[list[str]]) -> int:
    for row_index, row in enumerate(rows):
        # convert the row to a set and compare if it matches what is intended
        normalized_cells = {cell.strip() for cell in row if cell.strip()}
        if REQUIRED_HEADER_COLUMNS.issubset(normalized_cells):
            return row_index
    # if we make it through the entire function without finding a matching row
    raise ValueError("Could not locate the holdings table header in the IVV CSV.")


# pull the holdings "as of" date out of the CSV preamble if it exists
def extract_holdings_as_of(rows: list[list[str]], header_row: int) -> date | None:
    # loop throught the rows that come before the header row
    for row in rows[:header_row]:
        for column_index, cell in enumerate(row):
            # skip over crap
            if cell.strip() != "Fund Holdings as of":
                continue

            # if we have reached the end of the row
            if column_index + 1 >= len(row):
                continue

            # take the cell next to the "Fund Hold..." cell
            raw_value = row[column_index + 1].strip()
            # incase that is empty
            if not raw_value:
                continue

            # convert to pandas datetime object
            parsed = pd.to_datetime(raw_value, errors="coerce")
            # if the conversion failed continue looking throught the data
            if pd.isna(parsed):
                continue
            return parsed.date()

    return None


# here we take those raw downloaded bytes and convert it into a nice df
def parse_holdings_csv(raw_csv: bytes) -> tuple[pd.DataFrame, date | None]:
    # decode the bytes into one full string
    text = raw_csv.decode("utf-8-sig")
    # wrap the string so python can read the file as if it were in memory. in the end rows is a nested list of all the tickers
    rows = list(csv.reader(io.StringIO(text)))
    # from that list of list, look for the headers
    header_row = find_header_row(rows)

    # get the date for when this csv was last updated
    holdings_as_of = extract_holdings_as_of(rows, header_row)

    # convert the text to file, parse it into rows and columns
    holdings = pd.read_csv(io.StringIO(text), skiprows=header_row, dtype="string")
    # clean up the column names
    holdings.columns = [str(column).strip() for column in holdings.columns]
    # clean up the df; (drop rows where all values empty and reset indexing)
    holdings = holdings.dropna(how="all").reset_index(drop=True)
    # return the clean df and the date this was last updated
    return holdings, holdings_as_of


# clean up symbols, (BRK.B -> BRK-B)
def normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper()
    return cleaned.replace(".", "-")


# we take the data from and look for a particular column, if not return a Series of the same length as the rows in the data set
def optional_column(frame: pd.DataFrame, column_name: str) -> pd.Series:
    if column_name in frame.columns:
        return frame[column_name]
    return pd.Series([pd.NA] * len(frame), index=frame.index)


# build the data frame
def build_clean_universe(
        holdings: pd.DataFrame,
        *,
        holdings_as_of: date | None,
        downloaded_at_utc: str,
        min_symbols: int = EXPECTED_MIN_SYMBOLS,
        max_symbols: int = EXPECTED_MAX_SYMBOLS,
    ) -> pd.DataFrame:
    # check to see if you are missing any required columns
    missing_columns = REQUIRED_HEADER_COLUMNS.difference(holdings.columns)
    if missing_columns:
        # set of missing value to string
        missing_list = ", ".join(sorted(missing_columns))
        raise ValueError(f"IVV holdings CSV is missing required columns: {missing_list}")

    # create the clean copy
    cleaned = holdings.copy()
    # column wise operation to clean all the rows of a column
    cleaned["Ticker"] = cleaned["Ticker"].astype("string").str.strip()
    cleaned["Asset Class"] = cleaned["Asset Class"].astype("string").str.strip()
    cleaned["Name"] = cleaned["Name"].astype("string").str.strip()
    cleaned["Sector"] = cleaned["Sector"].astype("string").str.strip()
    # keep only rows where ticker column isnt empty
    cleaned = cleaned[cleaned["Ticker"].notna() & (cleaned["Ticker"] != "")]
    # keep only equities
    cleaned = cleaned[
        cleaned["Asset Class"].str.casefold() == "equity"
    ].reset_index(drop=True)

    # take evey value in the ticker column and run this function
    cleaned["symbol"] = cleaned["Ticker"].map(normalize_symbol)
    # drop duplicates and sort
    cleaned = cleaned.drop_duplicates(subset="symbol", keep="first")
    cleaned = cleaned.sort_values("symbol").reset_index(drop=True)

    # build the data frame
    output = pd.DataFrame(
        {
            "holdings_as_of": holdings_as_of.isoformat() if holdings_as_of else pd.NA,
            "downloaded_at_utc": downloaded_at_utc,
            "source": "ishares_ivv",
            "source_ticker": cleaned["Ticker"],
            "symbol": cleaned["symbol"],
            "name": cleaned["Name"],
            "sector": cleaned["Sector"],
            "asset_class": cleaned["Asset Class"],
            "weight_pct": pd.to_numeric(
                optional_column(cleaned, "Weight (%)"), errors="coerce"
            ),
            "market_value": pd.to_numeric(
                optional_column(cleaned, "Market Value"), errors="coerce"
            ),
            "quantity": pd.to_numeric(optional_column(cleaned, "Quantity"), errors="coerce"),
            "price": pd.to_numeric(optional_column(cleaned, "Price"), errors="coerce"),
            "location": optional_column(cleaned, "Location"),
            "exchange": optional_column(cleaned, "Exchange"),
            "currency": optional_column(cleaned, "Currency"),
        }
    )

    # final check to ensure we didnt collect more or less than what was intended
    symbol_count = len(output)
    if symbol_count < min_symbols or symbol_count > max_symbols:
        raise RuntimeError(
            "Unexpected IVV universe size after normalization: "
            f"{symbol_count} symbols. Expected between {min_symbols} and {max_symbols}."
        )

    return output


# create both paths and write to them. return the paths
def write_outputs(
    *,
    raw_csv: bytes,
    clean_universe: pd.DataFrame,
    output_dir: Path,
    holdings_as_of: date | None,
) -> tuple[Path, Path]:
    # create the directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # date label for the raw file name
    snapshot_date = holdings_as_of.isoformat() if holdings_as_of else date.today().isoformat()
    # create the paths for each file
    raw_path = output_dir / f"ivv_holdings_{snapshot_date}.csv"
    clean_path = output_dir / DEFAULT_CLEAN_FILENAME

    # create the files
    raw_path.write_bytes(raw_csv)
    clean_universe.to_csv(clean_path, index=False)

    return raw_path, clean_path


# this function is for setting up how the script can accept inputs from the command line
def build_argument_parser() -> argparse.ArgumentParser:
    # run the script with the help flag will output this message
    parser = argparse.ArgumentParser(
        description=(
            "Download the official iShares IVV holdings CSV and build a "
            "clean current S&P 500 universe file."
        )
    )
    # adding parameters for arguments when running from the command line
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional local IVV holdings CSV to parse instead of downloading.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for the raw snapshot and cleaned universe file. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--url",
        default=IVV_HOLDINGS_URL,
        help="Override the IVV holdings CSV URL.",
    )
    return parser


def main() -> int:
    # define the possible command line arguments
    parser = build_argument_parser()
    # store the arguments
    args = parser.parse_args()

    # if there is input, read it, if not default path
    if args.input:
        raw_csv = args.input.read_bytes()
    else:
        # get the raw bytes from website
        raw_csv = fetch_csv_bytes(args.url)

    # a time stamp for when it was downloaded
    downloaded_at_utc = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )

    # clean up the raw_csv into a nice df and extract the date when it was last uploaded
    holdings, holdings_as_of = parse_holdings_csv(raw_csv)

    clean_universe = build_clean_universe(
        holdings,
        holdings_as_of=holdings_as_of,
        downloaded_at_utc=downloaded_at_utc,
    )
    raw_path, clean_path = write_outputs(
        raw_csv=raw_csv,
        clean_universe=clean_universe,
        output_dir=args.output_dir,
        holdings_as_of=holdings_as_of,
    )

    # date/date-time object to string
    holdings_date_label = holdings_as_of.isoformat() if holdings_as_of else "unknown"
    
    print(f"IVV holdings as of: {holdings_date_label}")
    print(f"Clean equity universe size: {len(clean_universe)} symbols")
    print(f"Raw snapshot written to: {raw_path}")
    print(f"Cleaned universe written to: {clean_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())