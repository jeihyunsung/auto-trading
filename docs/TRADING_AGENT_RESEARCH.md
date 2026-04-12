# 암호화폐 트레이딩 에이전트 연구

> 최종 업데이트: 2026-02-15

## 목차

1. [개요](#개요)
2. [멀티 에이전트 시스템](#멀티-에이전트-시스템)
3. [기술적 지표](#기술적-지표)
4. [머신러닝 접근법](#머신러닝-접근법)
5. [강화학습 (DRL)](#강화학습-drl)
6. [감성 분석](#감성-분석)
7. [리스크 관리](#리스크-관리)
8. [현재 봇 개선 방향](#현재-봇-개선-방향)
9. [참고 자료](#참고-자료)

---

## 개요

암호화폐 트레이딩 봇은 크게 세 가지 패러다임으로 발전해왔습니다:

| 세대 | 접근법 | 특징 |
|------|--------|------|
| 1세대 | Rule-based | 고정된 규칙 (예: RSI < 30 → 매수) |
| 2세대 | ML/DRL | 데이터 기반 학습, 패턴 인식 |
| 3세대 | LLM Multi-Agent | 자연어 추론, 역할 분담, 협업 |

2025년 기준 AI가 전 세계 트레이딩 볼륨의 89%를 처리하고 있으며, 강화학습이 주요 기술로 부상하고 있습니다.

---

## 멀티 에이전트 시스템

### TradingAgents Framework

[TradingAgents](https://github.com/TauricResearch/TradingAgents)는 실제 트레이딩 회사 구조를 모방한 LLM 기반 멀티 에이전트 프레임워크입니다.

#### 에이전트 역할 구성

```
┌─────────────────────────────────────────────────────────────┐
│                      TRADING FIRM                           │
├─────────────────────────────────────────────────────────────┤
│  📊 Analysts                                                │
│  ├── Fundamentals Analyst (재무제표, 밸류에이션)            │
│  ├── Technical Analyst (차트, 지표)                         │
│  ├── Sentiment Analyst (소셜미디어, 뉴스 감성)              │
│  └── News Analyst (뉴스 이벤트, 규제)                       │
├─────────────────────────────────────────────────────────────┤
│  🔬 Researchers                                             │
│  ├── Bull Researcher (강세 논거 수집)                       │
│  └── Bear Researcher (약세 논거 수집)                       │
├─────────────────────────────────────────────────────────────┤
│  💼 Execution                                               │
│  ├── Trader (최종 결정, 다양한 리스크 프로필)               │
│  └── Risk Manager (노출도, 손실 한도 관리)                  │
└─────────────────────────────────────────────────────────────┘
```

#### 기술 스택

- **LangGraph**: 유연하고 모듈화된 에이전트 오케스트레이션
- **LLM 선택**: 작업별 최적화
  - 빠른 사고: 데이터 검색용 (GPT-4o-mini)
  - 깊은 사고: 분석 및 결정용 (GPT-4o, Claude)

#### 성능 결과

베이스라인 대비 개선:
- 누적 수익률 ↑
- 샤프 비율 ↑
- 최대 낙폭 ↓

### TradingGroup (2025)

[TradingGroup](https://arxiv.org/html/2508.17565v1)은 자기 반성(self-reflection) 모듈을 통합한 최신 시스템입니다.

**핵심 특징:**
- 거래 결정, 가격 예측, 스타일 선호 에이전트에 자기 반성 통합
- 동적 리스크 관리 모듈
- 자동 데이터 합성 및 주석 파이프라인

### 현재 봇과의 비교

| 항목 | 현재 봇 | TradingAgents | 개선 방향 |
|------|---------|---------------|-----------|
| 에이전트 수 | 6개 | 7개+ | 유사 |
| 역할 분리 | 기능별 | 역할별 | Bull/Bear 연구원 추가 고려 |
| 토론 메커니즘 | 없음 | 있음 | 다관점 분석 추가 |
| 자기 반성 | 없음 | 있음 | Reflection 노드 추가 |

---

## 기술적 지표

### 핵심 지표 비교

| 지표 | 유형 | 최적 시장 | 현재 봇 |
|------|------|-----------|---------|
| RSI (14) | 모멘텀 | 횡보장 | ✅ 사용 |
| MACD | 추세+모멘텀 | 추세장 | ✅ 사용 |
| Bollinger Bands | 변동성 | 돌파 감지 | ❌ 미사용 |
| Stochastic | 모멘텀 | 단기 반전 | ❌ 미사용 |
| OBV | 거래량 | 추세 확인 | ❌ 미사용 |
| VWAP | 가격/거래량 | 일중 거래 | ❌ 미사용 |
| Aroon | 추세 | 추세 전환 | ❌ 미사용 |

### 지표 조합 효과

연구에 따르면 MACD, RSI, KDJ, Bollinger Bands를 전략적으로 조합하면 **약 85%의 시장 추세 신호가 일치**합니다.

**효과적인 조합:**
- RSI + MACD: 추세 확인
- Bollinger Bands + 거래량 지표: 돌파 감지
- EMA + Fibonacci: 스윙 트레이딩

**피해야 할 조합:**
- RSI + Stochastic (유사한 데이터 중복)

### RSI 기간 설정

| 기간 | 특징 | 사용 사례 |
|------|------|-----------|
| 7일 | 민감, 신호 많음, 거짓 신호 증가 | 스캘핑, 단기 |
| **14일** | 균형 (표준) | 일반 트레이딩 |
| 21일 | 안정적, 늦은 반응 | 스윙, 포지션 |

암호화폐는 24/7 거래되므로 일부 트레이더는 7~10일을 선호합니다.

---

## 머신러닝 접근법

### 주요 알고리즘

| 알고리즘 | 용도 | 장점 | 단점 |
|----------|------|------|------|
| **Random Forest** | 분류/회귀 | 과적합 방지, 해석 가능 | 실시간 적응 어려움 |
| **XGBoost** | 특징 기반 예측 | 빠른 학습, 정확도 높음 | 시계열 특성 약함 |
| **LSTM** | 시계열 예측 | 장기 패턴 학습 | 학습 시간 김 |
| **Transformer** | 복잡한 패턴 | SOTA 성능 | 많은 데이터 필요 |

### 특징 엔지니어링

[Intelligent Trading Bot](https://github.com/asavinov/intelligent-trading-bot) 프로젝트의 접근:

```python
# 주요 특징 카테고리
features = {
    "price": ["open", "high", "low", "close", "volume"],
    "technical": ["rsi", "macd", "bb_upper", "bb_lower", "atr"],
    "derived": ["returns_1h", "returns_24h", "volatility"],
    "market": ["btc_dominance", "total_market_cap"],
    "sentiment": ["news_score", "social_volume"],
}
```

### 주요 리스크

1. **과적합 (Overfitting)**: 과거 데이터에 과도하게 최적화
2. **모델 드리프트 (Model Drift)**: 시장 변화에 따른 성능 저하
3. **데이터 품질**: 잡음이 많은 데이터
4. **비현실적 백테스트**: 슬리피지, 수수료 미반영

**해결책:**
- 정기적 모델 재학습
- Out-of-sample 검증
- 앙상블 방법 사용
- 롤링 학습/테스트 윈도우

---

## 강화학습 (DRL)

### 알고리즘 비교

| 알고리즘 | 특징 | 성능 | 사용 사례 |
|----------|------|------|-----------|
| **PPO** | 안정적 정책 업데이트 | 누적수익 +24% (vs TD3, SAC) | 범용, 포트폴리오 관리 |
| **A3C** | 병렬 에이전트 | 빠른 학습 | 다중 페어 거래, 차익거래 |
| **DQN** | 이산적 행동 | 기본 성능 | 단순 매수/매도/홀드 |
| **DDPG** | 연속적 행동 | 중간 | 포지션 사이징 |
| **TD3** | DDPG 개선 | 안정적 | 노이즈가 많은 환경 |
| **SAC** | 엔트로피 최대화 | 탐색 우수 | 불확실한 환경 |

### PPO가 2025년 선호되는 이유

1. 정책 업데이트 제한으로 치명적 성능 저하 방지
2. 탐색과 안정적 개선의 균형
3. 연속적 행동 공간에 적합 (포지션 사이징)

### 프레임워크

| 프레임워크 | 특징 |
|------------|------|
| [FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 금융 특화, DQN/DDPG/PPO/TD3/SAC 통합 |
| [Stable-Baselines3](https://github.com/DLR-RM/stable-baselines3) | PyTorch 기반, 프로덕션 준비 |
| [RLlib](https://docs.ray.io/en/latest/rllib/index.html) | 분산 학습, 확장성 |

### 2025년 11월 실적 예시

> 시장 붕괴 시 멀티 에이전트 RL이 +4.7% 수익을 기록한 반면, 시장은 -11% 하락

### 베스트 프랙티스

1. **항상 거래 비용/슬리피지 모델링**
2. 롤링 학습/테스트 윈도우 사용
3. 과도하게 표현력 있는 에이전트 정규화
4. 랜덤 및 결정론적 베이스라인과 비교

---

## 감성 분석

### LLM 기반 접근

| 모델 | 성능 | 특징 |
|------|------|------|
| **Gemini-2.5-pro** | 예측 1위 | 분 단위 해상도 |
| **GPT-4** (fine-tuned) | 높은 정확도 | 파인튜닝 후 성능 향상 |
| **FinBERT** | 금융 특화 | 빠른 추론 |
| **BERT** | 범용 | 기본 성능 |

### 데이터 소스

1. **뉴스**: Reuters, Bloomberg, CoinDesk
2. **소셜 미디어**: Twitter/X, Reddit
3. **온체인 데이터**: 대규모 지갑 이동, 거래소 유입/유출

### 감성-포트폴리오 통합

[Sentiment-Aware Mean-Variance Portfolio](https://arxiv.org/pdf/2508.16378) 연구:

```
Expected Return = Base Return × (1 + Sentiment Score × Weight)
```

**결과:**
- 텍스트 데이터 통합 시 정확도 향상
- 수익성 및 샤프 비율 개선

### 도구

| 도구 | 용도 |
|------|------|
| NLTK, SpaCy | 텍스트 전처리 |
| TextBlob | 간단한 감성 분석 |
| Hugging Face Transformers | BERT, GPT 활용 |
| [LunarCrush](https://lunarcrush.com/) | 소셜 미디어 감성 API |

---

## 리스크 관리

### 핵심 지표

| 지표 | 설명 | 목표 |
|------|------|------|
| **Maximum Drawdown** | 최대 낙폭 | < 20% |
| **Sharpe Ratio** | 위험 조정 수익 | > 1.5 |
| **Sortino Ratio** | 하방 위험만 고려 | > 2.0 |
| **CVaR (Conditional VaR)** | 극단적 손실 예상치 | 최소화 |
| **Win Rate** | 승률 | > 50% |

### 포지션 사이징 전략

| 전략 | 공식 | 특징 |
|------|------|------|
| **Fixed Fractional** | Position = Capital × Fixed% | 간단 |
| **Kelly Criterion** | f* = (p×b - q) / b | 수학적 최적 |
| **Volatility-Based** | Position ∝ 1/Volatility | 변동성 조절 |

### 현재 봇의 리스크 관리

```python
# 현재 구현
- 일일 손실 한도 (kill switch)
- 포지션 한도
- 최소 주문 금액 (5,000 KRW)
- Hysteresis (급격한 방향 전환 방지)
```

### 개선 가능 영역

1. **동적 포지션 사이징**: 변동성 기반
2. **CVaR 통합**: 극단적 손실 관리
3. **상관관계 분석**: 다중 자산 시 분산화

---

## 현재 봇 개선 방향

### 단기 (1-2주)

| 항목 | 현재 | 개선 | 난이도 |
|------|------|------|--------|
| Bollinger Bands 추가 | ❌ | ✅ | 낮음 |
| OBV (거래량) 추가 | ❌ | ✅ | 낮음 |
| 변동성 기반 포지션 사이징 | ❌ | ✅ | 중간 |

### 중기 (1-2개월)

| 항목 | 설명 | 난이도 |
|------|------|--------|
| Bull/Bear 연구원 에이전트 | 다관점 분석 | 중간 |
| Self-Reflection 노드 | 결정 검토 | 중간 |
| FinBERT 감성 분석 | 뉴스 고도화 | 중간 |

### 장기 (3개월+)

| 항목 | 설명 | 난이도 |
|------|------|--------|
| PPO 강화학습 에이전트 | 학습 기반 결정 | 높음 |
| 온체인 데이터 통합 | 대형 지갑 추적 | 높음 |
| 백테스팅 프레임워크 | 전략 검증 | 중간 |

---

## 참고 자료

### 학술 논문

- [TradingAgents: Multi-Agents LLM Financial Trading Framework](https://arxiv.org/abs/2412.20138)
- [TradingGroup: A Multi-Agent Trading System with Self-Reflection](https://arxiv.org/html/2508.17565v1)
- [LLMs and NLP Models in Cryptocurrency Sentiment Analysis](https://www.mdpi.com/2504-2289/8/6/63)
- [Deep Reinforcement Learning for Crypto Trading](https://link.springer.com/article/10.1007/s00521-023-08516-x)

### 오픈소스 프로젝트

- [TradingAgents (GitHub)](https://github.com/TauricResearch/TradingAgents) - LLM 멀티에이전트
- [Freqtrade](https://github.com/freqtrade/freqtrade) - 오픈소스 트레이딩 봇
- [FinRL](https://github.com/AI4Finance-Foundation/FinRL) - 강화학습 금융
- [Intelligent Trading Bot](https://github.com/asavinov/intelligent-trading-bot) - ML 트레이딩

### 가이드 및 튜토리얼

- [Understanding Machine Learning in Crypto Trading (3commas)](https://3commas.io/blog/understanding-machine-learning-algorithms-in-crypt)
- [Algorithmic Crypto Trading Guide (Zignaly)](https://zignaly.com/crypto-trading/algorithmic-strategies/algorithmic-crypto-trading)
- [Best Trading Indicators for Crypto in 2025](https://cryptomania.win/blog/trading-lessons/7-best-trading-indicators-indicators-for-crypto-in-2025/)
- [MACD vs RSI Comparison (Altrady)](https://www.altrady.com/blog/crypto-trading-strategies/macd-trading-strategy-macd-vs-rsi)

---

## 부록: 현재 봇 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                    AUTO-TRADING BOT                         │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Event-Driven (No LLM Cost)                        │
│  ├── WebSocket Stream (실시간 가격/거래량)                   │
│  ├── Trigger Evaluator (규칙 기반 조건)                     │
│  └── Event Dispatcher (배칭, 쿨다운)                        │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: LLM Pipeline (조건 충족 시)                       │
│  ├── Market Agent (시장 데이터 수집)                        │
│  ├── News Agent (뉴스 감성 분석)                            │
│  ├── Indicator Agent (기술적 지표: RSI, MACD)               │
│  ├── Decision Agent (LLM 판단 + Hysteresis)                 │
│  ├── Risk Agent (리스크 검증)                               │
│  ├── Execution Agent (주문 실행)                            │
│  └── Ops Agent (알림, 기록)                                 │
└─────────────────────────────────────────────────────────────┘
```
