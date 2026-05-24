"""Configuration management using pydantic-settings."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Upbit API
    upbit_access_key: str = Field(default="", description="Upbit API access key")
    upbit_secret_key: str = Field(default="", description="Upbit API secret key")

    # CoinMarketCap API
    cmc_api_key: str = Field(default="", description="CoinMarketCap API key")

    # OpenAI API — tiered models for cost optimization
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o-mini", description="Default OpenAI model")
    openai_model_decision: str = Field(
        default="gpt-4o-mini", description="Model for trading decisions (core)"
    )
    openai_model_analysis: str = Field(
        default="gpt-4o-mini", description="Model for news analysis (auxiliary)"
    )
    openai_model_vision: str = Field(
        default="gpt-4o", description="Model for chart pattern vision analysis (conditional)"
    )

    # Slack (optional)
    slack_webhook_url: str = Field(default="", description="Slack webhook URL for alerts")

    # Email (optional)
    email_enabled: bool = Field(default=False, description="Enable email notifications")
    email_smtp_server: str = Field(default="smtp.gmail.com", description="SMTP server address")
    email_smtp_port: int = Field(default=587, description="SMTP server port")
    email_sender: str = Field(default="", description="Sender email address")
    email_password: str = Field(default="", description="Email password or app password")
    email_recipient: str = Field(default="", description="Recipient email address")

    # Trading mode
    trading_mode: Literal["paper", "live"] = Field(
        default="paper", description="Trading mode: paper or live"
    )

    # Risk management
    max_daily_loss_pct: float = Field(
        default=3.0, ge=0.0, le=100.0, description="Maximum daily loss percentage"
    )
    max_position_pct: float = Field(
        default=50.0, ge=0.0, le=100.0, description="Maximum position as % of portfolio"
    )
    min_order_krw: float = Field(
        default=5000.0, ge=0.0, description="Minimum order amount in KRW"
    )

    # Isolated test mode (trade with limited capital)
    isolated_mode: bool = Field(
        default=False, description="Enable isolated trading mode (protect existing holdings)"
    )
    isolated_capital_krw: float = Field(
        default=200000.0, ge=5000.0, description="Maximum capital to use in isolated mode"
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_dir: Path = Field(default=Path("logs"), description="Directory for log files")

    # LLM call frequency controls
    llm_cache_ttl_seconds: int = Field(
        default=900,
        ge=60,
        le=3600,
        description="Seconds to cache HOLD LLM decisions (default 15min, must exceed polling interval)",
    )
    max_trades_per_day: int = Field(
        default=20,
        ge=1,
        le=500,
        description="Maximum BUY trades per day. SELL is always allowed (stop-loss exemption).",
    )
    stop_loss_pct: float = Field(
        default=2.0,
        ge=0.0,
        le=20.0,
        description=(
            "Force-exit threshold on unrealized P&L (positive number, percent). "
            "When the open BTC position loses more than this, DecisionAgent emits a "
            "SELL with bypass_hysteresis=True so the exit is not throttled. "
            "Set to 0 to disable."
        ),
    )

    # Event-driven streaming mode
    streaming_enabled: bool = Field(
        default=False, description="Enable WebSocket streaming mode"
    )
    streaming_symbols: list[str] = Field(
        default=["KRW-BTC"], description="Symbols to stream in event-driven mode"
    )
    trigger_cooldown_seconds: float = Field(
        default=60.0, ge=10.0, description="Minimum seconds between LLM calls"
    )
    event_batch_window_seconds: float = Field(
        default=10.0, ge=1.0, description="Seconds to batch events before LLM"
    )

    # Hysteresis (decision oscillation prevention)
    hysteresis_enabled: bool = Field(
        default=True, description="Enable hysteresis for streaming mode"
    )
    hysteresis_mode: Literal["streaming", "daily", "conservative"] = Field(
        default="streaming",
        description="Hysteresis preset: streaming (low), daily (medium), conservative (high)",
    )

    # Trend detection
    trend_mode: Literal["fast", "normal", "slow"] = Field(
        default="normal",
        description="Trend detection mode: fast (EMA 5/10/20), normal (EMA 10/20/50), slow (EMA 20/50/100)",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is valid."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid_levels:
            raise ValueError(f"Invalid log level: {v}. Must be one of {valid_levels}")
        return upper

    @property
    def is_paper_trading(self) -> bool:
        """Check if running in paper trading mode."""
        return self.trading_mode == "paper"

    @property
    def is_live_trading(self) -> bool:
        """Check if running in live trading mode."""
        return self.trading_mode == "live"

    def validate_api_keys(self) -> list[str]:
        """Validate required API keys are set.

        Returns:
            List of missing or invalid API key names.
        """
        missing = []

        if not self.upbit_access_key:
            missing.append("UPBIT_ACCESS_KEY")
        if not self.upbit_secret_key:
            missing.append("UPBIT_SECRET_KEY")
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        # CMC is optional but recommended
        if not self.cmc_api_key:
            missing.append("CMC_API_KEY (optional)")

        return missing


# Global settings instance (lazy loaded)
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get application settings (singleton).

    Returns:
        Settings instance loaded from environment.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings from environment.

    Returns:
        Fresh Settings instance.
    """
    global _settings
    _settings = Settings()
    return _settings
