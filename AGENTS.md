# Repository Guidelines

## Project Structure & Module Organization
Core application code lives in `src/trading/`. Key areas include `agents/` for trading decision agents, `adapters/` for external integrations, `backtest/` for simulation tooling, `dashboard/` for the Streamlit UI, and `core/`, `graph/`, `risk/`, and `triggers/` for shared trading logic. Tests mirror the package layout under `tests/` (for example, `tests/test_core/` and `tests/test_risk/`). Supporting documentation is in `docs/`, automation scripts are in `scripts/`, and generated backtest artifacts belong in `backtest_results/`.

## Build, Test, and Development Commands
Use Python 3.12 and prefer `uv`.

- `uv sync --extra dev --extra dashboard`: install runtime, test, and dashboard dependencies.
- `uv run python -m trading.main --validate-only`: verify configuration without placing trades.
- `uv run python -m trading.main --mode single`: run one paper-trading cycle.
- `uv run python -m trading.main --mode continuous --interval 300`: run the loop every 5 minutes.
- `uv run python -m trading.backtest.cli`: execute the backtest CLI.
- `uv run pytest -v`: run the full test suite.
- `uv run ruff check .` and `uv run mypy src`: lint and type-check before opening a PR.

## Coding Style & Naming Conventions
Follow Ruff and MyPy settings in `pyproject.toml`: Python 3.12, 100-character line length, strict typing, and import sorting enabled. Use 4-space indentation, `snake_case` for modules/functions, `PascalCase` for classes, and descriptive test names such as `test_rejects_order_above_limit`. Keep new modules inside the existing domain folders instead of creating parallel top-level packages.

## Testing Guidelines
Tests use `pytest` with `pytest-asyncio` (`asyncio_mode = "auto"`). Place tests in the matching `tests/test_<area>/` package and name files `test_<feature>.py`. Prefer small unit tests with mocks or fixtures from `tests/conftest.py` for API-dependent code. Run `uv run pytest -v` locally; use `uv run pytest --cov=src/trading` when checking impact on critical trading logic.

## Commit & Pull Request Guidelines
Git history is not available in this workspace, so follow a consistent imperative style such as `feat: add trailing-stop validation` or `fix: handle empty news feed`. Keep commits focused and explain behavior changes in the PR description. PRs should include the affected trading path, validation steps run (`pytest`, `ruff`, `mypy`, backtest command), linked issues, and screenshots when changing `src/trading/dashboard/`.

## Security & Configuration Tips
Copy `.env.example` to `.env` and keep exchange and LLM keys out of version control. Use paper-trading or validation modes for development. Do not commit generated files from `backtest_results/` unless they are intentionally part of an analysis update.
