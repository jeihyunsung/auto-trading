# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LLM-based automated BTC trading agent using LangGraph for multi-agent orchestration and OpenAI for decision-making. Trades on Upbit (Korean exchange) with paper trading support. Includes Binance Futures public data for derivatives sentiment.

## Commands

```bash
# Install dependencies
uv sync --extra dev --extra dashboard

# Validate configuration
python -m trading.main --validate-only

# Run single trading cycle (paper trading)
python -m trading.main --mode single

# Run continuous trading (5-minute intervals)
python -m trading.main --mode continuous --interval 300

# Use simple linear pipeline instead of supervisor
python -m trading.main --mode single --simple

# Event-driven streaming mode (WebSocket + rule-based triggers)
python -m trading.main --streaming --cooldown 60

# Backtest
python -m trading.backtest.cli --days 30 --interval 300

# Dashboard (requires dashboard extra)
python -m trading.dashboard.app

# Run tests
pytest tests/ -v
pytest tests/test_core/test_hysteresis.py -v       # single file
pytest tests/test_core/test_hysteresis.py::test_name -v  # single test

# Linting and type checking
ruff check src/ tests/
mypy src/
```

## Architecture

### Multi-Agent System (LangGraph)

Two graph modes in `src/trading/graph/builder.py`:

1. **Supervisor Graph** (`trading_graph`): Dynamic routing via supervisor node that selects agents based on state
2. **Simple Pipeline** (`simple_pipeline`): Linear flow for testing: market → news → indicators → decision → risk → execution → ops

```
supervisor → market_agent → supervisor
           → news_agent → supervisor
           → indicator_agent → supervisor
           → decision_agent → risk_agent → execution_agent → ops_agent → END
```

### Key Components

- **`core/state.py`**: `TradingState` TypedDict schema shared across all agents
- **`agents/`**: Each agent has a class and a `*_node()` function for LangGraph integration
- **`adapters/upbit.py`**: `UpbitBrokerAdapter` with paper trading simulation
- **`adapters/binance_futures.py`**: Public Binance Futures data (OI, L/S ratios, funding rates) — no API key needed
- **`llm/client.py`**: `LLMClient` wrapper for OpenAI with JSON parsing
- **`config.py`**: Pydantic-settings configuration from `.env`
- **`graph/edges.py`**: Conditional edge logic for supervisor routing

### TradingState Flow

The `TradingState` TypedDict accumulates data as it flows through the graph:
- `market`: Price, OHLCV, orderbook, volatility
- `news`: Headlines, sentiment (-1 to 1), impact level, memorized articles
- `indicators`: Trend, momentum, RSI, MACD signals
- `decision`: Action (BUY/SELL/HOLD), confidence, rationale
- `risk`: Daily loss %, position limits, kill switch
- `portfolio`: KRW balance, BTC balance, exposure

### Decision Flow

1. LLM-based decision (if OpenAI key available): Structured prompts in `llm/prompts.py`
2. Rule-based fallback: Counts bullish/bearish signals from indicators and sentiment
3. Hysteresis filter: Prevents rapid action reversals (BUY↔SELL) via `core/hysteresis.py`

### Position Sizing (`core/position_sizing.py`)

Tiered confidence-to-position mapping: calculates target position % based on model confidence, then determines delta from current position. Trades only execute if delta exceeds minimum threshold.

### Isolated Balance Tracking (`core/isolated_tracker.py`, `core/isolated_balance.py`)

Sandboxed balance tracking for the bot's allocated capital (KRW spent, BTC acquired, available funds), independent from user's existing Upbit holdings. Allows the bot to operate within a dedicated budget.

### Risk Management (`risk/`)

- **`limits.py`**: Enforces daily loss limits, position limits, min/max trade sizes
- **`validator.py`**: Validates LLM decisions against confidence thresholds and portfolio constraints; optional LLM secondary validation

### Event-Driven Mode (Streaming)

Two-layer architecture minimizing LLM costs:

```
Layer 1: Real-time monitoring (no LLM cost)
  WebSocket → MessageHandler → TriggerEvaluator → EventDispatcher

Layer 2: LLM decision (only when triggered)
  EventBatch → LangGraph pipeline → Decision/Execute
```

Trigger conditions (configurable in `triggers/conditions.py`):
- Price change: 1min ≥1%, 5min ≥2%, 24h ≥5%
- Volume spike: ≥5x average
- RSI extreme: ≤20 or ≥80

Cost controls: 60s cooldown between LLM calls, 10s event batching window, 300s post-trade cooldown.

### Indicators (`indicators/`)

- **`trend.py`**: EMA crossovers, Bollinger Bands
- **`momentum.py`**: RSI, MACD, OBV
- **`volatility.py`**: ATR, volatility metrics
- **`multi_timeframe.py`**: EMA-based trend alignment across 5m/1h/4h/1d timeframes for confidence adjustments

### Anomaly Detection (`core/anomaly.py`)

Detects sudden price surges/drops, volume spikes, and volatility spikes with configurable thresholds and severity classification.

### History & Dashboard

Append-only JSONL recorders in `core/`:
- `decision_history.py`: BUY/SELL/HOLD decisions with confidence
- `indicator_history.py`: RSI, MACD, Bollinger, OBV snapshots
- `derivatives_history.py`: OI, L/S ratios, funding rates
- `history_reader.py`: Loads JSONL history across date ranges for the dashboard

Dashboard (`dashboard/app.py`): Streamlit UI displaying decisions, indicator charts, price movements, and derivatives sentiment with i18n support.

### Backtest Engine (`backtest/`)

Simulates trading on historical data with configurable fees/slippage. CLI in `backtest/cli.py` with parameters for days, interval, initial capital. Generates reports via `backtest/report.py` with metrics from `backtest/metrics.py`.

## News System

### Filtering (`core/news_filter.py`)

Actionable: `breaking`, `regulatory`, `listing`, `security`, `partnership`, `etf`
Non-actionable (filtered): `analysis`, `educational`, `rehash`

### Memory (`core/news_memory.py`)

TTL: 4h, decay half-life: 1h. Duplicate detection via content hash. Blended sentiment: `current * 0.6 + memory * 0.4`.

## Decision Hysteresis (`core/hysteresis.py`)

Prevents BUY↔SELL flip-flopping. For reversals, requires confidence delta ≥ threshold (default 0.35). Example: BUY@0.70 → SELL needs ≥1.05 confidence (blocked → converted to HOLD).

CLI flags: `--hysteresis-reversal-delta 0.4`, `--no-hysteresis`

## Environment Variables

Required in `.env`:
- `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY`: Upbit API credentials
- `OPENAI_API_KEY`: For LLM decision-making

Optional:
- `CMC_API_KEY`: CoinMarketCap for additional data
- `TRADING_MODE`: "paper" (default) or "live"
- `OPENAI_MODEL`: Default "gpt-4o-mini"
- `NEWS_MEMORY_ENABLED`, `NEWS_MEMORY_TTL_HOURS`, `NEWS_DECAY_HALF_LIFE_HOURS`
- `NEWS_FILTER_ENABLED`: Enable news filtering (default: true)

## Testing

Uses pytest with `pytest-asyncio` (`asyncio_mode = "auto"`). Paper trading mode auto-enabled in tests. Key fixtures in `tests/conftest.py`: `mock_upbit`, `mock_env`.

```bash
pytest tests/ -v
pytest tests/test_core/test_hysteresis.py -v
pytest --cov=src/trading tests/  # coverage
```
