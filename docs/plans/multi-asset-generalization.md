# Multi-Asset Generalization Plan (BTC → BTC/ETH/XRP)

## Context

현재 봇은 BTC 단일 자산에 코드 전반이 하드코딩되어 있다. 5/31 백테스트로 ETH/XRP에서도 같은 코드를 돌릴 수 있는지 검증:

- **ETH**: Alpha -2.0% (BTC와 거의 동일 거동, 안전장치 정합) ✅
- **XRP**: Alpha -4.89% (변동성으로 stop-loss whipsaw, 임계 재조정 필요) ⚠️
- **BTC live 봇**: 8일 운영 중 (-0.83%, Alpha +4.2%)

목표: **자산별 별도 봇 인스턴스로 같은 코드 재사용**. Multi-asset 단일 봇은 자금 분배 로직이 복잡해서 제외.

## Goals

1. 하드코딩된 `BTC` / `KRW-BTC` / `BTCUSDT` 제거 — settings 기반 동적 분기
2. `IsolatedBalance`를 asset-agnostic하게 (필드명 `btc` → `asset_balance`)
3. 자산별 별도 `.env` + systemd 서비스 + 격리 잔고 파일 운영
4. 자산별 stop-loss/take-profit 임계 분리 (XRP는 더 넓게)
5. **기존 BTC 봇 운영 중단 없이** 변경 — backward compatibility 유지

## Non-Goals

- Multi-asset 단일 인스턴스 (자금 분배 logic 별도 큰 작업)
- 자산 추가는 BTC/ETH/XRP 3종만 (확장은 그 후)
- LLM prompt 자산별 customization (BTC와 같은 prompt로 시작)

## Change Inventory

코드에서 식별된 BTC 하드코딩 50+ 곳을 6개 카테고리로 분류:

### Category A: Settings + 분기 (entry point)

| 파일 | 변경 |
|---|---|
| `src/trading/config.py` | `trading_asset` (BTC/ETH/XRP), `upbit_symbol`, `binance_futures_symbol` 자동 derive; `stop_loss_pct` / `take_profit_pct` asset-specific overlay |
| `src/trading/main.py` + `main_async.py` | `balances.get("BTC", ...)` → `balances.get(settings.asset_symbol, ...)` |

### Category B: Isolated balance tracker (자산 일반화)

| 파일 | 변경 |
|---|---|
| `src/trading/core/isolated_balance.py` | `IsolatedBalance.btc` → `IsolatedBalance.asset_balance` + `asset_symbol`; `record_buy/sell` 파라미터명 일반화; `get_balances()`가 `{"KRW": ..., asset_symbol: ...}` 반환 |
| state file 경로 | `logs/isolated_balance.json` → `logs/isolated_balance_<asset>.json` (`__init__`에서 settings 기반 derive) |

### Category C: Execution + Risk

| 파일 | 변경 |
|---|---|
| `src/trading/agents/execution_agent.py` | `symbol = "KRW-BTC"` → `settings.upbit_symbol`; `isolated_balances.get("BTC", ...)` → `get(settings.asset_symbol, ...)`; 12+ 곳 |
| `src/trading/risk/limits.py` | `PortfolioState.btc_value_krw` → `asset_value_krw`; helper 이름 일반화 |
| `src/trading/risk/validator.py` | error message "No BTC holdings to sell" → 동적; `portfolio.btc_value_krw` 참조 갱신 |

### Category D: Market data + Binance Futures

| 파일 | 변경 |
|---|---|
| `src/trading/adapters/binance_futures.py` | `get_binance_futures_provider()` singleton 폐기, 또는 symbol 인자 받는 factory; `_provider` 자산별 dict |
| `src/trading/agents/market_agent.py` | `collect(symbol="KRW-BTC")` default 제거, settings 사용 |

### Category E: Performance + History

