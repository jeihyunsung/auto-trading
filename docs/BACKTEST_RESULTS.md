# 백테스트 결과 분석

## 개요

이 문서는 트레이딩 봇의 규칙 기반 전략에 대한 백테스트 결과를 정리합니다.
다양한 시간 인터벌과 Hysteresis 설정에 따른 성과를 비교 분석했습니다.

**테스트 환경**
- 테스트 일자: 2026-02-02
- 초기 자본: 10,000,000 KRW
- 수수료율: 0.05%
- 슬리피지: 0.1%
- 전략: 규칙 기반 (RSI + 트렌드 + 모멘텀)

---

## 1. Hysteresis란?

Hysteresis는 의사결정의 진동(oscillation)을 방지하는 로직입니다.

### 작동 원리

| 전환 유형 | 필요 신뢰도 델타 |
|----------|-----------------|
| HOLD → BUY/SELL | 0.15 |
| BUY/SELL → HOLD | 0.20 |
| BUY ↔ SELL (반전) | 0.35 |

### 주요 기능

- **시간 감쇠(Time Decay)**: 시간이 지나면 임계값이 점진적으로 감소
- **긴급 오버라이드**: 신뢰도 90% 이상이면 즉시 전환 허용
- **반전 차단**: BUY↔SELL 급반전 방지

---

## 2. 인터벌별 백테스트 결과

### 2.1 15분봉 (7일간)

| 지표 | Hysteresis OFF | Hysteresis ON | 차이 |
|------|----------------|---------------|------|
| 총 거래 | 236회 | 225회 | -11회 |
| 총 수익률 | -14.28% | -16.18% | -1.9%p |
| Buy & Hold | -19.52% | -19.41% | - |
| **알파** | **+5.24%** | +3.24% | **-2.0%p** |
| 승률 | 11.6% | 0.0% | -11.6%p |
| 최대 낙폭 | 14.39% | 17.15% | +2.76%p |

**결론**: 15분봉에서는 Hysteresis **OFF** 권장

---

### 2.2 1시간봉 (14일간)

| 지표 | Hysteresis OFF | Hysteresis ON | 차이 |
|------|----------------|---------------|------|
| 총 거래 | 328회 | 328회 | 0 |
| 총 수익률 | -17.72% | -17.98% | -0.26%p |
| Buy & Hold | -21.53% | -21.62% | - |
| **알파** | **+3.81%** | +3.64% | **-0.17%p** |
| 승률 | 65.5% | 61.4% | -4.1%p |
| 손익비 | 2.73 | 2.02 | -0.71 |
| 최대 낙폭 | 18.52% | 19.21% | +0.69%p |

**결론**: 1시간봉에서는 Hysteresis **OFF** 권장

---

### 2.3 4시간봉 (30일간)

| 지표 | Hysteresis OFF | Hysteresis ON | 차이 |
|------|----------------|---------------|------|
| 총 거래 | 357회 | 348회 | -9회 |
| 총 수익률 | -8.79% | **+2.78%** | **+11.57%p** |
| Buy & Hold | -6.16% | -6.20% | - |
| **알파** | -2.63% | **+8.98%** | **+11.61%p** |
| 승률 | 66.3% | **78.6%** | +12.3%p |
| 손익비 | 1.08 | **4.80** | +3.72 |
| 최대 낙폭 | 24.36% | **17.75%** | -6.61%p |

**결론**: 4시간봉에서는 Hysteresis **ON** 강력 권장

---

### 2.4 일봉 (90일간)

| 지표 | Hysteresis OFF | Hysteresis ON | 차이 |
|------|----------------|---------------|------|
| 총 거래 | 28회 | 22회 | -6회 |
| 총 수익률 | -8.88% | **-5.13%** | **+3.75%p** |
| Buy & Hold | -26.41% | -26.71% | - |
| **알파** | +17.53% | **+21.58%** | **+4.05%p** |
| 승률 | 0.0% | **66.7%** | +66.7%p |
| 손익비 | 0.00 | **3.25** | +3.25 |
| 최대 낙폭 | 9.56% | **8.19%** | -1.37%p |

**결론**: 일봉에서는 Hysteresis **ON** 권장

---

## 3. 종합 비교

### 3.1 알파 변화 요약

| 인터벌 | Hysteresis OFF | Hysteresis ON | 알파 변화 | 권장 설정 |
|--------|----------------|---------------|----------|----------|
| 15분봉 | +5.24% | +3.24% | -2.0%p | **OFF** |
| 1시간봉 | +3.81% | +3.64% | -0.17%p | **OFF** |
| 4시간봉 | -2.63% | +8.98% | +11.61%p | **ON** |
| 일봉 | +17.53% | +21.58% | +4.05%p | **ON** |

### 3.2 최적 설정 가이드

