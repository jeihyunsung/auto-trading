# 트레이딩 의사결정 로직

이 문서는 Auto Trading Bot의 BUY/SELL/HOLD 판단 근거를 상세히 설명합니다.

## 목차

1. [전체 의사결정 흐름](#1-전체-의사결정-흐름)
2. [데이터 수집](#2-데이터-수집)
3. [기술적 지표 분석](#3-기술적-지표-분석)
4. [파생상품 지표 분석](#4-파생상품-지표-분석)
5. [이상 감지](#5-이상-감지)
6. [의사결정 로직](#6-의사결정-로직)
7. [Hysteresis (진동 방지)](#7-hysteresis-진동-방지)
8. [리스크 검증](#8-리스크-검증)
9. [주문 실행](#9-주문-실행)
10. [포지션 크기 결정](#10-포지션-크기-결정)
11. [판단 예시](#11-판단-예시)

> **참고**: 백테스트 결과 및 Hysteresis 효과 분석은 [BACKTEST_RESULTS.md](./BACKTEST_RESULTS.md)를 참조하세요.

---

## 1. 전체 의사결정 흐름

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        1단계: 데이터 수집                                 │
├──────────────────────────────────────────────────────────────────────────┤
│  MarketAgent        →   현재가, OHLCV, 호가창, 24h 변동률, 포트폴리오   │
│                     →   파생상품 지표 (OI, L/S Ratio, Funding Rate)     │
│                     →   다중 시간프레임 (5m/1h/4h/1d) OHLCV/추세 정렬   │
│  IndicatorAgent     →   RSI, MACD, BB, OBV, 추세 채널, 모멘텀, 변동성  │
│  PatternAgent       →   차트 패턴 (Vision LLM, 조건부 발동)              │
│  AnomalyDetector    →   가격급등/급락, 거래량급증, 변동성스파이크        │
└──────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────────────┐
│                        2단계: 의사결정                                    │
├──────────────────────────────────────────────────────────────────────────┤
│  DecisionAgent      →   LLM 또는 규칙 기반으로 BUY/SELL/HOLD 결정       │
│                         - LLM: GPT-4o-mini 기반 종합 분석                │
│                         - Fallback: 규칙 기반 신호 카운팅               │
│                                                                          │
│  HysteresisManager  →   급격한 액션 변경 방지 (진동 필터링)             │
│                         - 방향 반전(BUY↔SELL): delta ≥ 0.25 필요        │
│                         - 새 포지션(HOLD→BUY/SELL): delta ≥ 0.10 필요   │
│                         - 긴급 오버라이드: confidence ≥ 0.85            │
└──────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────────────┐
│                        3단계: 리스크 검증                                 │
├──────────────────────────────────────────────────────────────────────────┤
│  RiskAgent          →   포지션 한도, 일일 손실 한도, 최소 주문금액 검증  │
│                         - 킬 스위치 확인                                 │
│                         - 확신도 임계값: BUY/SELL ≥ 60%                 │
│                         - 포지션 한도: ≤ 50%                            │
│                         - 최소 주문: ≥ 5,000 KRW                        │
│                         - 승인(approved) 또는 거부(rejected)             │
└──────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────────────┐
│                        4단계: 실행                                        │
├──────────────────────────────────────────────────────────────────────────┤
│  ExecutionAgent     →   Upbit API로 실제 주문 실행                       │
│                         - Isolated Mode: 봇 전용 자본으로 독립 운영      │
│                         - 최소 주문금액 미달 시 전량 매도 자동 처리      │
│  OpsAgent           →   Slack 알림 발송                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 데이터 수집

### 2.1 MarketAgent

**소스 파일**: `src/trading/agents/market_agent.py`

Upbit API와 CoinMarketCap API에서 시장 데이터를 수집합니다.

| 데이터 | 설명 | 소스 |
|--------|------|------|
| `current_price` | 현재 BTC 가격 (KRW) | Upbit |
| `ohlcv` | 일봉 캔들 데이터 (시가/고가/저가/종가/거래량) | Upbit |
| `orderbook` | 호가창 데이터 | Upbit |
| `percent_change_1h` | 1시간 변동률 | CoinMarketCap |
| `percent_change_24h` | 24시간 변동률 | Upbit / CoinMarketCap |
| `volatility_level` | 변동성 수준 (low/medium/high) | OHLCV 기반 계산 |

### 2.2 파생상품 데이터 (Binance Futures)

**소스 파일**: `src/trading/adapters/binance_futures.py`

Binance Futures 공개 API에서 파생상품 지표를 수집합니다. **API 키 불필요**.

| 데이터 | 설명 | 소스 |
|--------|------|------|
| `open_interest` | 미결제약정 (계약 수) | Binance Futures |
| `open_interest_value` | 미결제약정 가치 (USDT) | Binance Futures |
| `oi_change_pct_1h` | OI 1시간 변화율 | 계산 |
| `oi_change_pct_24h` | OI 24시간 변화율 | 계산 |
| `long_short_ratio` | 글로벌 롱/숏 비율 | Binance Futures |
| `top_trader_long_short_ratio` | 탑 트레이더 롱/숏 비율 | Binance Futures |
| `funding_rate` | 펀딩비 (8시간) | Binance Futures |
| `oi_trend` | OI 추세 (increasing/decreasing/stable) | 계산 |
| `position_bias` | 포지션 편향 (long_heavy/short_heavy/balanced) | 계산 |
| `funding_signal` | 펀딩 신호 (overheated_long/overheated_short/neutral) | 계산 |

### 2.3 포트폴리오 데이터

**소스 파일**: `src/trading/agents/market_agent.py` (`collect_portfolio` 메서드)

실시간 Upbit 잔고를 조회하여 포트폴리오 상태를 수집합니다.

| 데이터 | 설명 |
|--------|------|
| `cash_krw` | KRW 잔고 |
| `btc_balance` | BTC 보유량 |
| `btc_value_krw` | BTC 가치 (KRW) |
| `total_value_krw` | 총 자산 가치 |
| `exposure_pct` | BTC 노출도 (%) |

### 2.4 IndicatorAgent

**소스 파일**: `src/trading/agents/indicator_agent.py`

기술적 지표를 계산하여 시장 상태를 파악합니다.

| 출력 | 설명 | 가능한 값 |
|------|------|----------|
| `trend` | 추세 방향 | bullish / bearish / neutral |
| `momentum` | 모멘텀 상태 | overbought / oversold / neutral |
| `volatility` | 변동성 수준 | low / medium / high |
| `signals.rsi` | RSI 값 | 0 ~ 100 |
| `signals.macd_histogram` | MACD 히스토그램 | 양수/음수 |

---

## 3. 기술적 지표 분석

### 3.1 추세 신호 (Trend Signal)

**소스 파일**: `src/trading/indicators/trend.py`

**단기 + 중기 EMA**를 조합하여 빠른 추세 감지와 확인을 동시에 수행합니다.

```
┌─────────────────────────────────────────────────────────────┐
│              추세 판단 기준 (가중치 적용)                     │
├─────────────────────────────────────────────────────────────┤
│  [단기 신호] - 가중치 2배 (빠른 반응)                        │
├─────────────────────────────────────────────────────────────┤
│  1. EMA 5 vs EMA 10                                         │
│     - EMA 5 > EMA 10   →  Bullish (+1, 가중 후 +2)         │
│     - EMA 5 < EMA 10   →  Bearish (+1, 가중 후 +2)         │
├─────────────────────────────────────────────────────────────┤
│  2. 현재가 vs EMA 5                                         │
│     - 현재가 > EMA 5   →  Bullish (+1, 가중 후 +2)         │
│     - 현재가 < EMA 5   →  Bearish (+1, 가중 후 +2)         │
├─────────────────────────────────────────────────────────────┤
│  [중기 신호] - 가중치 1배 (추세 확인)                        │
├─────────────────────────────────────────────────────────────┤
│  3. EMA 10 vs EMA 20                                        │
│     - EMA 10 > EMA 20  →  Bullish (+1)                     │
│     - EMA 10 < EMA 20  →  Bearish (+1)                     │
├─────────────────────────────────────────────────────────────┤
│  4. 현재가 vs EMA 20                                        │
│     - 현재가 > EMA 20  →  Bullish (+1)                     │
│     - 현재가 < EMA 20  →  Bearish (+1)                     │
├─────────────────────────────────────────────────────────────┤
│  5. MACD 히스토그램                                         │
│     - MACD > 0         →  Bullish (+1)                     │
│     - MACD < 0         →  Bearish (+1)                     │
└─────────────────────────────────────────────────────────────┘

가중 합산:
- total_bullish = (short_bullish × 2) + medium_bullish  (최대 7)
- total_bearish = (short_bearish × 2) + medium_bearish  (최대 7)

결과:
- total_bullish ≥ 4 & bullish > bearish  →  "bullish"
- total_bearish ≥ 4 & bearish > bullish  →  "bearish"
- 그 외                                   →  "neutral"
```

**OHLCV 데이터**: 1분봉 100개 사용 (~1.7시간 데이터)

### 3.2 모멘텀 신호 (Momentum Signal)

**소스 파일**: `src/trading/indicators/momentum.py`

RSI와 Stochastic 지표로 과매수/과매도 상태를 판단합니다.

| 지표 | 과매수 (Overbought) | 과매도 (Oversold) |
|------|---------------------|-------------------|
| RSI (14일) | ≥ 70 | ≤ 30 |
| Stochastic %K | ≥ 80 | ≤ 20 |

```
결과:
- 1개 이상 과매수 조건 충족  →  "overbought" (하락 가능성)
- 1개 이상 과매도 조건 충족  →  "oversold" (반등 가능성)
- 그 외                      →  "neutral"
```

### 3.3 RSI (Relative Strength Index)

**7일 기간**의 상대강도지수를 계산합니다. (기존 14일 → 7일로 변경하여 빠른 반응)

| RSI 범위 | 해석 |
|----------|------|
| 0 ~ 30 | 과매도 (매수 기회) |
| 30 ~ 70 | 중립 |
| 70 ~ 100 | 과매수 (매도 기회) |

### 3.4 MACD (Moving Average Convergence Divergence)

- **MACD Line**: EMA(12) - EMA(26)
- **Signal Line**: MACD의 EMA(9)
- **Histogram**: MACD - Signal

```
히스토그램 해석:
- 양수 & 증가  →  강한 상승 모멘텀
- 양수 & 감소  →  상승 모멘텀 약화
- 음수 & 감소  →  강한 하락 모멘텀
- 음수 & 증가  →  하락 모멘텀 약화
```

---

## 4. 파생상품 지표 분석

**소스 파일**: `src/trading/adapters/binance_futures.py`

Binance Futures 공개 API에서 수집한 파생상품 데이터로 시장 심리를 분석합니다.

### 4.1 미결제약정 (Open Interest)

미결제약정은 아직 청산되지 않은 선물 계약의 총 수량입니다.

```
┌─────────────────────────────────────────────────────────────────┐
│                    OI + 가격 조합 해석                           │
├─────────────────────────────────────────────────────────────────┤
│  OI 증가 + 가격 상승  →  강한 상승 추세 (새 롱 진입)            │
│                         신뢰도 높은 BUY 신호                     │
├─────────────────────────────────────────────────────────────────┤
│  OI 증가 + 가격 하락  →  강한 하락 추세 (새 숏 진입)            │
│                         신뢰도 높은 SELL 신호                    │
├─────────────────────────────────────────────────────────────────┤
│  OI 감소 + 가격 변동  →  추세 약화 (포지션 청산 중)             │
│                         신중한 접근 필요, HOLD 선호              │
└─────────────────────────────────────────────────────────────────┘
```

**OI 추세 분류 기준**:
| 조건 | 결과 |
|------|------|
| 1h 변화 > 2% 또는 24h 변화 > 5% | `increasing` |
| 1h 변화 < -2% 또는 24h 변화 < -5% | `decreasing` |
| 그 외 | `stable` |

### 4.2 롱/숏 비율 (Long/Short Ratio)

롱 포지션과 숏 포지션의 비율로 시장 편향을 파악합니다.

```
┌─────────────────────────────────────────────────────────────────┐
│                 롱/숏 비율 역발상 (Contrarian) 신호              │
├─────────────────────────────────────────────────────────────────┤
│  L/S > 1.5   →  롱 과다 (Too Many Longs)                        │
│                 • 더 이상 매수 여력 없음                         │
│                 • 청산 캐스케이드 위험                           │
│                 → 하락 반전 가능성 (SELL 고려)                   │
├─────────────────────────────────────────────────────────────────┤
│  L/S < 0.67  →  숏 과다 (Too Many Shorts)                       │
│                 • Short Squeeze 가능성                          │
│                 • 숏 커버링 매수세 유입                          │
│                 → 상승 반전 가능성 (BUY 고려)                    │
├─────────────────────────────────────────────────────────────────┤
│  0.8 ≤ L/S ≤ 1.2  →  균형 잡힌 시장                             │
│                      → 기술적 지표 따라 판단                     │
└─────────────────────────────────────────────────────────────────┘
```

**왜 롱 과다가 하락 신호인가?**

```
롱 포지션 과다 (L/S > 1.5)
        ↓
대부분이 이미 매수함 → 추가 매수세 부족
        ↓
가격이 조금만 하락해도
        ↓
과도한 롱 포지션들이 손절/청산 (Stop Loss)
        ↓
청산 매도 → 가격 추가 하락
        ↓
더 많은 청산 유발 (Liquidation Cascade)
        ↓
급락 (Long Squeeze)
```

### 4.3 펀딩비 (Funding Rate)

무기한 선물에서 8시간마다 롱/숏 간 교환되는 수수료입니다.

```
┌─────────────────────────────────────────────────────────────────┐
│                      펀딩비 해석                                 │
├─────────────────────────────────────────────────────────────────┤
│  Funding > +0.1%  →  롱 과열 (Longs Pay Shorts)                 │
│                      • 롱 포지션 유지 비용 증가                  │
│                      • 롱 청산 압력                              │
│                      → SELL 신호 (overheated_long)              │
├─────────────────────────────────────────────────────────────────┤
│  Funding < -0.05% →  숏 과열 (Shorts Pay Longs)                 │
│                      • 숏 포지션 유지 비용 증가                  │
│                      • 숏 커버링 압력                            │
│                      → BUY 신호 (overheated_short)              │
├─────────────────────────────────────────────────────────────────┤
│  -0.05% ≤ F ≤ +0.1%  →  중립 (Neutral)                         │
│                          → 다른 지표 참고                        │
└─────────────────────────────────────────────────────────────────┘
```

### 4.4 복합 신호 해석

여러 파생상품 지표를 조합하여 더 강력한 신호를 도출합니다.

| OI 추세 | 포지션 편향 | 펀딩 신호 | 해석 | 권장 액션 |
|---------|------------|----------|------|----------|
| 증가 | 롱 과다 | 롱 과열 | 극단적 낙관 → 반전 임박 | **SELL** |
| 증가 | 숏 과다 | 숏 과열 | 극단적 비관 → 반등 임박 | **BUY** |
| 증가 | 롱 과다 | 중립 | 상승 추세 과열 | SELL 고려 |
| 증가 | 숏 과다 | 중립 | 하락 추세 과열 | BUY 고려 |
| 감소 | Any | Any | 추세 약화, 청산 진행 | **HOLD** |
| 안정 | 균형 | 중립 | 명확한 신호 없음 | HOLD |

### 4.5 LLM 프롬프트 통합

파생상품 데이터는 LLM 의사결정 프롬프트에 다음 형식으로 전달됩니다:

```
### Derivatives Data (Binance Futures)
- Open Interest: 15,234,567,890 USDT (+2.3% 1h, +5.1% 24h)
- OI Trend: increasing
- Long/Short Ratio: 1.45 (Global), 1.32 (Top Traders)
- Position Bias: long_heavy
- Funding Rate: +0.0150%
- Funding Signal: overheated_long
```

**LLM에게 파생상품 해석을 rationale에 포함하도록 지시**:
```
## Derivatives in Rationale (REQUIRED)
You MUST explicitly mention how derivatives data influenced your decision.
Include at least ONE of these in your rationale:
- OI trend and what it means for your decision
- L/S ratio and whether it's a contrarian signal
- Funding rate and market overheating status
```

### 4.6 대시보드 시각화

**소스 파일**: `src/trading/dashboard/app.py`, `src/trading/dashboard/charts.py`

파생상품 지표는 대시보드의 **"파생상품 지표"** 섹션에 표시됩니다:

- **메트릭 카드**: L/S Ratio, Funding Rate, Open Interest, Top Trader L/S
- **시계열 차트**: 3개 지표의 히스토리 (`create_derivatives_chart`)
- **신호 해석**: 현재 시장 상황에 대한 설명

데이터는 `logs/derivatives_YYYYMMDD.jsonl` 파일에 기록됩니다.

---

## 5. 이상 감지

### 5.1 폴링 모드 (MarketAnomalyDetector)

**소스 파일**: `src/trading/core/anomaly.py`

5분 간격 폴링 시 감지하는 이상 현상:

| 이상 유형 | 임계값 | 심각도 분류 |
|----------|--------|------------|
| 가격 급등 (price_surge) | 24h ≥ +5% | 5% → low, 10% → medium, 15% → high |
| 가격 급락 (price_drop) | 24h ≤ -5% | 5% → low, 10% → medium, 15% → high |
| 거래량 급증 (volume_spike) | 평균 대비 ≥ 3x | 3x → low, 5x → medium, 10x → high |
| 변동성 스파이크 (volatility_spike) | ≥ 2σ | 2σ → low, 3σ → medium, 4σ → high |

### 5.2 스트리밍 모드 (TriggerEvaluator)

**소스 파일**: `src/trading/triggers/evaluator.py`

WebSocket 실시간 스트리밍 시 감지하는 이상 현상:

| 트리거 | 조건 | 심각도 |
|--------|------|--------|
| 1분 가격 급등 | ≥ +1.0% | medium |
| 1분 가격 급락 | ≤ -1.0% | medium |
| 5분 가격 급등 | ≥ +2.0% | medium (5% 이상 high) |
| 5분 가격 급락 | ≤ -2.0% | medium (5% 이상 high) |
| 24시간 급등 | ≥ +5.0% | high |
| 24시간 급락 | ≤ -5.0% | high |
| 거래량 급증 | 평균 대비 ≥ 5x | medium (10x 이상 high) |
| RSI 극단적 과매도 | ≤ 20 | high |
| RSI 극단적 과매수 | ≥ 80 | high |
| RSI 과매도 | ≤ 30 | medium |
| RSI 과매수 | ≥ 70 | medium |
| 호가 스프레드 확대 | ≥ 0.5% | medium |

---

## 6. 의사결정 로직

### 6.1 LLM 기반 결정 (Primary)

**소스 파일**: `src/trading/agents/decision_agent.py`

LLM(GPT-4o-mini)에게 모든 수집 데이터를 전달하여 종합 판단을 요청합니다.

**LLM에 전달되는 데이터**:

```
## Market Data
- Symbol: KRW-BTC
- Current Price: 150,000,000 KRW
- 24h Change: +2.5%
- Volatility Level: medium

## News Context
- Sentiment: 0.35 (-1 to +1)
- Impact Level: medium
- Summary: 비트코인 ETF 승인 기대감으로 기관 투자자 유입 증가

## Technical Indicators
- Trend: bullish
- Momentum: oversold
- RSI: 28.5
- MACD Histogram: 150000

## Portfolio
- KRW Balance: 10,000,000
- BTC Balance: 0.05
- Exposure: 42.8%
- Unrealized P&L: +1.2%

## Risk Constraints
- Max Position: 50%
- Max Daily Loss: 3%
- Current Daily P&L: +0.5%

## Anomalies
- price_surge: 24시간 5.2% 급등 (severity: medium)

## Recent Decision History (Last 3)
- Last Trade: BUY (70%) at 2024-02-16T00:20 - RSI 과매도 구간에서 매수
- Last Decision: HOLD (50%) at 2024-02-16T00:35 - 혼합 신호로 관망
```

**LLM 시스템 프롬프트 핵심 지침**:

```
## Position-Aware Decision Framework
CRITICAL: Always consider your current position before deciding!
- If Exposure > 80%: prefer HOLD or SELL, avoid BUY
- If Exposure < 10%: prefer HOLD or BUY, avoid SELL
- If KRW Balance < 5,000: cannot BUY

## Decision Consistency
- Review your recent decision history before making a new decision
- Avoid frequent flip-flopping (e.g., BUY → SELL → BUY)
- To change direction (BUY → SELL): need STRONG signals (confidence > 0.8)
- If market conditions similar to last decision: prefer consistency
```

**LLM 응답 형식**:

```json
{
  "action": "BUY",
  "confidence": 0.75,
  "rationale": "RSI가 과매도 구간에 있고, 추세가 상승세이며, 펀딩비가 마이너스로 숏 과열 상태입니다."
}
```

### 6.2 규칙 기반 결정 (Fallback)

LLM 사용이 불가능한 경우 규칙 기반 폴백 로직이 작동합니다.

```python
# 포지션 상태 확인 (Position-Aware)
exposure = portfolio.exposure_pct
krw_balance = portfolio.cash_krw
btc_balance = portfolio.btc_balance

can_buy = krw_balance > 5000 and exposure < 90   # KRW 있고 90% 미만 투자
can_sell = btc_balance > 0 and exposure > 5      # BTC 있고 5% 이상 노출

# 신호 카운팅
bullish_signals = 0
bearish_signals = 0

# 1. 추세 신호
if trend == "bullish":
    bullish_signals += 1
elif trend == "bearish":
    bearish_signals += 1

# 2. 모멘텀 신호 (역발상)
if momentum == "oversold":    # 과매도 → 반등 기대 → 매수 신호
    bullish_signals += 1
elif momentum == "overbought": # 과매수 → 하락 기대 → 매도 신호
    bearish_signals += 1

# 3. RSI
if rsi < 30:      # 과매도 → 매수 신호
    bullish_signals += 1
elif rsi > 70:    # 과매수 → 매도 신호
    bearish_signals += 1
```

**결정 기준 (포지션 인식)**:

| 조건 | 포지션 체크 | 액션 | 확신도 |
|------|------------|------|--------|
| bullish_signals ≥ 3 | can_buy = True | **BUY** | bullish_signals / 4 |
| bullish_signals ≥ 3 | can_buy = False | **HOLD** | 0.5 ("이미 투자됨") |
| bearish_signals ≥ 3 | can_sell = True | **SELL** | bearish_signals / 4 |
| bearish_signals ≥ 3 | can_sell = False | **HOLD** | 0.5 ("포지션 없음") |
| 그 외 | - | **HOLD** | 0.3 ~ 0.4 |

---

## 7. Hysteresis (진동 방지)

**소스 파일**: `src/trading/core/hysteresis.py`

Hysteresis는 의사결정의 급격한 변동(BUY↔SELL↔HOLD 진동)을 방지하는 안정화 로직입니다.

### 7.1 작동 원리

액션 변경 시 일정 수준 이상의 신뢰도 델타가 필요합니다.

**핵심 개선**: `last_trade_action` 별도 추적
```
기존 문제: BUY → HOLD → SELL 경로가 반전 체크를 우회
해결: HOLD가 아닌 마지막 거래 액션(BUY/SELL)을 별도 추적

예시:
- Cycle 1: BUY 70% → last_trade_action = BUY
- Cycle 2: HOLD 50% → last_trade_action = BUY (유지)
- Cycle 3: SELL 60% → BUY와 비교하여 반전 체크!
```

**스트리밍 모드 설정** (기본값):

| 전환 유형 | 필요 델타 | 설명 |
|----------|----------|------|
| HOLD → BUY/SELL | 0.10 | 새로운 포지션 진입 |
| BUY/SELL → HOLD | 0.15 | 기존 포지션 청산 |
| BUY ↔ SELL | 0.25 | 방향 반전 (가장 높은 임계값) |

### 7.2 시간 감쇠 (Time Decay)

시간이 경과하면 임계값이 점진적으로 감소합니다.

```
required_delta = base_delta × max(0.5, 1.0 - decay_rate × hours)

예시 (hold_to_action_delta = 0.10, decay_rate = 0.15):
- 0시간 경과: 0.10 (100%)
- 2시간 경과: 0.07 (70%)
- 3.3시간 경과: 0.05 (50%, 최소값)
```

### 7.3 긴급 오버라이드

신뢰도가 **85% 이상**이면 Hysteresis를 무시하고 즉시 액션 변경을 허용합니다.

### 7.4 설정 비교

| 설정 | hold_to_action | action_to_hold | reversal | emergency | 용도 |
|------|----------------|----------------|----------|-----------|------|
| streaming | 0.10 | 0.15 | 0.25 | 0.85 | 실시간 스트리밍 |
| backtest_daily | 0.15 | 0.20 | 0.35 | 0.90 | 일봉 백테스트 |
| conservative | 0.20 | 0.25 | 0.45 | 0.95 | 고변동성 시장 |

### 7.5 결정 기록 및 중복 필터링

**소스 파일**: `src/trading/core/decision_history.py`

결정 노이즈를 줄이기 위해 중복 결정을 필터링합니다.

```
┌─────────────────────────────────────────────────────────────────┐
│  중복 결정 판단 기준                                             │
├─────────────────────────────────────────────────────────────────┤
│  다음 조건을 모두 만족하면 중복으로 판단하여 기록 생략:          │
│                                                                  │
│  1. 이전 결정과 동일한 액션 (예: 둘 다 HOLD)                     │
│  2. 이전 결정과 동일한 상태 (예: 둘 다 rejected)                 │
│  3. 실행되지 않음 (was_executed = False)                         │
│                                                                  │
│  항상 기록되는 경우:                                             │
│  - 실행된 결정 (was_executed = True)                             │
│  - 액션 변경 (HOLD → BUY, BUY → SELL 등)                        │
│  - 상태 변경 (pending → rejected 등)                             │
└─────────────────────────────────────────────────────────────────┘

효과:
- Before: 매 사이클마다 동일한 "BUY rejected" 반복 기록
- After:  첫 번째만 기록, 이후 중복은 생략
```

---

## 8. 리스크 검증

**소스 파일**: `src/trading/agents/risk_agent.py`, `src/trading/risk/validator.py`

DecisionAgent의 결정이 실행되기 전에 RiskAgent가 리스크 규칙을 검증합니다.

### 8.1 검증 조건 (순서대로)

| # | 규칙 | 조건 | 기본값 | 실패 시 |
|---|------|------|--------|---------|
| 1 | 킬 스위치 | OFF 상태 | - | 즉시 거부 |
| 2 | HOLD 액션 | action == HOLD | - | 즉시 승인 |
| 3 | 확신도 | confidence ≥ threshold | BUY/SELL: 60% | 거부 |
| 4 | 일일 손실 | daily_loss < max | 3% | BUY 거부, SELL 허용 |
| 5 | **일일 거래 한도** | **buy_count < cap** | **20회/일** | **BUY 거부, SELL 항상 허용** |
| 6 | 포지션 한도 | exposure ≤ max | 50% | 크기 조정 |
| 7 | 최소 주문 | order_amount ≥ min | 5,000 KRW | 특별 처리* |
| 8 | 변동성 | volatility check | - | 크기 50% 축소 |
| 9 | 이상 감지 | anomaly count | - | 경고만 |

### 8.1.1 일일 거래 한도 (Daily Trade Cap)

**소스**: `src/trading/risk/limits.py` (`check_daily_trade_cap`, `get_buy_count_today`)

과도한 거래로 인한 수수료/슬리피지 누적과 과적합을 방지하기 위해 BUY 횟수에 일일 한도를 둡니다.

- **카운트 대상**: `logs/trades_YYYYMMDD.jsonl`에서 status="filled"인 BUY 항목만
- **예외**: SELL과 HOLD는 항상 통과 — 손절 매도가 막히면 손실이 누적되므로 stop-loss 안전성 확보를 위해 의도적으로 면제
- **기본값**: 20회 (settings `MAX_TRADES_PER_DAY`로 조정)
- **카운트 영속화**: 메모리가 아닌 trade log 파일을 읽어 카운트 → 프로세스 재시작에도 카운트 유지

### 8.1.2 자동 손절 (Stop-Loss)

**소스**: `src/trading/agents/decision_agent.py:detect_stop_loss`

DecisionAgent의 가장 첫 단계로 실행되어, 보유 BTC 평가손실이 임계값을 넘으면 hysteresis와 LLM을 모두 우회하여 강제 매도합니다. **Live 관찰에서 hysteresis가 SELL 신호를 4시간 차단해 손실이 누적된 사례**를 방지하기 위해 추가되었습니다.

- **트리거 조건**: `portfolio.unrealized_pnl < -stop_loss_pct` AND `btc_balance > 0`
- **기본값**: `STOP_LOSS_PCT=2.0` (2% 손실 시 발동, 0이면 비활성)
- **동작**: `action=SELL, confidence=0.95, target_position_pct=0%, bypass_hysteresis=True`
- **실행 순서**: rapid_movement, LLM, MTF check **모두 전에** 실행 → 어떤 신호도 stop-loss를 막을 수 없음

### 8.1.3 Decision Hysteresis (진동 방지)

**소스**: `src/trading/core/hysteresis.py`

같은 시점에 BUY↔SELL 반복(flip-flopping)과 무의미한 같은 방향 클러스터를 방지하는 다중 정책. Live 관찰 + Codex 리뷰 기반으로 튜닝됨.

| 정책 | 동작 | streaming 기본값 |
|---|---|---|
| 확신도 델타 | BUY→SELL 시 `new_conf - prev_conf ≥ action_reversal_delta` 요구 | 0.15 (live observation으로 0.25→0.15 하향) |
| Post-trade cooldown | 거래 후 N분 안 reversal 차단 | 15분 |
| **Same-direction cooldown** | BUY→BUY / SELL→SELL 클러스터 차단 (asymmetric) | BUY 15분, SELL 5분 |
| Sizing 강도 완화 | `|delta_pct| ≥ 25%` → required × 0.5 / `≥ 15%` → × 0.7 (multiplier only) | 활성 |
| 누적 차단 카운터 | 30분 내 같은 방향 ≥3회 차단 시 점진적 완화 (0.4x floor) | 활성 |
| Emergency override | confidence ≥ N → 모든 hysteresis 우회 | 0.85 (streaming) |

**Codex 권고 핵심**: Sizing 강도는 multiplier로만 적용 (full bypass는 mediocre SELL이 통과하는 새 failure mode를 만듦).

### 8.2 최소 주문 금액 특별 처리 (SELL)

**중요**: SELL 주문에서 percentage 기반 계산 금액이 최소 주문금액(5,000 KRW) 미만인 경우:

```
┌─────────────────────────────────────────────────────────────────┐
│  SELL 최소 주문금액 검증 로직                                    │
├─────────────────────────────────────────────────────────────────┤
│  1. 매도 금액 계산: trade_amount = size_pct × BTC 가치          │
│                                                                  │
│  2. trade_amount < 5,000 KRW 인 경우:                           │
│     - 전체 BTC 가치 ≥ 5,000 KRW → ✅ 승인 (전량 매도로 전환)    │
│     - 전체 BTC 가치 < 5,000 KRW → ❌ 거부 (매도 불가)           │
│                                                                  │
│  3. trade_amount ≥ 5,000 KRW 인 경우:                           │
│     → ✅ 승인 (요청 크기대로 매도)                               │
└─────────────────────────────────────────────────────────────────┘
```

**예시**:
- BTC 보유량: 0.0004 BTC (약 44,000 KRW 가치)
- 요청: SELL 10% → 4,400 KRW (최소 미만)
- 결과: **전량 매도 승인** (44,000 KRW ≥ 5,000 KRW)

### 8.3 검증 결과

- **approved**: 모든 조건 충족 → 실행 진행
- **rejected**: 하나 이상 조건 미충족 → 실행 중단

```
거부 예시:
- "Rejected: Confidence too low: 0.55 < 0.60"
- "Rejected: Position limit reached: exposure=52.0% >= max=50%"
- "Rejected: Daily loss limit breached: -3.5%"
- "Rejected: Kill switch is active"
- "Rejected: Order too small: 3,500 < 5,000 KRW"
```

---

## 9. 주문 실행

**소스 파일**: `src/trading/agents/execution_agent.py`

### 9.1 Isolated Mode (봇 독립 운영)

Isolated Mode에서는 봇이 거래소 전체 잔액이 아닌 **지정된 자본금 내에서만** 거래합니다.

```
┌─────────────────────────────────────────────────────────────────┐
│  Isolated Mode 특징                                             │
├─────────────────────────────────────────────────────────────────┤
│  • 봇 전용 자본금 설정 (예: 100,000 KRW)                        │
│  • 기존 보유 자산과 완전 분리                                   │
│  • 봇이 매수한 BTC만 매도 가능                                  │
│  • logs/isolated_balance.json에 상태 저장                       │
│  • 재시작 시 이전 상태 복원                                     │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 BUY 실행 로직

```python
# Isolated Mode
available_krw = min(isolated_balance.krw, exchange_krw)
amount_krw = available_krw × (size_pct / 100)

if amount_krw < 5000:
    # 최소 주문금액 미달 → 실행 안함
    return None

# 시장가 매수 실행
order = broker.buy_market_order("KRW-BTC", amount_krw)
```

### 9.3 SELL 실행 로직

```python
# Isolated Mode
sellable_btc = isolated_balance.btc  # 봇이 매수한 BTC만

if sellable_btc <= 0:
    return None  # 매도할 BTC 없음

sell_qty = sellable_btc × (size_pct / 100)
sell_value = sell_qty × market_price
total_value = sellable_btc × market_price

if sell_value < 5000:  # 최소 주문금액 미달
    if total_value >= 5000:
        sell_qty = sellable_btc  # 전량 매도로 전환
    else:
        return None  # 전체 가치도 최소 미만 → 매도 불가

# 시장가 매도 실행
order = broker.sell_market_order("KRW-BTC", sell_qty)
```

### 9.4 주문 상태 확인

Upbit API 특성상 시장가 주문은 `state: "cancel"`로 표시되더라도 실제로 체결될 수 있습니다.

```python
# 주문 체결 확인 로직
if executed_volume > 0 and trades_count > 0:
    status = FILLED  # 실제 체결됨
else:
    status = map_upbit_state(response.state)
```

---

## 10. 포지션 크기 결정

**소스 파일**: `src/trading/agents/decision_agent.py` (`_calculate_size` 메서드)

```python
# 1. 기본 크기 계산 (확신도 기반)
base_size = confidence × 10  # 최대 10%

# 2. 변동성에 따른 조정
if volatility == "high":
    base_size *= 0.5   # 고변동성 시 50% 축소
elif volatility == "low":
    base_size *= 1.2   # 저변동성 시 20% 확대

# 3. 최종 크기 (0% ~ 10% 범위)
final_size = min(10.0, max(0.0, base_size))
```

**예시**:

| 확신도 | 변동성 | 기본 크기 | 조정 후 크기 |
|--------|--------|----------|-------------|
| 0.8 | low | 8% | 9.6% |
| 0.8 | medium | 8% | 8% |
| 0.8 | high | 8% | 4% |
| 0.6 | medium | 6% | 6% |
| 1.0 | high | 10% | 5% |

---

## 11. 판단 예시

### 11.1 BUY 결정 → 승인 → 실행

```
┌─────────────────────────────────────────────────────────────┐
│  상황                                                        │
├─────────────────────────────────────────────────────────────┤
│  현재가: 112,000,000 KRW                                    │
│  추세: bullish, 모멘텀: oversold, RSI: 28                   │
│  펀딩비: -0.005% (숏 과열), L/S=0.6                         │
│  포트폴리오: KRW 56,780 / BTC 0.00039 (노출도 43%)          │
├─────────────────────────────────────────────────────────────┤
│  DecisionAgent                                               │
├─────────────────────────────────────────────────────────────┤
│  액션: BUY                                                  │
│  확신도: 75%                                                 │
│  제안 크기: 7.5%                                            │
├─────────────────────────────────────────────────────────────┤
│  HysteresisManager                                          │
├─────────────────────────────────────────────────────────────┤
│  이전 액션: HOLD (confidence=0.40)                          │
│  delta: 0.75 - 0.40 = 0.35 ≥ 0.10 (hold_to_action)         │
│  결과: ✅ 통과                                              │
├─────────────────────────────────────────────────────────────┤
│  RiskAgent                                                   │
├─────────────────────────────────────────────────────────────┤
│  확신도: 75% ≥ 60% ✅                                       │
│  포지션: 43% + 7.5% = 50.5% → 50%로 조정 ✅                 │
│  주문금액: 50,715 × 7% = 3,550 KRW                          │
│  최소 확인: 3,550 < 5,000 ❌                                 │
│  결과: ❌ rejected (Order too small)                        │
├─────────────────────────────────────────────────────────────┤
│  결론: 주문 금액이 최소 미달로 실행 안됨                     │
└─────────────────────────────────────────────────────────────┘
```

### 11.2 SELL 결정 → 전량 매도 전환 → 실행

```
┌─────────────────────────────────────────────────────────────┐
│  상황                                                        │
├─────────────────────────────────────────────────────────────┤
│  현재가: 112,000,000 KRW                                    │
│  추세: bearish, 모멘텀: overbought, RSI: 72                 │
│  포트폴리오: KRW 6,780 / BTC 0.00039 (약 44,000 KRW)        │
├─────────────────────────────────────────────────────────────┤
│  DecisionAgent                                               │
├─────────────────────────────────────────────────────────────┤
│  액션: SELL                                                 │
│  확신도: 70%                                                 │
│  제안 크기: 8.4%                                            │
├─────────────────────────────────────────────────────────────┤
│  HysteresisManager                                          │
├─────────────────────────────────────────────────────────────┤
│  이전 액션: HOLD (confidence=0.40)                          │
│  delta: 0.70 - 0.40 = 0.30 ≥ 0.10 (hold_to_action)         │
│  결과: ✅ 통과                                              │
├─────────────────────────────────────────────────────────────┤
│  RiskAgent                                                   │
├─────────────────────────────────────────────────────────────┤
│  확신도: 70% ≥ 60% ✅                                       │
│  매도 금액: 44,000 × 8.4% = 3,696 KRW                       │
│  최소 확인: 3,696 < 5,000                                   │
│  BUT: 전체 BTC 가치 44,000 ≥ 5,000 → 전량 매도 승인 ✅      │
│  결과: ✅ approved (전량 매도로 전환)                       │
├─────────────────────────────────────────────────────────────┤
│  ExecutionAgent                                              │
├─────────────────────────────────────────────────────────────┤
│  매도 수량: 0.00039 BTC (전량)                              │
│  예상 금액: ~44,000 KRW                                     │
│  결과: ✅ 체결                                              │
└─────────────────────────────────────────────────────────────┘
```

### 11.3 SELL 결정 → Hysteresis 차단

```
┌─────────────────────────────────────────────────────────────┐
│  상황                                                        │
├─────────────────────────────────────────────────────────────┤
│  이전 액션: BUY (confidence=0.80)                           │
│  새 액션: SELL (confidence=0.70)                            │
├─────────────────────────────────────────────────────────────┤
│  HysteresisManager                                          │
├─────────────────────────────────────────────────────────────┤
│  delta: 0.70 - 0.80 = -0.10                                 │
│  필요 delta: 0.25 (BUY ↔ SELL 반전)                        │
│  -0.10 < 0.25 → ❌ 차단                                     │
│                                                             │
│  결과: BUY 유지 (SELL 차단됨)                               │
│  rationale: "[Hysteresis] Maintaining BUY. Original: ..."   │
└─────────────────────────────────────────────────────────────┘
```

### 11.4 포지션 인식 결정 (신규)

```
┌─────────────────────────────────────────────────────────────┐
│  상황 (이미 상당 부분 투자됨)                                 │
├─────────────────────────────────────────────────────────────┤
│  현재가: 102,000,000 KRW                                    │
│  추세: bullish, 모멘텀: oversold, RSI: 35                   │
│  포트폴리오: KRW 64,000 / BTC 0.00132 (~135,000 KRW)        │
│  노출도: 68% (= 135,000 / 199,000)                          │
├─────────────────────────────────────────────────────────────┤
│  DecisionAgent (포지션 인식 로직)                            │
├─────────────────────────────────────────────────────────────┤
│  bullish_signals = 3 (추세 + 모멘텀 + RSI)                  │
│                                                             │
│  포지션 체크:                                                │
│  - can_buy = (64,000 > 5,000) and (68% < 90%) = True       │
│  - BUT: 실제 주문 시 size 계산 후 최소 금액 미달 가능       │
│                                                             │
│  LLM 컨텍스트 (프롬프트에 포함):                             │
│  - Exposure: 68% ← "이미 상당 부분 투자됨" 인식             │
│  - Recent Decision: BUY 70% rejected (order too small)     │
│  - Guidance: "If Exposure > 80%: prefer HOLD"              │
├─────────────────────────────────────────────────────────────┤
│  LLM 결정 (개선 후)                                         │
├─────────────────────────────────────────────────────────────┤
│  액션: HOLD (기존: BUY)                                     │
│  확신도: 50%                                                 │
│  rationale: "상승 신호가 있지만, 이미 68% 노출되어 있어      │
│             추가 매수보다 관망이 적절합니다."                │
├─────────────────────────────────────────────────────────────┤
│  결과: ✅ 의미있는 HOLD 결정 (불필요한 BUY rejected 방지)   │
└─────────────────────────────────────────────────────────────┘
```

---

## 부록: 관련 파일 경로

| 모듈 | 파일 경로 |
|------|----------|
| 시장 데이터 수집 | `src/trading/agents/market_agent.py` |
| 기술적 지표 계산 | `src/trading/agents/indicator_agent.py` |
| 차트 패턴 인식 (Vision LLM) | `src/trading/agents/pattern_agent.py` |
| 의사결정 | `src/trading/agents/decision_agent.py` |
| 리스크 검증 | `src/trading/agents/risk_agent.py`, `src/trading/risk/validator.py` |
| 리스크 한도 | `src/trading/risk/limits.py` |
| 주문 실행 | `src/trading/agents/execution_agent.py` |
| 알림 발송 | `src/trading/agents/ops_agent.py` |
| 추세 지표 | `src/trading/indicators/trend.py` |
| 모멘텀 지표 | `src/trading/indicators/momentum.py` |
| 변동성 지표 | `src/trading/indicators/volatility.py` |
| 이상 감지 (폴링) | `src/trading/core/anomaly.py` |
| 이상 감지 (스트리밍) | `src/trading/triggers/evaluator.py` |
| Hysteresis (진동 방지) | `src/trading/core/hysteresis.py` |
| 결정 기록 및 필터링 | `src/trading/core/decision_history.py` |
| Isolated Balance | `src/trading/core/isolated_balance.py` |
| LLM 프롬프트 | `src/trading/llm/prompts.py` |
| 설정 | `src/trading/config.py` |
| **파생상품 데이터 수집** | `src/trading/adapters/binance_futures.py` |
| **파생상품 모델** | `src/trading/core/models.py` |
| **파생상품 히스토리 기록** | `src/trading/history/derivatives_writer.py` |
| **파생상품 히스토리 조회** | `src/trading/history/reader.py` |
| **대시보드 차트** | `src/trading/dashboard/charts.py` |
| **대시보드 다국어** | `src/trading/dashboard/i18n.py` |
| 백테스트 결과 | `docs/BACKTEST_RESULTS.md` |