| 파일 | 변경 |
|---|---|
| `src/trading/core/performance.py` | `PortfolioSnapshot.btc_balance/btc_price/btc_value_krw` → `asset_balance/asset_price/asset_value_krw`; `_initial_btc_price` rename |
| `src/trading/core/state.py` | `Portfolio.btc_balance` → `asset_balance` |
| `src/trading/core/indicator_history.py` | `btc_price` 필드 rename |
| `logs/portfolio_snapshots.jsonl`, `indicators_*.jsonl` | **schema 호환성** — 기존 BTC 데이터 못 읽으면 dashboard 부서짐. `Field(alias=...)` 또는 `from_dict`가 양쪽 키 처리 |

### Category F: LLM prompts

| 파일 | 변경 |
|---|---|
| `src/trading/llm/prompts.py` | `{btc_balance}` → `{asset_balance}` + `{asset_symbol}` (또는 그냥 "asset"); SELL signals 설명도 일반화 |
| `src/trading/llm/schemas.py` | `LLMDecisionInput.btc_balance` → `asset_balance` (LLM 호출에 영향 없음 — 내부 필드명만) |
| `src/trading/agents/decision_agent.py` | `_decide_with_llm`에서 prompt format 호출 시 키 변경 |

## Codex Review Findings (2026-05-31 반영)

Codex가 plan을 비판적으로 검토한 결과 4가지 critical 이슈 발견:

### 🚨 Critical 1 — `backtest/` 모듈 전체 누락

원래 plan은 `backtest/engine.py` 외에는 backtest 계열을 잡지 않았다. 실제로는:
- `backtest/engine.py:320` — `market.symbol = "KRW-BTC"` 고정
- `backtest/engine.py:362-368` — `portfolio["btc_balance"]` LLM 입력 직접 사용
- `backtest/derivatives_loader.py:65` — provider 미전달 시 BTCUSDT 기본
- `backtest/data.py:52,107` — `symbol="KRW-BTC"` 기본
- `backtest/cli.py:48-52` — `--symbol KRW-BTC` 하드코딩
- `backtest/metrics.py:108-111` — `btc_price` 직접 참조
- `backtest/report.py:191-210` — CSV 헤더 `btc_quantity`, `btc_price`

이대로 두면 ETH/XRP 백테스트가 조용히 BTC 데이터를 사용하게 됨. → **새 Phase 4b로 분리**.

### 🚨 Critical 2 — Pydantic alias 전략은 적용 안 됨

`performance.py`와 `indicator_history.py`는 **Pydantic이 아니라 dataclass + `from_dict()`**. Pydantic `Field(alias=...)`는 이 파일들에 영향 없음. 재시작 시 `performance.py:187-211`이 기존 JSONL 전체를 읽는데 키 이름 다르면 `from_dict()` 실패 → BTC 봇 재시작 망함.

**수정**: alias 전략 → "**dual-read + per-row normalize**"로 변경. `from_dict()`에서 `asset_*` 우선, 없으면 `btc_*` fallback. `HistoryReader.get_portfolio_snapshots()`도 raw dict normalize.

### 🚨 Critical 3 — 로그 전략은 Phase 1 설계 제약

ETH/XRP 인스턴스가 같은 `log_dir`로 시작하면 5종 JSONL 모두 즉시 오염:
- `execution_agent.py:318-321` → `trades_YYYYMMDD.jsonl`
- `decision_history.py:91-93` → `decisions_YYYYMMDD.jsonl`
- `indicator_history.py:101-115` → `indicators_YYYYMMDD.jsonl`
- `derivatives_history.py:94-107` → `derivatives_YYYYMMDD.jsonl`
- `performance.py:295-296` → `portfolio_snapshots.jsonl`

**수정**: Phase 7 배포가 아니라 **Phase 1에서 `logs/btc/`, `logs/eth/`, `logs/xrp/` 디렉토리 분리** 결정. `dashboard/app.py:31-35`의 `TRADING_LOG_DIR`와 `settings.log_dir`가 환경변수로 이미 분리 가능.

### 🚨 Critical 4 — `market_agent.py` CMC fallback BTC 고정

