"""Historical data loading for backtesting."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyupbit

from trading.core.models import OHLCV

logger = logging.getLogger(__name__)


@dataclass
class HistoricalDataPoint:
    """Single historical data point for backtesting.

    Attributes:
        timestamp: Data point timestamp.
        ohlcv: OHLCV data up to this point.
        current_price: Price at this timestamp.
        change_24h_pct: 24-hour change percentage.
        volume_24h: 24-hour trading volume.
    """

    timestamp: datetime
    ohlcv: list[OHLCV]
    current_price: float
    change_24h_pct: float
    volume_24h: float


class HistoricalDataLoader:
    """Load historical market data for backtesting.

    Supports loading from Upbit API or local CSV files.
    """

    def __init__(self, cache_dir: Path | None = None):
        """Initialize data loader.

        Args:
            cache_dir: Directory for caching data.
        """
        self.cache_dir = cache_dir or Path("data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load_ohlcv(
        self,
        symbol: str = "KRW-BTC",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        interval: str = "day",
        count: int = 200,
    ) -> pd.DataFrame:
        """Load OHLCV data from Upbit.

        Args:
            symbol: Trading pair (e.g., "KRW-BTC").
            start_date: Start date (optional).
            end_date: End date (optional, defaults to now).
            interval: Candle interval ("minute1", "minute5", "day", etc.).
            count: Number of candles to fetch (max 200 per request).

        Returns:
            DataFrame with OHLCV data.
        """
        logger.info(f"Loading OHLCV data for {symbol}, interval={interval}")

        if end_date is None:
            end_date = datetime.now()

        # Fetch data from Upbit
        if interval == "day":
            df = pyupbit.get_ohlcv(symbol, interval=interval, count=count, to=end_date)
        elif interval.startswith("minute"):
            minutes = int(interval.replace("minute", ""))
            df = pyupbit.get_ohlcv(
                symbol, interval=f"minute{minutes}", count=count, to=end_date
            )
        else:
            df = pyupbit.get_ohlcv(symbol, interval=interval, count=count, to=end_date)

        if df is None or df.empty:
            logger.warning(f"No data returned for {symbol}")
            return pd.DataFrame()

        # Rename columns for consistency
        df = df.rename(
            columns={
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
                "value": "value",
            }
        )

        logger.info(f"Loaded {len(df)} candles from {df.index.min()} to {df.index.max()}")
        return df

    def load_extended_ohlcv(
        self,
        symbol: str = "KRW-BTC",
        days: int = 365,
        interval: str = "day",
    ) -> pd.DataFrame:
        """Load extended OHLCV data by making multiple API requests.

        Args:
            symbol: Trading pair.
            days: Number of days of data to fetch.
            interval: Candle interval.

        Returns:
            DataFrame with extended OHLCV data.
        """
        logger.info(f"Loading extended OHLCV data: {days} days")

        all_data = []
        end_date = datetime.now()
        batch_size = 200

        # Calculate number of batches needed
        if interval == "day":
            batches_needed = (days // batch_size) + 1
        else:
            # For minute intervals, calculate based on interval
            batches_needed = min(10, (days * 24 * 60 // batch_size) + 1)

        for i in range(batches_needed):
            df = self.load_ohlcv(
                symbol=symbol,
                end_date=end_date,
                interval=interval,
                count=batch_size,
            )

            if df.empty:
                break

            all_data.append(df)
            end_date = df.index.min() - timedelta(seconds=1)

            if len(df) < batch_size:
                break

        if not all_data:
            return pd.DataFrame()

        # Combine and sort
        combined = pd.concat(all_data)
        combined = combined[~combined.index.duplicated(keep="first")]
        combined = combined.sort_index()

        logger.info(f"Loaded total {len(combined)} candles")
        return combined

    def prepare_backtest_data(
        self,
        df: pd.DataFrame,
        lookback_period: int = 50,
    ) -> list[HistoricalDataPoint]:
        """Prepare data points for backtesting.

        Converts DataFrame to list of HistoricalDataPoint objects,
        each containing the OHLCV history up to that point.

        Args:
            df: OHLCV DataFrame.
            lookback_period: Number of candles to include in each point's history.

        Returns:
            List of HistoricalDataPoint objects.
        """
        if len(df) < lookback_period + 1:
            logger.warning(f"Insufficient data: {len(df)} < {lookback_period + 1}")
            return []

        data_points = []

        for i in range(lookback_period, len(df)):
            # Get OHLCV history up to this point
            history_df = df.iloc[i - lookback_period : i + 1]

            ohlcv_list = [
                OHLCV(
                    timestamp=idx.to_pydatetime(),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row["volume"],
                )
                for idx, row in history_df.iterrows()
            ]

            # Calculate 24h change
            current_price = df.iloc[i]["close"]
            if i >= 1:
                prev_price = df.iloc[i - 1]["close"]
                change_24h = ((current_price - prev_price) / prev_price) * 100
            else:
                change_24h = 0.0

            # Calculate 24h volume
            volume_24h = df.iloc[max(0, i - 24) : i + 1]["volume"].sum()

            data_points.append(
                HistoricalDataPoint(
                    timestamp=df.index[i].to_pydatetime(),
                    ohlcv=ohlcv_list,
                    current_price=current_price,
                    change_24h_pct=change_24h,
                    volume_24h=volume_24h,
                )
            )

        logger.info(f"Prepared {len(data_points)} data points for backtesting")
        return data_points

    def save_to_csv(self, df: pd.DataFrame, filename: str) -> Path:
        """Save DataFrame to CSV file.

        Args:
            df: DataFrame to save.
            filename: Output filename.

        Returns:
            Path to saved file.
        """
        filepath = self.cache_dir / filename
        df.to_csv(filepath)
        logger.info(f"Saved data to {filepath}")
        return filepath

    def load_from_csv(self, filename: str) -> pd.DataFrame:
        """Load DataFrame from CSV file.

        Args:
            filename: Input filename.

        Returns:
            Loaded DataFrame.
        """
        filepath = self.cache_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"Cache file not found: {filepath}")

        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        logger.info(f"Loaded {len(df)} rows from {filepath}")
        return df
