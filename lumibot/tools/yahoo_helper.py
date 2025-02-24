import logging
import os
import pickle

import yfinance as yf
from lumibot import LUMIBOT_CACHE_FOLDER, LUMIBOT_DEFAULT_PYTZ

from .helpers import get_lumibot_datetime

DAY_DATA = "day_data"
INFO_DATA = "info"


class _YahooData:
    def __init__(self, symbol, type, data):
        self.symbol = symbol
        self.type = type.lower()
        self.data = data
        self.file_name = "%s_%s.pickle" % (symbol, type)

    def is_up_to_date(self, last_needed_datetime=None):
        if last_needed_datetime is None:
            last_needed_datetime = get_lumibot_datetime()

        if self.type == DAY_DATA:
            last_needed_date = last_needed_datetime.date()
            last_day = self.data.index[-1].to_pydatetime().date()

            # ip_up_to_date will always return False on holidays even though
            # the data is up to date because the market is still closed
            return last_day >= last_needed_date

        if self.type == INFO_DATA:
            if self.data.get("error"):
                return False

            last_needed_date = last_needed_datetime.date()
            last_day = self.data.get("last_update").date()

            return last_day >= last_needed_date

        return False


class YahooHelper:

    # =========Internal initialization parameters and methods============

    CACHING_ENABLED = False
    LUMIBOT_YAHOO_CACHE_FOLDER = os.path.join(LUMIBOT_CACHE_FOLDER, "yahoo")

    if not os.path.exists(LUMIBOT_YAHOO_CACHE_FOLDER):
        try:
            os.makedirs(LUMIBOT_YAHOO_CACHE_FOLDER)
            CACHING_ENABLED = True
        except Exception as e:
            pass
    else:
        CACHING_ENABLED = True

    # ====================Caching methods=================================

    @staticmethod
    def check_pickle_file(symbol, type):
        if YahooHelper.CACHING_ENABLED:
            file_name = "%s_%s.pickle" % (symbol, type.lower())
            pickle_file_path = os.path.join(
                YahooHelper.LUMIBOT_YAHOO_CACHE_FOLDER, file_name
            )
            if os.path.exists(pickle_file_path):
                try:
                    with open(pickle_file_path, "rb") as f:
                        return pickle.load(f)
                except Exception as e:
                    logging.error(
                        "Error while loading pickle file %s: %s" % (pickle_file_path, e)
                    )
                    return None

        return None

    @staticmethod
    def dump_pickle_file(symbol, type, data):
        if YahooHelper.CACHING_ENABLED:
            yahoo_data = _YahooData(symbol, type, data)
            file_name = "%s_%s.pickle" % (symbol, type.lower())
            pickle_file_path = os.path.join(
                YahooHelper.LUMIBOT_YAHOO_CACHE_FOLDER, file_name
            )
            with open(pickle_file_path, "wb") as f:
                pickle.dump(yahoo_data, f)

    # ====================Formatters methods===============================

    @staticmethod
    def format_df(df, auto_adjust):
        if auto_adjust:
            del df["Adj Ratio"]
            del df["Close"]
            del df["Open"]
            del df["High"]
            del df["Low"]
            df.rename(
                columns={
                    "Adj Close": "Close",
                    "Adj Open": "Open",
                    "Adj High": "High",
                    "Adj Low": "Low",
                },
                inplace=True,
            )
        else:
            del df["Adj Ratio"]
            del df["Adj Open"]
            del df["Adj High"]
            del df["Adj Low"]

        return df

    @staticmethod
    def process_df(df, asset_info=None):
        df = df.dropna().copy()

        if df.index.tzinfo is None:
            df.index = df.index.tz_localize(LUMIBOT_DEFAULT_PYTZ)
        else:
            df.index = df.index.tz_convert(LUMIBOT_DEFAULT_PYTZ)

        return df

    # ===================Data download method=============================

    @staticmethod
    def download_symbol_info(symbol):
        ticker = yf.Ticker(symbol)

        try:
            info = ticker.info
        except Exception as e:
            logging.error(
                f"Error while downloading symbol info for {symbol}, setting info to None for now."
            )
            logging.error(e)
            return {
                "ticker": symbol,
                "last_update": get_lumibot_datetime(),
                "error": True,
                "info": None,
            }

        return {
            "ticker": ticker.ticker,
            "last_update": get_lumibot_datetime(),
            "error": False,
            "info": info,
        }

    @staticmethod
    def get_symbol_info(symbol):
        ticker = yf.Ticker(symbol)
        return ticker.info

    @staticmethod
    def get_symbol_last_price(symbol):
        ticker = yf.Ticker(symbol)
        info = ticker.info
        return info["last_price"]

    @staticmethod
    def download_symbol_day_data(symbol):
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="max", auto_adjust=False)

        # Adjust the time when we are getting daily stock data to the beginning of the day
        # This way the times line up when backtesting daily data
        info = YahooHelper.get_symbol_info(symbol)
        if info.get("info") and info.get("info").get("market") == "us_market":
            # Check if the timezone is already set, if not set it to the default timezone
            if df.index.tzinfo is None:
                df.index = df.index.tz_localize(
                    info.get("info").get("exchangeTimezoneName")
                )
            else:
                df.index = df.index.tz_convert(
                    info.get("info").get("exchangeTimezoneName")
                )
            df.index = df.index.map(lambda t: t.replace(hour=16, minute=0))
        elif info.get("info") and info.get("info").get("market") == "ccc_market":
            # Check if the timezone is already set, if not set it to the default timezone
            if df.index.tzinfo is None:
                df.index = df.index.tz_localize(
                    info.get("info").get("exchangeTimezoneName")
                )
            else:
                df.index = df.index.tz_convert(
                    info.get("info").get("exchangeTimezoneName")
                )
            df.index = df.index.map(lambda t: t.replace(hour=23, minute=59))

        df = YahooHelper.process_df(df, asset_info=info)
        return df

    @staticmethod
    def download_symbols_day_data(symbols):
        if len(symbols) == 1:
            item = YahooHelper.download_symbol_day_data(symbols[0])
            return {symbols[0]: item}

        result = {}
        tickers = yf.Tickers(" ".join(symbols))
        df_yf = tickers.history(
            period="max",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
        )

        for i in df_yf.columns.levels[0]:
            result[i] = YahooHelper.process_df(df_yf[i])

        return result

    # ===================Cache retrieval and dumping=====================

    @staticmethod
    def fetch_symbol_info(symbol, caching=True, last_needed_datetime=None):
        if caching:
            cached_data = YahooHelper.check_pickle_file(symbol, INFO_DATA)
            if cached_data:
                if cached_data.is_up_to_date(last_needed_datetime=last_needed_datetime):
                    return cached_data.data

        # Caching is disabled or no previous data found
        # or data found not up to date
        data = YahooHelper.download_symbol_info(symbol)
        YahooHelper.dump_pickle_file(symbol, INFO_DATA, data)
        return data

    @staticmethod
    def fetch_symbol_day_data(symbol, caching=True, last_needed_datetime=None):
        if caching:
            cached_data = YahooHelper.check_pickle_file(symbol, DAY_DATA)
            if cached_data:
                if cached_data.is_up_to_date(last_needed_datetime=last_needed_datetime):
                    return cached_data.data

        # Caching is disabled or no previous data found
        # or data found not up to date
        data = YahooHelper.download_symbol_day_data(symbol)
        YahooHelper.dump_pickle_file(symbol, DAY_DATA, data)
        return data

    @staticmethod
    def fetch_symbols_day_data(symbols, caching=True):
        result = {}
        missing_symbols = symbols.copy()

        if caching:
            for symbol in symbols:
                cached_data = YahooHelper.check_pickle_file(symbol, DAY_DATA)
                if cached_data:
                    if cached_data.is_up_to_date():
                        result[symbol] = cached_data.data
                        missing_symbols.remove(symbol)

        if missing_symbols:
            missing_data = YahooHelper.download_symbols_day_data(missing_symbols)
            for symbol, data in missing_data.items():
                result[symbol] = data
                YahooHelper.dump_pickle_file(symbol, DAY_DATA, data)

        return result

    # ======Shortcut methods==================================

    @staticmethod
    def get_symbol_info(symbol, caching=True):
        return YahooHelper.fetch_symbol_info(symbol, caching=caching)

    @staticmethod
    def get_symbol_day_data(
        symbol, auto_adjust=True, caching=True, last_needed_datetime=None
    ):
        result = YahooHelper.fetch_symbol_day_data(
            symbol, caching=caching, last_needed_datetime=last_needed_datetime
        )
        return result

    @staticmethod
    def get_symbol_data(
        symbol,
        timestep="day",
        auto_adjust=True,
        caching=True,
        last_needed_datetime=None,
    ):
        if timestep == "day":
            return YahooHelper.get_symbol_day_data(
                symbol,
                auto_adjust=auto_adjust,
                caching=caching,
                last_needed_datetime=last_needed_datetime,
            )
        else:
            raise ValueError("Unknown timestep %s" % timestep)

    @staticmethod
    def get_symbols_day_data(symbols, auto_adjust=True, caching=True):
        result = YahooHelper.fetch_symbols_day_data(symbols, caching=caching)
        for key, df in result.items():
            result[key] = YahooHelper.format_df(df, auto_adjust)
        return result

    @staticmethod
    def get_symbols_data(symbols, timestep="day", auto_adjust=True, caching=True):
        if timestep == "day":
            return YahooHelper.get_symbols_day_data(
                symbols, auto_adjust=auto_adjust, caching=caching
            )
        else:
            raise ValueError("Unknown timestep %s" % timestep)

    @staticmethod
    def get_symbol_dividends(symbol, caching=True):
        """https://github.com/ranaroussi/yfinance/blob/main/yfinance/base.py"""
        history = YahooHelper.get_symbol_day_data(symbol, caching=caching)
        dividends = history["Dividends"]
        return dividends[dividends != 0].dropna()

    @staticmethod
    def get_symbols_dividends(symbols, caching=True):
        result = {}
        data = YahooHelper.get_symbols_day_data(symbols, caching=caching)
        for symbol, df in data.items():
            dividends = df["Dividends"]
            result[symbol] = dividends[dividends != 0].dropna()

        return result

    @staticmethod
    def get_symbol_splits(symbol, caching=True):
        """https://github.com/ranaroussi/yfinance/blob/main/yfinance/base.py"""
        history = YahooHelper.get_symbol_day_data(symbol, caching=caching)
        splits = history["Stock Splits"]
        return splits[splits != 0].dropna()

    @staticmethod
    def get_symbols_splits(symbols, caching=True):
        result = {}
        data = YahooHelper.get_symbols_day_data(symbols, caching=caching)
        for symbol, df in data.items():
            splits = df["Stock Splits"]
            result[symbol] = splits[splits != 0].dropna()

        return result

    @staticmethod
    def get_symbol_actions(symbol, caching=True):
        """https://github.com/ranaroussi/yfinance/blob/main/yfinance/base.py"""
        history = YahooHelper.get_symbol_day_data(symbol, caching=caching)
        actions = history[["Dividends", "Stock Splits"]]
        return actions[actions != 0].dropna(how="all").fillna(0)

    @staticmethod
    def get_symbols_actions(symbols, caching=True):
        result = {}
        data = YahooHelper.get_symbols_day_data(symbols, caching=caching)
        for symbol, df in data.items():
            actions = df[["Dividends", "Stock Splits"]]
            result[symbol] = actions[actions != 0].dropna(how="all").fillna(0)

        return result

    @staticmethod
    def get_risk_free_rate(with_logging=True, caching=True):
        # 13 Week Treasury Rate (^IRX)
        irx_price = YahooHelper.get_symbol_last_price("^IRX")
        risk_free_rate = irx_price / 100
        if with_logging:
            logging.info(f"Risk Free Rate {risk_free_rate * 100:0.2f}%")

        return risk_free_rate

    # ==========Appending Data====================================

    @staticmethod
    def append_actions_data(symbol, df, caching=True):
        if df.empty:
            return df

        df = df.copy()
        df["dividend"] = 0
        df["stock_splits"] = 0

        dividends_actions = YahooHelper.get_symbol_actions(symbol, caching=caching)
        start = df.index[0]
        end = df.index[-1]
        filtered_actions = dividends_actions[
            (dividends_actions.index >= start) & (dividends_actions.index <= end)
        ]

        for index, row in filtered_actions.iterrows():
            dividends = row["Dividends"]
            stock_splits = row["Stock Splits"]
            search = df[df.index >= index]
            if not search.empty:
                target_day = search.index[0]
                df.loc[target_day, "dividend"] = dividends
                df.loc[target_day, "stock_splits"] = stock_splits

        return df