- `agents/market_agent.py:67-72` — symbol 무관하게 `self.cmc.get_btc_quote()` 호출
- ETH/XRP 백테스트 1h/24h 변화율이 BTC 기준으로 들어가 결정 품질 직격타

**수정**: Phase 4a에 포함 (CMC fallback도 자산별 quote 사용).

### ⚠️ Phase 순서 변경

Phase 4 (Binance Futures)가 너무 뒤에 있어서 ETH/XRP 검증 시점에 잘못된 데이터 사용. 새 순서:

```
Phase 1 (settings + log_dir 분리)
  → Phase 4a (futures provider + market_agent CMC + derivatives_loader)
  → Phase 4b (backtest 모듈 일반화)
  → Phase 2 (isolated balance)
  → Phase 3 (execution/risk)
  → Phase 5 (history/dashboard with dual-read)
  → Phase 6 (prompts/pattern)
  → Phase 7 (deploy)
```

### ⚠️ XRP 임계값 수정 권고

stop-loss 4% + take-profit 1.5%는 리워드/리스크 불균형. Codex 권고:
- `STOP_LOSS_PCT=4.0`, `TAKE_PROFIT_PCT=2.5~3.5`
- `action_reversal_delta`: 0.15 → 0.25~0.35
- `post_trade_cooldown`: 15분 → 20~30분
- stop-loss/take-profit은 `bypass_hysteresis=True`라 긴급 탈출 영향 없음

### ⚠️ Effort 재추정: 5일 → 6~8일

| Phase | 추정 |
|---|---|
| 1 settings + log_dir | 0.5~1일 |
| 4a futures/CMC/loader | 0.5~1일 |
| 4b backtest 일반화 | 0.5~1일 (신규) |
| 2 isolated balance | 1~1.5일 |
| 3 execution/risk | 1~1.5일 |
| 5 history/dashboard | 1.5~2.5일 (회귀 위험 최고) |
| 6 prompts/pattern | 0.5~1일 |
| 7 deploy + paper soak | 1~2일 + soak 1~2주 |

### 💡 추가로 plan에 명시할 파일

- `agents/pattern_agent.py` — 차트/프롬프트 BTC 고정
- `config.py:173-175` `streaming_symbols`
- `main_async.py:492-495` `--symbols` 기본값

---

## Implementation Order (Codex 반영 후 — 안전 우선)

### Phase 1 — Settings + log_dir 분리 (영향 없음)

1. `config.py`에 신규 필드:
   - `trading_asset: Literal["BTC", "ETH", "XRP"] = "BTC"` (default BTC → 기존 봇 영향 없음)
   - `upbit_symbol: str` (computed: `f"KRW-{trading_asset}"`)
   - `binance_futures_symbol: str` (computed: `f"{trading_asset}USDT"`)
   - `stop_loss_pct_override`, `take_profit_pct_override` (자산별 dict)
2. 단위 테스트로 settings 로드 확인. 코드 변경 없음.
3. Commit + push. 라이브 봇 영향 0.

### Phase 2 — IsolatedBalance asset 일반화

1. `IsolatedBalance` dataclass에 `asset_symbol: str = "BTC"` 추가 (기본값 BTC).
2. `btc` 필드는 유지하되 **alias** `asset_balance` 추가 (`Field(validation_alias=AliasChoices(...))`) — 기존 BTC json 로드 호환.
3. `record_buy/sell` 메서드는 그대로 두되 내부적으로 `_balance.btc` (legacy)와 `_balance.asset_balance` 동기화.
4. State file 경로:
   - `settings.asset_symbol == "BTC"`이면 `isolated_balance.json` (기존 경로) 유지
   - 그 외 `isolated_balance_<asset>.json`
   - → BTC 봇 영향 0
5. ETH/XRP 봇은 새 파일 경로로 깨끗이 시작.
6. 단위 테스트로 BTC json 로드 + ETH 새 instance 둘 다 검증.

### Phase 3 — Execution + Risk

