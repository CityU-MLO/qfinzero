import os

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
OPTIONS_H5_PATH = os.getenv(
    "OPTIONS_H5_PATH",
    "/home/hluo/OptionBench/data/assets/options_structured.h5",
)
PRICES_H5_PATH = os.getenv(
    "PRICES_H5_PATH",
    "/home/hluo/OptionBench/data/assets/prices_2025.h5",
)
RATES_CSV_PATH = os.getenv(
    "RATES_CSV_PATH",
    "/home/hluo/OptionBench/data/assets/treasury_yields.csv",
)

DATE_FMT = "%Y-%m-%d"