```
┌─────────────────────────────────────────────────────────────┐
│                    Hysteresis 설정 가이드                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   단기 트레이딩 (15분 ~ 1시간)                               │
│   └── Hysteresis: OFF                                       │
│   └── 이유: 빠른 시장 대응이 수익에 유리                      │
│                                                             │
│   중장기 트레이딩 (4시간 ~ 일봉)                              │
│   └── Hysteresis: ON                                        │
│   └── 이유: 노이즈 필터링으로 안정적 수익                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 인터벌별 특성

| 인터벌 | 거래 빈도 | 노이즈 민감도 | Hysteresis 효과 |
|--------|----------|--------------|----------------|
| 15분봉 | 매우 높음 | 매우 높음 | 부정적 |
| 1시간봉 | 높음 | 높음 | 중립 |
| 4시간봉 | 중간 | 중간 | **매우 긍정적** |
| 일봉 | 낮음 | 낮음 | 긍정적 |

---

## 4. 핵심 인사이트

### 4.1 Hysteresis가 효과적인 이유 (중장기)

1. **노이즈 필터링**: 일시적 변동에 의한 잘못된 신호 차단
2. **반전 방지**: BUY→SELL 급반전으로 인한 손실 방지
3. **거래 비용 절감**: 불필요한 거래 감소
4. **심리적 안정**: 일관된 포지션 유지

### 4.2 Hysteresis가 비효과적인 이유 (단기)

1. **기회 손실**: 빠른 시장 변화에 대응 지연
2. **과도한 차단**: 유효한 신호까지 필터링
3. **트렌드 추종 실패**: 짧은 트렌드를 놓침

### 4.3 4시간봉이 최적인 이유

- **균형점**: 노이즈 필터링과 시장 대응의 최적 균형
- **알파 극대화**: +11.61%p 알파 개선 (가장 큰 효과)
- **리스크 감소**: MDD 24.36% → 17.75% (-6.61%p)
- **손익비 극대화**: 1.08 → 4.80 (4.4배 향상)

---

## 5. 권장 운영 설정

### 5.1 프로덕션 설정

```python
# 4시간봉 + Hysteresis ON (권장)
BacktestConfig(
    initial_capital_krw=10_000_000,
    fee_rate=0.0005,
    slippage_rate=0.001,
    use_llm=False,
    use_hysteresis=True,  # 4시간봉 이상에서 ON
    confidence_threshold=0.5,
    max_position_pct=50.0,
)
```

### 5.2 Hysteresis 설정

```python
# 프리셋 사용 (권장)
from trading.core.hysteresis import HysteresisConfig

# 스트리밍 모드 (WebSocket 실시간)
config = HysteresisConfig.streaming()

# 일봉 백테스트
config = HysteresisConfig.backtest_daily()

# 보수적 설정 (고변동성 시장)
config = HysteresisConfig.conservative()
```

#### 프리셋별 임계값

| 프리셋 | HOLD→액션 | 액션→HOLD | 반전 | 긴급 오버라이드 |
|--------|----------|----------|------|----------------|
| **streaming** | 0.10 | 0.15 | 0.25 | 85% |
| **daily** | 0.15 | 0.20 | 0.35 | 90% |
| **conservative** | 0.20 | 0.25 | 0.45 | 95% |

---

## 6. 스트리밍 모드 실행 방법

WebSocket 기반 실시간 트레이딩 봇 실행:

```bash
# 기본 실행 (Hysteresis ON, streaming 프리셋)
python -m trading.main_async --symbols KRW-BTC

# Hysteresis 모드 지정
python -m trading.main_async --hysteresis-mode streaming   # 빠른 대응
python -m trading.main_async --hysteresis-mode daily       # 중간
python -m trading.main_async --hysteresis-mode conservative # 보수적

# Hysteresis 비활성화
python -m trading.main_async --no-hysteresis

# 전체 옵션
python -m trading.main_async \
    --symbols KRW-BTC \
    --cooldown 60 \
    --batch-window 10 \
    --hysteresis \
    --hysteresis-mode streaming \
    --log-level INFO
```

### 환경 변수 (.env)

```bash
# Hysteresis 설정
HYSTERESIS_ENABLED=true
HYSTERESIS_MODE=streaming  # streaming, daily, conservative
```

---

## 7. 백테스트 실행 방법

```bash
# 기본 실행 (일봉, 90일)
trading-backtest --days 90 --interval day

# 4시간봉 + Hysteresis (권장)
trading-backtest --days 30 --interval minute240 --hysteresis

# 15분봉 (단기 테스트)
trading-backtest --days 7 --interval minute15

# 전체 옵션
trading-backtest \
    --symbol KRW-BTC \
    --days 90 \
    --interval day \
    --capital 10000000 \
    --hysteresis \
    --confidence-threshold 0.5 \
    --max-position 50
```

---

## 8. 생성 파일

백테스트 실행 시 `backtest_results/` 디렉토리에 다음 파일들이 생성됩니다:

| 파일 | 설명 |
|------|------|
| `*_summary.txt` | 텍스트 요약 리포트 |
| `*_trades.csv` | 거래 내역 CSV |
| `*_portfolio.csv` | 포트폴리오 히스토리 CSV |
| `*_decisions.json` | 모든 의사결정 JSON |
| `*_report.json` | 전체 리포트 JSON |

---

## 9. 향후 개선 사항

1. **LLM 모드 테스트**: 규칙 기반 vs LLM 비교
2. **다양한 시장 조건**: 상승장/하락장/횡보장 별도 분석
3. **파라미터 최적화**: Hysteresis 임계값 튜닝
4. **멀티 심볼**: BTC 외 다른 코인 테스트

---

*마지막 업데이트: 2026-02-02*