1. `execution_agent.py` 변경:
   - `symbol = settings.upbit_symbol`
   - `balances.get(settings.asset_symbol, Decimal("0"))`
2. `risk/limits.py` + `validator.py` 변경:
   - `PortfolioState`에 `asset_value_krw` 추가 (별칭). `btc_value_krw`는 deprecated alias로 유지.
3. BTC backtest 회귀 확인 — 기존 결과 재현.

### Phase 4 — Binance Futures multi-symbol provider

1. `BinanceFuturesDataProvider`는 이미 symbol 인자 받음 — singleton만 변경.
2. `get_binance_futures_provider(symbol=None)` → 캐시 `_providers: dict[str, BinanceFuturesDataProvider]`.
3. `market_agent.collect_derivatives()` → settings 기반 symbol 전달.

### Phase 5 — Performance / History schema 호환

1. `PortfolioSnapshot` / `IndicatorSnapshot` 필드 rename:
   - `btc_price` → `asset_price` (with alias for legacy reads)
   - `btc_balance` → `asset_balance` (alias)
   - `btc_value_krw` → `asset_value_krw` (alias)
2. `from_dict` 메서드에서 양쪽 키 처리 (`data.get("asset_price", data.get("btc_price"))`).
3. Dashboard 코드 (`history_reader.py`, `dashboard/app.py`) 같이 갱신.
4. 기존 BTC `portfolio_snapshots.jsonl` (13K+ rows) 그대로 읽혀야 함.

### Phase 6 — LLM prompts

1. `prompts.py`의 `{btc_balance}` → `{asset_balance}` 변경.
2. Prompt 본문 "BTC"라는 단어가 명시된 곳에 `{asset_symbol}` 또는 "the asset" 사용.
3. **단, LLM이 BTC 단어로 학습된 가능성** — A/B 테스트로 prompt 변화가 결정 품질에 영향 미치는지 확인.

### Phase 7 — 운영 (배포)

1. VM에 신규 systemd 서비스 `trading-bot-eth.service`, `trading-bot-xrp.service` 작성:
   - `ExecutionAgent=... python -m trading.main --streaming`
   - `EnvironmentFile=/home/dawn-h/auto-trading/.env.eth` (또는 `.env.xrp`)
2. `.env.eth`:
   ```
   TRADING_ASSET=ETH
   ISOLATED_MODE=true
   ISOLATED_CAPITAL_KRW=500000   # 보수적 시작
   STOP_LOSS_PCT=2.0             # ETH는 BTC와 같음
   TAKE_PROFIT_PCT=1.5
   ```
3. `.env.xrp`:
   ```
   TRADING_ASSET=XRP
   ISOLATED_MODE=true
   ISOLATED_CAPITAL_KRW=300000   # 더 보수적
   STOP_LOSS_PCT=4.0             # 변동성 큰 자산 — 백테스트 반영
   TAKE_PROFIT_PCT=2.5
   ```
4. Watchdog 스크립트도 자산별 인스턴스 처리 — 현재는 `trading-bot` 단일. `trading-bot-{btc,eth,xrp}` 모두 모니터링하도록 일반화.
5. ETH 먼저 paper로 1주 운영 → 결과 좋으면 live → XRP는 stop-loss 재조정 후 별도 결정.

## Critical Files

코드 변경 대상 (Phase별 정리):

```
src/trading/
├── config.py                              # Phase 1
├── core/
│   ├── isolated_balance.py                # Phase 2
│   ├── performance.py                     # Phase 5
│   ├── state.py                           # Phase 5
│   └── indicator_history.py               # Phase 5
├── agents/
│   ├── execution_agent.py                 # Phase 3
│   ├── market_agent.py                    # Phase 4
│   └── decision_agent.py                  # Phase 6 (prompt format key)
├── risk/
│   ├── limits.py                          # Phase 3
│   └── validator.py                       # Phase 3
├── adapters/
│   └── binance_futures.py                 # Phase 4
├── llm/
│   ├── prompts.py                         # Phase 6
│   └── schemas.py                         # Phase 6
├── dashboard/app.py                       # Phase 5
└── main.py + main_async.py                # Phase 1 wiring
```

