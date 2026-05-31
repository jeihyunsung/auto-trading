"""Isolated balance tracking for independent bot operation.

This module provides balance tracking that is isolated from the user's
existing holdings, allowing the bot to operate with a dedicated budget.
"""

import atexit
import errno
import fcntl
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trading.config import get_settings
from trading.core.time import KST

logger = logging.getLogger(__name__)


def _now_kst_iso() -> str:
    """Return current KST timestamp in ISO 8601 format."""
    return datetime.now(KST).isoformat()


@dataclass
class IsolatedBalance:
    """Isolated balance state for bot operation.

    Tracks the bot's sandboxed capital for a single asset. The original
    schema hard-coded BTC; the new schema stores asset_balance + asset_symbol
    so the same class can back ETH/XRP bot instances. Reads remain
    backward-compatible with existing BTC `isolated_balance.json` files
    via from_dict's dual-key fallback.

    Attributes:
        krw: Available KRW balance for the bot.
        asset_balance: Asset holdings (BTC/ETH/XRP) acquired by the bot.
        asset_symbol: Ticker for the held asset (default "BTC").
        initial_capital: Starting capital in KRW.
        total_invested: Total KRW invested in the asset.
        total_fees: Total fees paid.
        created_at: When isolated tracking started (KST).
        last_updated: Last update timestamp (KST).
        daily_start_value: Total portfolio value (KRW) at start of today (KST).
        daily_start_date: Date string (YYYY-MM-DD) for daily rebase.
    """

    krw: Decimal
    asset_balance: Decimal
    initial_capital: Decimal
    asset_symbol: str = "BTC"
    total_invested: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    created_at: str = field(default_factory=_now_kst_iso)
    last_updated: str = field(default_factory=_now_kst_iso)
    daily_start_value: Decimal = Decimal("0")  # 0 means "not yet seeded"
    daily_start_date: str = ""

    @property
    def btc(self) -> Decimal:
        """Legacy alias kept so existing call sites still compile until
        Phase 3 sweeps execution_agent/market_agent."""
        return self.asset_balance

    @btc.setter
    def btc(self, value: Decimal) -> None:
        self.asset_balance = value

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization.

        Writes both the new asset_balance/asset_symbol fields AND the legacy
        "btc" mirror so that:
          - older bot binaries (if rolled back) still see "btc".
          - dashboards / external readers expecting "btc" don't break.
        The legacy mirror can be dropped once the live BTC bot has run
        through one save cycle on the new code.
        """
        return {
            "krw": str(self.krw),
            "asset_balance": str(self.asset_balance),
            "asset_symbol": self.asset_symbol,
            "btc": str(self.asset_balance),  # legacy mirror — TODO: remove after burn-in
            "initial_capital": str(self.initial_capital),
            "total_invested": str(self.total_invested),
            "total_fees": str(self.total_fees),
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "daily_start_value": str(self.daily_start_value),
            "daily_start_date": self.daily_start_date,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IsolatedBalance":
        """Create from dictionary with backward-compatible dual-key read.

        Live BTC bot state files only have the legacy "btc" key. New
        files (and resaved BTC files) have "asset_balance" + "asset_symbol".
        from_dict prefers new keys, falls back to legacy ones.
        """
        # Prefer new key; fall back to legacy "btc" so BTC live state loads.
        asset_balance_str = data.get("asset_balance", data.get("btc", "0"))
        asset_symbol = data.get("asset_symbol", "BTC")
        return cls(
            krw=Decimal(data["krw"]),
            asset_balance=Decimal(asset_balance_str),
            asset_symbol=asset_symbol,
            initial_capital=Decimal(data["initial_capital"]),
            total_invested=Decimal(data.get("total_invested", "0")),
            total_fees=Decimal(data.get("total_fees", "0")),
            created_at=data.get("created_at", _now_kst_iso()),
            last_updated=data.get("last_updated", _now_kst_iso()),
            daily_start_value=Decimal(data.get("daily_start_value", "0")),
            daily_start_date=data.get("daily_start_date", ""),
        )


class IsolatedBalanceTracker:
    """Tracks bot's isolated balance separate from exchange account.

    This allows the bot to operate with a dedicated budget without
    being affected by existing holdings on the exchange.
    """

    def __init__(
        self,
        initial_capital_krw: float | None = None,
        state_file: Path | None = None,
        asset_symbol: str | None = None,
    ):
        """Initialize isolated balance tracker.

        Args:
            initial_capital_krw: Starting capital (uses config if None).
            state_file: File to persist state. If None, derived from
                settings.isolated_balance_path so BTC keeps the legacy
                logs/isolated_balance.json while ETH/XRP get per-asset files.
            asset_symbol: Override asset (e.g., 'ETH', 'XRP'). If None,
                taken from settings.asset_symbol.

        Raises:
            RuntimeError: If another process already holds the tracker lock
                for the same state file. Prevents two bot instances from
                corrupting the shared balance JSON.
        """
        settings = get_settings()
        self._initial_capital = Decimal(
            str(initial_capital_krw or settings.isolated_capital_krw)
        )
        self._asset_symbol = asset_symbol or settings.asset_symbol
        self._state_file = state_file or settings.isolated_balance_path
        self._balance: IsolatedBalance | None = None
        self._lock_file = None  # Held for tracker lifetime

        # Acquire exclusive single-instance lock BEFORE loading state.
        # Releases automatically on process exit via atexit.
        self._acquire_instance_lock()

        # Load or create initial state
        self._load_or_create()

    def _acquire_instance_lock(self) -> None:
        """Acquire an OS-level exclusive lock to prevent dual-process corruption.

        Uses fcntl.flock on a sibling .lock file. Raises RuntimeError if
        another process already holds the lock so the operator sees the
        conflict instead of having two bots silently fight over the JSON.
        """
        lock_path = self._state_file.with_suffix(self._state_file.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Open the lock file (kept open for the tracker's lifetime).
        try:
            fp = open(lock_path, "w")
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise RuntimeError(
                    f"Another bot instance is holding {lock_path}. "
                    f"Refusing to start to prevent isolated_balance.json corruption. "
                    f"If this is stale, remove the .lock file manually."
                ) from None
            raise
        fp.write(f"{os.getpid()}\n")
        fp.flush()
        self._lock_file = fp
        atexit.register(self._release_instance_lock)

    def _release_instance_lock(self) -> None:
        """Release the instance lock and remove the lock file."""
        if self._lock_file is None:
            return
        try:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            self._lock_file.close()
            lock_path = self._state_file.with_suffix(self._state_file.suffix + ".lock")
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
        except Exception as e:
            logger.warning(f"Lock release error (ignoring): {e}")
        self._lock_file = None

    def _load_or_create(self) -> None:
        """Load existing state or create new one."""
        if self._state_file.exists():
            try:
                with open(self._state_file) as f:
                    data = json.load(f)
                self._balance = IsolatedBalance.from_dict(data)
                # Ensure asset_symbol on loaded state matches the tracker's
                # configured asset. Loaded BTC files have asset_symbol="BTC";
                # a mismatch would mean the operator pointed an ETH bot at
                # a BTC state file by accident — fail loud rather than
                # silently rewriting the holdings under a different ticker.
                if self._balance.asset_symbol != self._asset_symbol:
                    raise RuntimeError(
                        f"Isolated state file {self._state_file} holds "
                        f"{self._balance.asset_symbol} but tracker was "
                        f"initialized for {self._asset_symbol}. Refusing "
                        f"to mix assets. Point to a different state file "
                        f"or reset."
                    )
                logger.info(
                    f"Loaded isolated balance: KRW={self._balance.krw:,.0f}, "
                    f"{self._balance.asset_symbol}={self._balance.asset_balance:.8f}"
                )
                return
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning(f"Failed to load isolated balance: {e}")

        # Create new state
        self._balance = IsolatedBalance(
            krw=self._initial_capital,
            asset_balance=Decimal("0"),
            asset_symbol=self._asset_symbol,
            initial_capital=self._initial_capital,
        )
        self._save()
        logger.info(
            f"Created new isolated balance with {self._initial_capital:,.0f} KRW "
            f"for asset={self._asset_symbol}"
        )

    def _save(self) -> None:
        """Persist state to file atomically.

        Writes to a temp sibling then os.replace() — POSIX-atomic rename
        guarantees readers never see a half-written file even if the
        process is killed mid-write. Prevents JSON corruption / silent
        balance loss on crash or concurrent updates.
        """
        if self._balance is None:
            return

        self._balance.last_updated = _now_kst_iso()
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = self._state_file.with_suffix(self._state_file.suffix + ".tmp")
        with open(tmp_path, "w") as f:
            json.dump(self._balance.to_dict(), f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, self._state_file)

    @property
    def balance(self) -> IsolatedBalance:
        """Get current balance state."""
        if self._balance is None:
            self._load_or_create()
        return self._balance  # type: ignore

    @property
    def asset_symbol(self) -> str:
        """Ticker of the asset tracked by this instance."""
        return self._asset_symbol

    def get_balances(self) -> dict[str, Decimal]:
        """Get balances in broker-compatible format.

        Returns:
            Dict with KRW and the tracker's asset balance, keyed by ticker.
            Example: {'KRW': ..., 'BTC': ...} or {'KRW': ..., 'ETH': ...}.
        """
        return {
            "KRW": self.balance.krw,
            self._asset_symbol: self.balance.asset_balance,
        }

    def get_krw_balance(self) -> Decimal:
        """Get available KRW balance."""
        return self.balance.krw

    def get_asset_balance(self) -> Decimal:
        """Get asset balance (asset-agnostic)."""
        return self.balance.asset_balance

    def get_btc_balance(self) -> Decimal:
        """Get asset balance (legacy alias). Prefer get_asset_balance()."""
        return self.balance.asset_balance

    def record_buy(
        self,
        krw_spent: Decimal,
        asset_received: Decimal | None = None,
        fee_krw: Decimal = Decimal("0"),
        *,
        btc_received: Decimal | None = None,  # legacy kw alias
    ) -> bool:
        """Record a BUY transaction.

        Args:
            krw_spent: KRW amount spent (before fees).
            asset_received: Asset amount received (BTC/ETH/XRP).
            fee_krw: Fee paid in KRW.
            btc_received: Legacy alias for asset_received. Existing call
                sites that pass btc_received= keep working unchanged.

        Returns:
            True if recorded successfully, False if insufficient balance.
        """
        if asset_received is None:
            asset_received = btc_received
        if asset_received is None:
            raise TypeError("record_buy requires asset_received (or btc_received)")

        total_cost = krw_spent + fee_krw

        if total_cost > self.balance.krw:
            logger.warning(
                f"Insufficient isolated KRW: {self.balance.krw:,.0f} < {total_cost:,.0f}"
            )
            return False

        self._balance.krw -= total_cost
        self._balance.asset_balance += asset_received
        self._balance.total_invested += krw_spent
        self._balance.total_fees += fee_krw
        self._save()

        logger.info(
            f"Isolated BUY: -{krw_spent:,.0f} KRW, "
            f"+{asset_received:.8f} {self._asset_symbol}, "
            f"fee={fee_krw:,.0f} KRW"
        )
        return True

    def record_sell(
        self,
        asset_sold: Decimal | None = None,
        krw_received: Decimal | None = None,
        fee_krw: Decimal = Decimal("0"),
        *,
        btc_sold: Decimal | None = None,  # legacy kw alias
    ) -> bool:
        """Record a SELL transaction.

        Args:
            asset_sold: Asset amount sold (BTC/ETH/XRP).
            krw_received: KRW amount received (after fees).
            fee_krw: Fee paid in KRW.
            btc_sold: Legacy alias for asset_sold.

        Returns:
            True if recorded successfully, False if insufficient balance.
        """
        if asset_sold is None:
            asset_sold = btc_sold
        if asset_sold is None or krw_received is None:
            raise TypeError(
                "record_sell requires asset_sold (or btc_sold) and krw_received"
            )

        if asset_sold > self.balance.asset_balance:
            logger.warning(
                f"Insufficient isolated {self._asset_symbol}: "
                f"{self.balance.asset_balance:.8f} < {asset_sold:.8f}"
            )
            return False

        # Reduce total_invested proportionally to amount sold so the
        # remaining holdings keep the correct average cost basis.
        if self._balance.asset_balance > 0 and self._balance.total_invested > 0:
            sell_ratio = asset_sold / self._balance.asset_balance
            invested_reduction = self._balance.total_invested * sell_ratio
            self._balance.total_invested -= invested_reduction

        self._balance.asset_balance -= asset_sold
        self._balance.krw += krw_received
        self._balance.total_fees += fee_krw
        self._save()

        logger.info(
            f"Isolated SELL: -{asset_sold:.8f} {self._asset_symbol}, "
            f"+{krw_received:,.0f} KRW, fee={fee_krw:,.0f} KRW"
        )
        return True

    def _rebase_daily_if_needed(self, total_value: Decimal) -> None:
        """Reset daily_start_value at KST midnight.

        Called from get_portfolio_value whenever a new KST day starts so
        that daily P&L tracks today-only change instead of cumulative.
        Persists across restarts via daily_start_date in the state file.
        """
        today = datetime.now(KST).strftime("%Y-%m-%d")
        if self._balance.daily_start_date != today:
            self._balance.daily_start_date = today
            self._balance.daily_start_value = total_value
            self._save()
            logger.info(
                f"Daily P&L rebased for {today}: start_value={total_value:,.0f} KRW"
            )

    def get_portfolio_value(self, asset_price: float | None = None,
                            btc_price: float | None = None) -> dict:
        """Calculate current portfolio value.

        Args:
            asset_price: Current asset price in KRW (BTC/ETH/XRP).
            btc_price: Legacy alias for asset_price.

        Returns:
            Dict with portfolio metrics. Includes BOTH `asset_balance`
            (new) and `btc_balance` (legacy mirror) keys, plus
            `asset_value_krw`/`btc_value_krw`, so callers can migrate
            piecemeal without breaking dashboards.
        """
        if asset_price is None:
            asset_price = btc_price
        if asset_price is None:
            raise TypeError("get_portfolio_value requires asset_price (or btc_price)")

        asset_value = float(self.balance.asset_balance) * asset_price
        total_value = float(self.balance.krw) + asset_value
        initial = float(self.balance.initial_capital)
        total_invested = float(self.balance.total_invested)

        # Daily P&L (rebased at KST midnight) — used by RiskAgent for the
        # daily loss limit. Without this, cumulative pnl would falsely
        # trigger the limit on long-running bots.
        self._rebase_daily_if_needed(Decimal(str(total_value)))
        daily_start = float(self._balance.daily_start_value)
        if daily_start > 0:
            daily_pnl_pct = ((total_value / daily_start) - 1) * 100
        else:
            daily_pnl_pct = 0.0

        # Unrealized P&L: asset position only (current value vs invested
        # amount). Measures gain/loss on holdings, not including cash.
        if total_invested > 0 and self.balance.asset_balance > 0:
            unrealized_pnl_pct = ((asset_value / total_invested) - 1) * 100
        else:
            unrealized_pnl_pct = 0.0

        asset_balance_float = float(self.balance.asset_balance)
        return {
            "krw_balance": float(self.balance.krw),
            "asset_balance": asset_balance_float,
            "btc_balance": asset_balance_float,  # legacy mirror
            "asset_symbol": self._asset_symbol,
            "asset_value_krw": asset_value,
            "btc_value_krw": asset_value,  # legacy mirror
            "total_value_krw": total_value,
            "initial_capital_krw": initial,
            "total_invested_krw": total_invested,
            "pnl_krw": total_value - initial,
            "pnl_pct": ((total_value / initial) - 1) * 100 if initial > 0 else 0,
            "daily_pnl_pct": daily_pnl_pct,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "exposure_pct": (asset_value / total_value * 100) if total_value > 0 else 0,
            "total_fees_krw": float(self.balance.total_fees),
        }

    def reset(self, new_capital: Decimal | None = None) -> None:
        """Reset to initial state.

        Args:
            new_capital: New initial capital (uses current if None).
        """
        capital = new_capital or self._initial_capital
        self._balance = IsolatedBalance(
            krw=capital,
            asset_balance=Decimal("0"),
            asset_symbol=self._asset_symbol,
            initial_capital=capital,
        )
        self._save()
        logger.info(
            f"Isolated balance reset to {capital:,.0f} KRW "
            f"for asset={self._asset_symbol}"
        )

    def adjust_capital(self, target_capital: float) -> None:
        """Adjust capital to target amount while preserving current holdings.

        Args:
            target_capital: Target initial capital in KRW.
        """
        target = Decimal(str(target_capital))
        current = self._balance.initial_capital
        diff = target - current

        if diff == 0:
            return

        # Adjust KRW balance by the difference
        new_krw = self._balance.krw + diff
        if new_krw < 0:
            logger.warning(
                f"Cannot reduce capital by {-diff:,.0f} KRW. "
                f"Current KRW balance is only {self._balance.krw:,.0f}"
            )
            return

        self._balance.krw = new_krw
        self._balance.initial_capital = target
        self._save()

        action = "Added" if diff > 0 else "Reduced"
        logger.info(
            f"{action} {abs(diff):,.0f} KRW capital. "
            f"New initial_capital={self._balance.initial_capital:,.0f}, "
            f"KRW={self._balance.krw:,.0f}"
        )

    def get_stats(self) -> dict:
        """Get statistics summary.

        Returns:
            Dict with balance statistics. Includes both `asset_balance`
            (new) and `btc` (legacy mirror) keys for backward compatibility.
        """
        asset_balance_float = float(self.balance.asset_balance)
        return {
            "krw": float(self.balance.krw),
            "asset_balance": asset_balance_float,
            "btc": asset_balance_float,  # legacy mirror
            "asset_symbol": self._asset_symbol,
            "initial_capital": float(self.balance.initial_capital),
            "total_invested": float(self.balance.total_invested),
            "total_fees": float(self.balance.total_fees),
            "created_at": self.balance.created_at,
            "last_updated": self.balance.last_updated,
        }


# Module-level singleton
_isolated_tracker: IsolatedBalanceTracker | None = None


def get_isolated_tracker() -> IsolatedBalanceTracker | None:
    """Get global isolated tracker instance.

    Returns:
        IsolatedBalanceTracker if isolated mode enabled, None otherwise.
    """
    return _isolated_tracker


def set_isolated_tracker(tracker: IsolatedBalanceTracker | None) -> None:
    """Set global isolated tracker instance.

    Args:
        tracker: Tracker instance or None to disable.
    """
    global _isolated_tracker
    _isolated_tracker = tracker


def init_isolated_tracker_if_enabled() -> IsolatedBalanceTracker | None:
    """Initialize isolated tracker if isolated mode is enabled in settings.

    Returns:
        IsolatedBalanceTracker if enabled, None otherwise.
    """
    settings = get_settings()
    if not settings.isolated_mode:
        return None

    tracker = IsolatedBalanceTracker(
        initial_capital_krw=settings.isolated_capital_krw
    )
    set_isolated_tracker(tracker)
    return tracker