## Backward Compatibility Strategy

기존 BTC 봇이 무중단으로 가동되어야 한다. 모든 phase에서:

- Settings default = BTC → `.env`에 `TRADING_ASSET` 없으면 BTC
- File path 분기: `asset_symbol == "BTC"`이면 기존 경로 유지
- Pydantic `Field(validation_alias=AliasChoices("asset_balance", "btc"))` 패턴으로 양쪽 키 읽기 가능
- Schema 변경은 **읽기만 alias 처리 (양쪽), 쓰기는 신규 키 사용**

## Verification

각 phase 후:

1. **단위 테스트**: `uv run python -m pytest tests/ -q` (현재 48 통과)
2. **BTC 회귀 백테스트**: 같은 5일 데이터로 backtest → 결과 동일성 확인 (alpha/trades/MDD)
3. **ETH 백테스트**: 새 코드로 다시 → 이전 결과(-2% alpha) 재현
4. **XRP 백테스트** (Phase 7 직전): stop-loss 4% 조정 후 알파 측정. 0% 이상이면 deploy 검토.
5. **VM smoke** (Phase 7): paper mode로 ETH/XRP 봇 1시간 가동 후 freeze/에러 없음 확인

## Operational Changes

배포 후 상태:

```
VM: trading-bot.gcp
├── systemd: trading-bot         (BTC, 기존)
├── systemd: trading-bot-eth     (신규)
├── systemd: trading-bot-xrp     (신규, fix 완료 후)
├── /home/dawn-h/auto-trading/
│   ├── .env                     (BTC, 기존)
│   ├── .env.eth                 (신규)
│   ├── .env.xrp                 (신규)
│   └── logs/
│       ├── isolated_balance.json          (BTC)
│       ├── isolated_balance_eth.json      (신규)
│       ├── isolated_balance_xrp.json      (신규)
│       ├── trades_<date>.jsonl            (자산별 또는 단일? 결정 필요)
│       └── decisions_<date>.jsonl         (동일)
└── /usr/local/bin/trading-bot-watchdog.sh (3개 서비스 모두 모니터링)
```

**미해결 의문**: trade/decision/indicator 로그를 자산별로 분리할지 단일로 둘지. 단일이면 dashboard에서 자산 필터링 가능하지만 schema에 asset 필드 추가 필요. 자산별 분리면 dashboard URL/필터 추가.

## Risks

1. **기존 BTC 봇 회귀**: schema 변경으로 기존 JSONL 파일 못 읽으면 dashboard 망가짐 → alias 처리 + 회귀 백테스트로 차단
2. **LLM prompt 변화로 결정 다름**: "BTC" → "asset" 변경이 미묘하게 LLM bias에 영향 → A/B 백테스트로 확인
3. **자산별 stop-loss 임계 잘못**: XRP 4%로 했는데도 whipsaw → 추가 백테스트 + 모니터링
4. **3개 봇 동시 가동 부담**: VM e2-small 메모리/CPU → 모니터링, 필요시 업그레이드
5. **LLM 비용 3배** ($0.05 → $0.15/일): 작지만 추세 모니터링

## Effort Estimate

- Phase 1 (settings): 0.5일
- Phase 2 (isolated balance): 1일 (alias 처리 + 테스트)
- Phase 3 (execution + risk): 1일
- Phase 4 (Binance Futures): 0.5일
- Phase 5 (performance/history schema): 1.5일 (회귀 위험 가장 큼)
- Phase 6 (LLM prompts): 0.5일
- Phase 7 (배포 + paper 검증): 1주

**총 코드 작업 ~5일 + 검증 1~2주**

## Next Step

1. Codex review로 이 plan 검증
2. Phase 1부터 순차 진행 (BTC 봇 회귀 없는지 매 phase 검증)
