# LLM 기반 자동 투자 Agent 개발 계획 (BTC → 멀티자산 확장)

> 주의: 아래 내용은 **소프트웨어/아키텍처 설계 관점**의 제안이며, 특정 매매를 권유하거나 수익을 보장하지 않습니다. 실거래는 큰 손실 위험이 있으며, 반드시 소액/페이퍼 트레이딩부터 시작하고, 규제·세금·거래소 약관 준수를 전제로 하세요.

---

## 1) 목표와 핵심 요구사항

### 목표
- **실시간 뉴스 + 가격/차트 데이터**를 근거로 거래 여부를 판단하는 **반응형(reactive) 투자 Agent**
- 초기 투자 대상: **비트코인(BTC)**
- 추후 확장: **주식/ETF/부동산(간접상품 등)** 등 다른 플랫폼/자산군

### 핵심 요구사항
- **거래소 API 연동** (주문, 잔고, 포지션, 체결 조회)
- **실시간 데이터 파이프라인** (뉴스 스트림, 시세/캔들)
- **지표 계산/신호 생성** (기술적 지표, 변동성/추세/모멘텀 등)
- **의사결정(LLM + 규칙/모델 혼합)**: “거래/보류/리스크 축소”를 판단
- **안전장치** (손실 제한, 주문 안전성, 장애/네트워크/레이트리밋 대응)
- **관측가능성** (로그/추적, 리플레이, 성능 평가, 알림)

---

## 2) Sub-agent 설계: 현재 구성 + 추가 권장 역할

현재 제안된 역할:
1. **News Agent**: 실시간 뉴스 스크래핑/정리/요약/감성/이슈 태깅  
2. **Chart/Indicator Agent**: 차트 모니터링 + 지표 계산

추가 권장 sub-agent (강력 추천):
3. **Market Data Agent (수집/정규화 전담)**  
   - 거래소별/자산별로 시세·오더북·캔들·펀딩비(선물) 등을 받아 **표준 스키마로 정규화**  
   - 지표 계산/의사결정 모듈이 데이터 소스에 덜 의존하도록 분리

4. **Risk Manager Agent (리스크/포지션 관리)**  
   - 포지션 사이즈 결정(예: 변동성 기반 sizing), 레버리지 제한, 최대 손실/일일 손실 한도  
   - “신호가 BUY라도 리스크 규칙을 통과 못하면 거래 금지” 같은 **게이트키퍼 역할**

5. **Execution Agent (주문 집행/체결/슬리피지 관리)**  
   - 주문 타입 선택(Market/Limit), 분할주문(TWAP/VWAP 단순화), 재시도, 레이트리밋/오류 처리  
   - 주문 전후로 잔고/포지션/주문 상태를 확인하고 **idempotency**(중복 주문 방지) 보장

6. **Policy/Compliance Agent (규정/약관/내부정책 준수)**  
   - API 키 보호, 접근통제, 거래소 약관/지역 규제 체크리스트, 로그 보관 정책  
   - (멀티자산 확장 시) 시장별 거래 가능 시간, 공시/뉴스 사용 제한 등 정책 반영

7. **Memory & Research Agent (지식/상태 관리)**  
   - 과거 뉴스/이슈 → 가격 반응 패턴 저장(임베딩/요약), 전략 변경 히스토리 관리  
   - “이번 FOMC/ETF 승인 루머처럼 반복되는 이벤트”를 구조화해서 회상

8. **Evaluator/Backtest Agent (오프라인 평가/리플레이)**  
   - 과거 데이터 리플레이로 전략 점검, 최근 N일 드리프트 감지  
   - 실거래 전/후 A/B, 파라미터 스윕, 성능 리포트 생성

9. **Ops/Alert Agent (운영/알림)**  
   - 장애 감지(데이터 끊김, 주문 실패), 슬랙/이메일/문자 알림  
   - “수동 중지/비상청산” 같은 킬스위치 제어(사람-in-the-loop)

> 최소 구성(MVP) 추천: **News + Indicator + Risk + Execution + Ops(간단 알림)**

---

## 3) 기본 동작 구조 (Event-driven)

### 이벤트 종류
- `NEWS_UPDATE`: 새 기사/속보 수집
- `MARKET_TICK`: 시세/캔들 갱신(예: 1m, 5m)
- `SCHEDULED_CHECK`: 주기적 점검(리스크/포지션/드리프트)
- `ORDER_UPDATE`: 체결/미체결/거부 등 주문 상태 변경
- `FAILURE_EVENT`: API 오류, 레이트리밋, 데이터 지연 등

### 의사결정 파이프라인(한 사이클)
1. **데이터 수집**: News Agent, Market Data Agent
2. **특징 추출**: Indicator Agent(지표), News Agent(이슈/감성/중요도)
3. **시그널 생성**: Strategy/Decision 단계(LLM + 규칙/모델)
4. **리스크 게이트**: Risk Manager가 포지션/손실/한도 체크
5. **주문 집행**: Execution Agent가 주문 생성/관리
6. **사후 기록**: 모든 입력/출력/근거를 저장(리플레이 가능)
7. **알림/감시**: Ops Agent가 상태를 모니터링

---

## 4) LLM을 어디에 쓰는 게 좋은가 (권장 패턴)

LLM은 “수치 계산”보다는 “텍스트 이해/추론/설명/정책 적용”에 강점이 있습니다. 아래처럼 **역할을 제한**하면 안정성이 올라갑니다.

### (A) 뉴스 이해/정리
- 기사 요약, 중복 제거, 루머/확정 구분, 중요도 스코어링(근거 포함)
- 이슈 분류(ETF, 규제, 해킹, 매크로, 거래소 이슈 등)
- “이 뉴스가 BTC에 미칠 가능성 있는 방향”을 **확률/시나리오**로 정리하되, **매매 실행은 별도 게이트**

### (B) 규칙 기반/모델 기반 신호에 대한 ‘해석 계층’
- 기술적 지표 신호(예: 추세/모멘텀/변동성)를 입력으로 받아
  - “충돌 신호가 있으면 보류”
  - “뉴스가 high-impact이면 포지션 규모 축소”
  - “확률 낮으면 관망”
- 단, **최종 주문은 Risk/Execution에서 검증**

### (C) 관측가능성/리포팅
- “왜 이 결정을 내렸는지”를 사람이 이해할 수 있게 근거 요약
- 장애/이상탐지 로그 요약 및 대응 가이드

> 반대로, LLM에게 “그냥 차트 보고 매수/매도 수량까지 결정”을 맡기면 변동성/환각/레이트리밋/주문 실패 등 실전 리스크가 커집니다.  
> **수치·규칙은 코드**, **텍스트·설명은 LLM**으로 분리하세요.

---

## 5) LangGraph 기반 멀티 에이전트 아키텍처

### 왜 LangGraph인가?

단순 파이프라인이 아닌 **상태 기반 그래프**가 필요한 이유:

```
❌ 단순 파이프라인 (기존 방식)
   데이터 수집 → 지표 계산 → LLM 결정 → 실행
   (항상 동일한 경로, 상황 대응 불가)

✅ LangGraph (제안)
   상황에 따라 다른 경로 선택, 에이전트 간 협업, 사람 개입 가능
```

### 핵심 활용 패턴

| 패턴 | 활용 영역 | 장점 |
|------|----------|------|
| **Supervisor** | 전체 에이전트 오케스트레이션 | LLM이 상황에 맞게 에이전트 선택 |
| **조건부 라우팅** | 시장 상황별 전략 분기 | 고변동성/뉴스/비상 상황 대응 |
| **ReAct** | 데이터 수집 에이전트 | 필요한 정보만 선택적 수집 |
| **Human-in-the-Loop** | 대규모 거래 승인 | 리스크 관리, 킬스위치 |
| **Plan-and-Execute** | 복잡한 포지션 관리 | 다단계 진입/청산 전략 |

---

### 5-1) 상태(State) 스키마

```python
from typing import TypedDict, Literal, Annotated
from operator import add

class MarketData(TypedDict):
    symbol: str
    current_price: float
    ohlcv: list[dict]
    orderbook: dict
    volatility_level: Literal["low", "medium", "high"]
    percent_change_1h: float
    percent_change_24h: float

class NewsContext(TypedDict):
    headlines: list[str]
    sentiment: float  # -1.0 ~ 1.0
    impact: Literal["low", "medium", "high"]
    summary: str

class IndicatorSignals(TypedDict):
    trend: Literal["bullish", "bearish", "neutral"]
    momentum: Literal["overbought", "oversold", "neutral"]
    volatility: Literal["low", "medium", "high"]
    signals: dict[str, float]  # RSI, MACD 등

class Portfolio(TypedDict):
    cash_krw: float
    btc_balance: float
    avg_entry_price: float
    unrealized_pnl: float
    exposure_pct: float

class RiskState(TypedDict):
    daily_loss_pct: float
    max_loss_pct: float
    position_limit_pct: float
    is_kill_switch_on: bool

class Decision(TypedDict):
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float
    suggested_size_pct: float
    rationale: str
    status: Literal["pending", "approved", "rejected", "executed"]

class Anomaly(TypedDict):
    type: str
    severity: Literal["low", "medium", "high"]
    description: str

class TradingState(TypedDict):
    """LangGraph 전체 상태"""
    # 데이터
    market: MarketData | None
    news: NewsContext | None
    indicators: IndicatorSignals | None
    portfolio: Portfolio | None

    # 리스크 & 결정
    risk: RiskState
    decision: Decision | None
    anomalies: list[Anomaly]

    # 메타
    messages: Annotated[list, add]  # 에이전트 간 대화 기록
    current_step: str
    error: str | None
```

---

### 5-2) Supervisor 패턴 (에이전트 오케스트레이션)

Supervisor가 현재 상태를 보고 다음에 호출할 에이전트를 결정합니다.

```python
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

llm = ChatAnthropic(model="claude-sonnet-4-20250514")

SUPERVISOR_PROMPT = """당신은 BTC 트레이딩 시스템의 Supervisor입니다.
현재 상태를 분석하고 다음에 실행할 에이전트를 선택하세요.

## 현재 상태
- 시장 데이터: {market_status}
- 뉴스 분석: {news_status}
- 지표 계산: {indicator_status}
- 포트폴리오: {portfolio_status}
- 이상 감지: {anomaly_count}건

## 사용 가능한 에이전트
1. market_agent: 시장 데이터 수집 (pyupbit + CoinMarketCap)
2. news_agent: 뉴스 헤드라인 수집 및 분석
3. indicator_agent: 기술적 지표 계산
4. analysis_agent: 종합 분석 및 매매 제안 생성
5. risk_agent: 리스크 검증
6. execution_agent: 주문 실행
7. FINISH: 이번 사이클 종료

## 규칙
- 시장 데이터가 없으면 market_agent 먼저
- 이상 감지 시 analysis_agent로 바로 이동
- decision이 있고 approved면 execution_agent
- 모든 데이터가 있고 decision이 없으면 analysis_agent

다음 에이전트 이름만 출력하세요:"""

def supervisor_node(state: TradingState) -> dict:
    """Supervisor: 다음 에이전트 결정"""

    prompt = SUPERVISOR_PROMPT.format(
        market_status="있음" if state.get("market") else "없음",
        news_status="있음" if state.get("news") else "없음",
        indicator_status="있음" if state.get("indicators") else "없음",
        portfolio_status="있음" if state.get("portfolio") else "없음",
        anomaly_count=len(state.get("anomalies", []))
    )

    response = llm.invoke([
        SystemMessage(content="You are a trading system supervisor."),
        HumanMessage(content=prompt)
    ])

    next_agent = response.content.strip().lower()

    return {"current_step": next_agent}

def route_from_supervisor(state: TradingState) -> str:
    """Supervisor 결정에 따라 라우팅"""
    return state["current_step"]
```

---

### 5-3) 조건부 라우팅 (시장 상황별 분기)

```python
from typing import Literal

def route_by_market_condition(
    state: TradingState
) -> Literal["normal", "volatile", "news_driven", "emergency"]:
    """시장 상황에 따라 다른 전략 경로 선택"""

    anomalies = state.get("anomalies", [])
    market = state.get("market", {})
    news = state.get("news", {})

    # 1. 비상 상황 (급등락 10% 이상, 거래량 폭증)
    high_severity = any(a["severity"] == "high" for a in anomalies)
    if high_severity:
        return "emergency"

    # 2. 뉴스 주도 시장
    if news.get("impact") == "high":
        return "news_driven"

    # 3. 고변동성 시장
    if market.get("volatility_level") == "high":
        return "volatile"

    # 4. 일반 시장
    return "normal"

# 각 상황별 전략 노드
def normal_strategy_node(state: TradingState) -> dict:
    """일반 시장: 지표 기반 전략"""
    # 표준 지표 분석 + LLM 판단
    return {"current_step": "normal_analysis"}

def volatile_strategy_node(state: TradingState) -> dict:
    """고변동성 시장: 보수적 전략"""
    # 포지션 축소, 손절 타이트하게
    return {
        "decision": {
            "action": "HOLD",
            "confidence": 0.0,
            "suggested_size_pct": 0.0,
            "rationale": "High volatility detected - conservative mode",
            "status": "approved"
        }
    }

def news_driven_strategy_node(state: TradingState) -> dict:
    """뉴스 주도 시장: 뉴스 심층 분석 후 판단"""
    # 뉴스 내용 상세 분석 → 방향성 판단
    return {"current_step": "deep_news_analysis"}

def emergency_handler_node(state: TradingState) -> dict:
    """비상 상황: 즉시 포지션 정리 또는 동결"""
    anomalies = state.get("anomalies", [])

    # 알림 발송
    alert_message = f"🚨 비상 상황 감지: {[a['description'] for a in anomalies]}"

    return {
        "decision": {
            "action": "HOLD",  # 또는 SELL (전량 청산)
            "confidence": 1.0,
            "suggested_size_pct": 0.0,
            "rationale": f"Emergency: {alert_message}",
            "status": "approved"
        },
        "messages": [{"role": "system", "content": alert_message}]
    }
```

---

### 5-4) ReAct 패턴 (도구 기반 데이터 수집)

LLM이 필요한 도구를 선택적으로 호출하여 정보를 수집합니다.

```python
from langchain.tools import tool
from langchain.agents import create_react_agent, AgentExecutor

@tool
def get_btc_price() -> dict:
    """현재 BTC 가격과 변동률 조회"""
    import pyupbit
    price = pyupbit.get_current_price("KRW-BTC")
    return {"price": price, "symbol": "KRW-BTC"}

@tool
def get_ohlcv(interval: str = "minute5", count: int = 100) -> dict:
    """OHLCV 캔들 데이터 조회

    Args:
        interval: 캔들 간격 (minute1, minute5, minute15, hour, day)
        count: 조회할 캔들 개수
    """
    import pyupbit
    df = pyupbit.get_ohlcv("KRW-BTC", interval=interval, count=count)
    return df.tail(10).to_dict()

@tool
def get_rsi(period: int = 14) -> float:
    """RSI 지표 계산

    Args:
        period: RSI 계산 기간 (기본 14)
    """
    import pyupbit
    import pandas_ta as ta
    df = pyupbit.get_ohlcv("KRW-BTC", count=period + 10)
    rsi = ta.rsi(df['close'], length=period)
    return float(rsi.iloc[-1])

@tool
def get_news_headlines(limit: int = 5) -> list[str]:
    """최근 BTC 관련 뉴스 헤드라인 조회

    Args:
        limit: 조회할 뉴스 개수
    """
    # RSS 피드에서 헤드라인 수집
    return rss_collector.fetch_headlines(limit)

@tool
def get_portfolio() -> dict:
    """현재 포트폴리오 상태 조회"""
    balances = upbit.get_balances()
    return {
        "KRW": next((b for b in balances if b["currency"] == "KRW"), {}),
        "BTC": next((b for b in balances if b["currency"] == "BTC"), {})
    }

@tool
def get_global_metrics() -> dict:
    """글로벌 시장 지표 조회 (BTC 도미넌스 등)"""
    return cmc_provider.get_global_metrics().__dict__

# ReAct 에이전트 생성
REACT_PROMPT = """당신은 BTC 시장 분석가입니다.
주어진 도구를 사용하여 현재 시장 상황을 분석하세요.

사용 가능한 도구:
{tools}

도구 이름: {tool_names}

분석에 필요한 정보를 수집한 후, 종합 분석 결과를 제공하세요.

## 출력 형식
Thought: 현재 무엇을 해야 하는지 생각
Action: 사용할 도구 이름
Action Input: 도구에 전달할 입력
Observation: 도구 실행 결과

(위 과정을 필요한 만큼 반복)

Thought: 충분한 정보를 수집했으므로 최종 분석
Final Answer: 종합 분석 결과

{agent_scratchpad}
"""

def create_data_agent():
    """ReAct 기반 데이터 수집 에이전트"""
    tools = [get_btc_price, get_ohlcv, get_rsi, get_news_headlines,
             get_portfolio, get_global_metrics]

    agent = create_react_agent(llm, tools, REACT_PROMPT)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)

def data_collection_node(state: TradingState) -> dict:
    """ReAct 에이전트로 데이터 수집"""
    agent = create_data_agent()

    result = agent.invoke({
        "input": "현재 BTC 시장 상황을 분석하기 위해 필요한 데이터를 수집하세요."
    })

    # 결과 파싱하여 상태 업데이트
    return {
        "messages": [{"role": "agent", "content": result["output"]}]
    }
```

---

### 5-5) Human-in-the-Loop (거래 승인)

대규모 거래나 중요 결정 시 사람의 승인을 요청합니다.

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

APPROVAL_THRESHOLD_KRW = 1_000_000  # 100만원 이상 거래 시 승인 필요

def human_approval_node(state: TradingState) -> dict:
    """대규모 거래 시 사람 승인 요청"""

    decision = state.get("decision")
    if not decision:
        return state

    portfolio = state.get("portfolio", {})
    trade_amount = portfolio.get("cash_krw", 0) * decision.get("suggested_size_pct", 0)

    # 승인 필요 조건 체크
    needs_approval = (
        trade_amount > APPROVAL_THRESHOLD_KRW or
        decision.get("action") == "SELL" and decision.get("suggested_size_pct", 0) > 0.5
    )

    if needs_approval:
        # 실행 중단하고 사람에게 질문
        approval = interrupt({
            "type": "approval_request",
            "question": "다음 거래를 승인하시겠습니까?",
            "details": {
                "action": decision["action"],
                "amount_krw": f"{trade_amount:,.0f} KRW",
                "confidence": f"{decision['confidence']:.1%}",
                "rationale": decision["rationale"]
            },
            "options": ["approve", "reject", "modify_size"]
        })

        if approval["response"] == "reject":
            return {
                "decision": {**decision, "status": "rejected"},
                "messages": [{"role": "human", "content": "거래 거부됨"}]
            }
        elif approval["response"] == "modify_size":
            new_size = approval.get("new_size_pct", decision["suggested_size_pct"] * 0.5)
            return {
                "decision": {**decision, "suggested_size_pct": new_size, "status": "approved"}
            }

    return {"decision": {**decision, "status": "approved"}}

# 킬스위치 노드
def kill_switch_node(state: TradingState) -> dict:
    """킬스위치 체크"""

    if state.get("risk", {}).get("is_kill_switch_on"):
        return {
            "decision": {
                "action": "HOLD",
                "confidence": 1.0,
                "suggested_size_pct": 0.0,
                "rationale": "Kill switch is ON - all trading halted",
                "status": "approved"
            },
            "error": "KILL_SWITCH_ACTIVE"
        }

    return state
```

---

### 5-6) Plan-and-Execute 패턴 (복잡한 전략)

복잡한 포지션 관리(분할 매수/매도 등)를 위한 계획 수립 및 실행.

```python
from dataclasses import dataclass

@dataclass
class ExecutionStep:
    step_type: str  # "wait", "check_condition", "trade", "alert"
    params: dict
    condition: str | None = None

PLANNER_PROMPT = """당신은 BTC 트레이딩 전략가입니다.
현재 상황을 분석하고 실행 계획을 수립하세요.

## 현재 상황
- 가격: {price:,.0f} KRW
- 24시간 변동: {change_24h:+.2f}%
- RSI: {rsi:.1f}
- 보유 BTC: {btc_balance:.6f}
- 가용 현금: {cash:,.0f} KRW

## 계획 수립 규칙
1. 한 번에 전체 물량을 거래하지 말 것 (분할 매수/매도)
2. 각 단계마다 조건 확인 후 진행
3. 리스크 관리 단계 필수 포함

## 출력 형식 (JSON)
{{
  "strategy_name": "전략 이름",
  "total_steps": 숫자,
  "steps": [
    {{
      "step": 1,
      "type": "check_condition",
      "description": "RSI 30 이하 확인",
      "condition": "rsi < 30",
      "on_true": "continue",
      "on_false": "abort"
    }},
    {{
      "step": 2,
      "type": "trade",
      "action": "BUY",
      "size_pct": 0.3,
      "description": "1차 매수 (30%)"
    }},
    {{
      "step": 3,
      "type": "wait",
      "duration_minutes": 30,
      "description": "30분 대기"
    }}
  ]
}}
"""

def planner_node(state: TradingState) -> dict:
    """실행 계획 수립"""

    market = state.get("market", {})
    portfolio = state.get("portfolio", {})
    indicators = state.get("indicators", {})

    prompt = PLANNER_PROMPT.format(
        price=market.get("current_price", 0),
        change_24h=market.get("percent_change_24h", 0),
        rsi=indicators.get("signals", {}).get("rsi", 50),
        btc_balance=portfolio.get("btc_balance", 0),
        cash=portfolio.get("cash_krw", 0)
    )

    response = llm.invoke([HumanMessage(content=prompt)])

    import json
    plan = json.loads(response.content)

    return {
        "execution_plan": plan,
        "plan_step": 0,
        "messages": [{"role": "planner", "content": f"계획 수립: {plan['strategy_name']}"}]
    }

def executor_node(state: TradingState) -> dict:
    """계획의 현재 단계 실행"""

    plan = state.get("execution_plan", {})
    current_idx = state.get("plan_step", 0)

    if current_idx >= len(plan.get("steps", [])):
        return {"current_step": "plan_complete"}

    step = plan["steps"][current_idx]

    if step["type"] == "check_condition":
        # 조건 평가
        condition_met = evaluate_condition(step["condition"], state)
        if not condition_met and step.get("on_false") == "abort":
            return {"current_step": "plan_aborted", "error": f"Condition failed: {step['condition']}"}

    elif step["type"] == "trade":
        # 거래 실행 요청 생성
        return {
            "decision": {
                "action": step["action"],
                "suggested_size_pct": step["size_pct"],
                "rationale": step["description"],
                "status": "pending"
            },
            "plan_step": current_idx + 1
        }

    elif step["type"] == "wait":
        # 대기 (실제로는 스케줄러에서 처리)
        return {
            "plan_step": current_idx + 1,
            "messages": [{"role": "executor", "content": f"대기 중: {step['duration_minutes']}분"}]
        }

    return {"plan_step": current_idx + 1}

def should_continue_plan(state: TradingState) -> Literal["continue", "complete", "abort"]:
    """계획 계속 실행 여부 판단"""

    if state.get("error"):
        return "abort"

    plan = state.get("execution_plan", {})
    current_idx = state.get("plan_step", 0)

    if current_idx >= len(plan.get("steps", [])):
        return "complete"

    # 시장 급변 시 재계획
    if any(a["severity"] == "high" for a in state.get("anomalies", [])):
        return "abort"

    return "continue"
```

---

### 5-7) 전체 그래프 구성

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

def build_trading_graph() -> StateGraph:
    """트레이딩 시스템 그래프 구성"""

    graph = StateGraph(TradingState)

    # 노드 추가
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("market_agent", market_data_node)
    graph.add_node("news_agent", news_collection_node)
    graph.add_node("indicator_agent", indicator_calculation_node)
    graph.add_node("analysis_agent", data_collection_node)  # ReAct
    graph.add_node("risk_agent", risk_validation_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("execution_agent", execution_node)
    graph.add_node("kill_switch", kill_switch_node)

    # 전략별 노드
    graph.add_node("normal_strategy", normal_strategy_node)
    graph.add_node("volatile_strategy", volatile_strategy_node)
    graph.add_node("news_strategy", news_driven_strategy_node)
    graph.add_node("emergency_handler", emergency_handler_node)

    # Plan-and-Execute 노드
    graph.add_node("planner", planner_node)
    graph.add_node("executor", executor_node)

    # 시작점
    graph.set_entry_point("kill_switch")

    # 킬스위치 → Supervisor (또는 종료)
    graph.add_conditional_edges(
        "kill_switch",
        lambda s: "end" if s.get("error") == "KILL_SWITCH_ACTIVE" else "continue",
        {"end": END, "continue": "supervisor"}
    )

    # Supervisor → 각 에이전트
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "market_agent": "market_agent",
            "news_agent": "news_agent",
            "indicator_agent": "indicator_agent",
            "analysis_agent": "analysis_agent",
            "risk_agent": "risk_agent",
            "execution_agent": "human_approval",  # 실행 전 승인
            "finish": END
        }
    )

    # 데이터 수집 에이전트 → Supervisor로 복귀
    for agent in ["market_agent", "news_agent", "indicator_agent"]:
        graph.add_edge(agent, "supervisor")

    # 분석 에이전트 → 시장 상황별 라우팅
    graph.add_conditional_edges(
        "analysis_agent",
        route_by_market_condition,
        {
            "normal": "normal_strategy",
            "volatile": "volatile_strategy",
            "news_driven": "news_strategy",
            "emergency": "emergency_handler"
        }
    )

    # 전략 노드 → 리스크 검증
    for strategy in ["normal_strategy", "news_strategy"]:
        graph.add_edge(strategy, "risk_agent")

    # 보수적/비상 전략 → 바로 종료
    graph.add_edge("volatile_strategy", END)
    graph.add_edge("emergency_handler", END)

    # 리스크 검증 → Supervisor (재평가 또는 실행)
    graph.add_edge("risk_agent", "supervisor")

    # 사람 승인 → 실행
    graph.add_conditional_edges(
        "human_approval",
        lambda s: "execute" if s.get("decision", {}).get("status") == "approved" else "end",
        {"execute": "execution_agent", "end": END}
    )

    # 실행 → 종료
    graph.add_edge("execution_agent", END)

    return graph

# 체크포인터로 상태 저장 (Human-in-the-loop 지원)
checkpointer = MemorySaver()

# 그래프 컴파일
app = build_trading_graph().compile(
    checkpointer=checkpointer,
    interrupt_before=["human_approval"]  # 승인 전 중단
)
```

---

### 5-8) 그래프 실행 예시

```python
import asyncio

async def run_trading_cycle():
    """트레이딩 사이클 실행"""

    # 초기 상태
    initial_state = {
        "market": None,
        "news": None,
        "indicators": None,
        "portfolio": None,
        "risk": {
            "daily_loss_pct": 0.0,
            "max_loss_pct": 3.0,
            "position_limit_pct": 50.0,
            "is_kill_switch_on": False
        },
        "decision": None,
        "anomalies": [],
        "messages": [],
        "current_step": "start",
        "error": None
    }

    config = {"configurable": {"thread_id": "trading-session-1"}}

    # 그래프 실행
    async for event in app.astream(initial_state, config):
        print(f"Step: {event}")

        # Human-in-the-loop 처리
        if "__interrupt__" in event:
            interrupt_info = event["__interrupt__"]
            print(f"\n🔔 승인 요청: {interrupt_info}")

            # 사용자 입력 대기 (실제로는 Slack/웹 등에서 처리)
            user_response = await get_user_approval(interrupt_info)

            # 응답으로 재개
            async for resume_event in app.astream(
                {"approval_response": user_response},
                config
            ):
                print(f"Resume: {resume_event}")

# 주기적 실행
async def main():
    while True:
        try:
            await run_trading_cycle()
        except Exception as e:
            print(f"Error: {e}")

        await asyncio.sleep(60 * 5)  # 5분 간격

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6) 데이터/스토리지 설계 (리플레이 가능하게)

### 저장해야 하는 것(최소)
- 입력: 뉴스 원문(링크/타임스탬프/소스), OHLCV/오더북 스냅샷
- 파생: 지표 값, 뉴스 요약/태그/스코어
- 출력: 의사결정(action/size), 주문 요청/응답, 체결 결과
- 근거: “왜?”(rationale)와 사용한 주요 feature/스코어

### 스토리지 추천
- 실시간 캐시: Redis(옵션)
- 시계열/캔들: TimescaleDB/InfluxDB(또는 Postgres)
- 뉴스/문서: Postgres + 벡터DB(옵션: pgvector)
- 로그/추적: OpenTelemetry + Loki/ELK 등(규모에 따라)

> 리플레이(Backtest/Replay)는 “같은 입력 → 같은 출력”이 가능해야 신뢰도가 올라갑니다.

---

## 7) 트레이딩 안전장치 체크리스트 (필수)

- **페이퍼 트레이딩 모드**(실거래 전 기본값)
- **킬스위치**(즉시 중단, 신규 주문 차단)
- **최대 손실/일일 손실 한도** + 초과 시 자동 중단
- **포지션 제한**(최대 노출, 레버리지, 진입 횟수)
- **주문 검증**
  - 최소/최대 주문 수량, 가격 밴드(현재가 대비 ±x%)
  - 중복 주문 방지(idempotency key)
  - 실패 재시도(지수 백오프) 및 “재시도 상한”
- **데이터 품질 게이트**
  - 캔들 결측/지연 시 거래 중단
  - 뉴스 소스 신뢰도/중복 제거
- **감사 로그**(누가/언제/무슨 근거로 거래했는지)

---

## 8) 확장성을 위한 인터페이스 설계(핵심)

### 공통 도메인 모델(예)
- `Instrument` (symbol, asset_class, venue…)
- `MarketSnapshot` (ohlcv, orderbook, timestamp…)
- `Signal` (direction, confidence, horizon, features…)
- `RiskConstraints` (max_position, max_loss, allowed_order_types…)
- `OrderRequest/OrderResult` (idempotency, status, fills…)

### 어댑터 패턴
- `MarketDataProvider`: exchange/stock API 별 구현
- `NewsProvider`: RSS, paid API, scraping 등
- `BrokerAdapter`: 주문/잔고/포지션 추상화

이렇게 해두면 BTC → 주식/부동산으로 확장할 때 “Agent 로직”은 대부분 재사용 가능합니다.

---

## 9) MVP에서 바로 구현하면 좋은 "결정 규칙" 예시

- 지표 신호가 강하더라도:
  - 변동성이 기준치 이상이면 **사이즈 축소**
  - 주요 뉴스가 불확실(루머)로 분류되면 **보류**
  - 데이터 지연/결측 시 **거래 중지**
- LLM 출력은 반드시 아래 형태로 제한(스키마 강제):
  - `{action: BUY|SELL|HOLD, confidence: 0~1, rationale: "...", required_checks: [...], suggested_size_pct: ...}`
- `required_checks`를 Risk Manager가 만족시키지 못하면 **자동 HOLD**

---

## 10) 다음 액션(바로 착수용)

1) “MVP 범위”를 아래로 고정 추천  
- 대상: BTC 현물(또는 선물) 1개 거래소  
- 타임프레임: 1m/5m 캔들  
- 뉴스 소스: 2~3개  
- 전략: 기술적 지표 + 뉴스 영향도에 따른 사이즈 조절  
- 안전장치: 페이퍼 모드 + 손실한도 + 킬스위치

2) LangGraph 상태/이벤트 스키마를 먼저 문서화  
3) Execution/Risk부터 구현(의사결정은 마지막)  
4) 리플레이 가능한 로그 저장을 MVP 단계부터 포함

---

## 11) LLM 의사결정 기준 (Decision Criteria)

### LLM 의사결정 범위 및 역할

LLM은 **최종 주문 결정자가 아닌 "분석/제안자"** 역할을 수행합니다.

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM 역할 (DO)                            │
├─────────────────────────────────────────────────────────────┤
│ ✓ 뉴스 요약/분류/중요도 판단                                 │
│ ✓ 지표 신호 해석 및 충돌 분석                                │
│ ✓ 매매 제안(Proposal) 생성                                  │
│ ✓ 의사결정 근거(rationale) 작성                             │
│ ✓ 리스크 수준 평가 (high/medium/low)                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    LLM 역할 아님 (DON'T)                     │
├─────────────────────────────────────────────────────────────┤
│ ✗ 정확한 주문 수량/가격 계산                                 │
│ ✗ 레버리지/포지션 사이즈 최종 결정                           │
│ ✗ 주문 실행 직접 호출                                       │
│ ✗ 리스크 한도 우회                                          │
└─────────────────────────────────────────────────────────────┘
```

### LLM 입력 데이터 (Input Context)

```python
@dataclass
class LLMDecisionInput:
    """LLM 의사결정을 위한 입력 컨텍스트"""

    # 시장 상태
    current_price: float
    price_change_1h: float       # 1시간 변동률 (%)
    price_change_24h: float      # 24시간 변동률 (%)

    # 기술적 지표 요약
    trend_signal: str            # "bullish" | "bearish" | "neutral"
    momentum_signal: str         # "overbought" | "oversold" | "neutral"
    volatility_level: str        # "high" | "medium" | "low"

    # 뉴스/이벤트
    recent_news_summary: str     # 최근 뉴스 요약 (LLM이 사전 처리)
    news_sentiment: float        # -1.0 ~ 1.0
    news_importance: str         # "high" | "medium" | "low"

    # 포트폴리오 상태
    current_position: float      # 현재 BTC 보유량
    position_pnl_pct: float      # 현재 포지션 손익률 (%)
    available_cash: float        # 사용 가능 현금 (KRW)

    # 리스크 상태
    daily_loss_pct: float        # 당일 실현 손실률
    max_allowed_loss_pct: float  # 허용 최대 손실률
```

### LLM 출력 스키마 (Output Schema)

```python
@dataclass
class LLMDecisionOutput:
    """LLM 의사결정 출력 (스키마 강제)"""

    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float            # 0.0 ~ 1.0
    suggested_size_pct: float    # 제안 포지션 비율 (0.0 ~ 1.0)

    rationale: str               # 결정 근거 (사람이 읽을 수 있는 형태)

    # 리스크 체크 요청
    required_checks: list[str]   # ["volatility_ok", "news_confirmed", ...]

    # 메타 정보
    news_impact: str             # "positive" | "negative" | "neutral" | "uncertain"
    time_horizon: str            # "immediate" | "short_term" | "hold"
```

### 의사결정 기준 매트릭스

| 조건 | action | confidence | 비고 |
|------|--------|------------|------|
| 추세 상승 + 뉴스 긍정 + 변동성 낮음 | BUY | 0.7~0.9 | 가장 이상적 |
| 추세 상승 + 뉴스 중립 | BUY | 0.5~0.7 | 소량 진입 |
| 추세 하락 + 뉴스 부정 | SELL | 0.7~0.9 | 포지션 정리 |
| 지표 충돌 (추세↑ 모멘텀↓) | HOLD | - | 관망 |
| 변동성 급등 (어떤 신호든) | HOLD | - | 리스크 회피 |
| 뉴스 불확실 (루머) | HOLD | - | 확정 대기 |
| 일일 손실 한도 근접 | HOLD/SELL | - | 리스크 차단 |

### LLM 프롬프트 템플릿

```python
DECISION_PROMPT = '''
당신은 BTC 트레이딩 어시스턴트입니다. 아래 데이터를 분석하여 매매 제안을 생성하세요.

## 현재 시장 상태
- 가격: {current_price:,.0f} KRW
- 1시간 변동: {price_change_1h:+.2f}%
- 24시간 변동: {price_change_24h:+.2f}%

## 기술적 지표
- 추세: {trend_signal}
- 모멘텀: {momentum_signal}
- 변동성: {volatility_level}

## 뉴스 분석
{recent_news_summary}
- 감성 점수: {news_sentiment:.2f}
- 중요도: {news_importance}

## 포트폴리오
- 현재 포지션: {current_position:.6f} BTC
- 포지션 손익: {position_pnl_pct:+.2f}%
- 가용 현금: {available_cash:,.0f} KRW

## 리스크 상태
- 당일 손실: {daily_loss_pct:.2f}% / 한도 {max_allowed_loss_pct:.2f}%

---

**규칙:**
1. 변동성이 "high"면 반드시 HOLD
2. 일일 손실이 한도의 80% 이상이면 신규 BUY 금지
3. 뉴스가 "uncertain"이면 confidence 0.5 이하
4. 지표 신호가 충돌하면 HOLD

**출력 형식 (JSON):**
{{
  "action": "BUY|SELL|HOLD",
  "confidence": 0.0-1.0,
  "suggested_size_pct": 0.0-1.0,
  "rationale": "결정 근거...",
  "required_checks": ["check1", "check2"],
  "news_impact": "positive|negative|neutral|uncertain",
  "time_horizon": "immediate|short_term|hold"
}}
'''
```

### Risk Manager의 최종 검증

LLM 출력은 반드시 Risk Manager를 통해 검증됩니다:

```python
def validate_llm_decision(
    decision: LLMDecisionOutput,
    risk_state: RiskState,
    market_state: MarketState
) -> tuple[bool, str]:
    """LLM 결정을 리스크 규칙으로 검증"""

    # 1. 변동성 체크
    if market_state.volatility_level == "high" and decision.action != "HOLD":
        return False, "High volatility - forced HOLD"

    # 2. 일일 손실 한도 체크
    if risk_state.daily_loss_pct >= risk_state.max_loss_pct * 0.8:
        if decision.action == "BUY":
            return False, "Daily loss limit approaching - BUY blocked"

    # 3. 낮은 확신도 체크
    if decision.confidence < 0.5 and decision.action != "HOLD":
        return False, f"Low confidence ({decision.confidence}) - forced HOLD"

    # 4. 포지션 한도 체크
    if decision.action == "BUY":
        projected_exposure = calculate_exposure(decision.suggested_size_pct)
        if projected_exposure > risk_state.max_exposure:
            return False, "Max exposure exceeded"

    # 5. required_checks 검증
    for check in decision.required_checks:
        if not verify_check(check, market_state, risk_state):
            return False, f"Required check failed: {check}"

    return True, "All checks passed"
```

---

## 12) pyupbit 기반 거래소 연동 계획

> 참고: [pyupbit GitHub](https://github.com/sharebook-kr/pyupbit)

### pyupbit 주요 기능 활용 매핑

| Sub-agent | pyupbit 함수 | 용도 |
|-----------|-------------|------|
| **Market Data Agent** | `get_tickers()`, `get_current_price()`, `get_ohlcv()`, `get_orderbook()` | 시세/캔들/호가 수집 |
| **Indicator Agent** | `get_ohlcv()` (DataFrame 반환) | OHLCV 기반 지표 계산 |
| **Risk Manager Agent** | `get_balance()`, `get_balances()` | 잔고/포지션 확인 |
| **Execution Agent** | `buy_market_order()`, `sell_market_order()`, `buy_limit_order()`, `sell_limit_order()`, `get_order()`, `cancel_order()` | 주문 집행/관리 |

### pyupbit 래퍼 설계 (`UpbitBrokerAdapter` 구현)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
import pyupbit

class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"

@dataclass
class OrderRequest:
    symbol: str          # e.g., "KRW-BTC"
    side: OrderSide
    order_type: OrderType
    quantity: float | None = None  # 매도 시 수량
    price: float | None = None     # 지정가 주문 시
    amount: float | None = None    # 시장가 매수 시 금액

@dataclass
class OrderResult:
    uuid: str
    symbol: str
    side: OrderSide
    status: str
    filled_quantity: float
    avg_price: float
    error: str | None = None

class BrokerAdapter(ABC):
    """거래소 추상화 인터페이스 (멀티자산 확장 대비)"""

    @abstractmethod
    def get_balance(self, symbol: str) -> float: ...

    @abstractmethod
    def get_all_balances(self) -> dict[str, float]: ...

    @abstractmethod
    def submit_order(self, request: OrderRequest) -> OrderResult: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderResult: ...

    @abstractmethod
    def get_open_orders(self, symbol: str | None = None) -> list[OrderResult]: ...

class UpbitBrokerAdapter(BrokerAdapter):
    """pyupbit 기반 Upbit 거래소 어댑터"""

    def __init__(self, access_key: str, secret_key: str):
        self._client = pyupbit.Upbit(access_key, secret_key)

    def get_balance(self, symbol: str) -> float:
        return self._client.get_balance(symbol)

    def get_all_balances(self) -> dict[str, float]:
        balances = self._client.get_balances()
        return {b['currency']: float(b['balance']) for b in balances}

    def submit_order(self, request: OrderRequest) -> OrderResult:
        try:
            if request.order_type == OrderType.MARKET:
                if request.side == OrderSide.BUY:
                    resp = self._client.buy_market_order(request.symbol, request.amount)
                else:
                    resp = self._client.sell_market_order(request.symbol, request.quantity)
            else:  # LIMIT
                if request.side == OrderSide.BUY:
                    resp = self._client.buy_limit_order(
                        request.symbol, request.price, request.quantity
                    )
                else:
                    resp = self._client.sell_limit_order(
                        request.symbol, request.price, request.quantity
                    )
            return self._parse_order_response(resp, request)
        except Exception as e:
            return OrderResult(
                uuid="", symbol=request.symbol, side=request.side,
                status="error", filled_quantity=0, avg_price=0, error=str(e)
            )

    def cancel_order(self, order_id: str) -> bool:
        result = self._client.cancel_order(order_id)
        return result is not None and 'uuid' in result

    def get_order_status(self, order_id: str) -> OrderResult:
        order = self._client.get_order(order_id)
        return self._parse_existing_order(order)

    def get_open_orders(self, symbol: str | None = None) -> list[OrderResult]:
        orders = self._client.get_order(symbol) if symbol else self._client.get_order()
        return [self._parse_existing_order(o) for o in (orders or [])]

    def _parse_order_response(self, resp: dict, request: OrderRequest) -> OrderResult:
        if resp is None or 'error' in resp:
            return OrderResult(
                uuid="", symbol=request.symbol, side=request.side,
                status="error", filled_quantity=0, avg_price=0,
                error=str(resp.get('error') if resp else 'No response')
            )
        return OrderResult(
            uuid=resp.get('uuid', ''),
            symbol=request.symbol,
            side=request.side,
            status=resp.get('state', 'unknown'),
            filled_quantity=float(resp.get('executed_volume', 0)),
            avg_price=float(resp.get('avg_price', 0)) if resp.get('avg_price') else 0
        )

    def _parse_existing_order(self, order: dict) -> OrderResult:
        return OrderResult(
            uuid=order.get('uuid', ''),
            symbol=order.get('market', ''),
            side=OrderSide.BUY if order.get('side') == 'bid' else OrderSide.SELL,
            status=order.get('state', 'unknown'),
            filled_quantity=float(order.get('executed_volume', 0)),
            avg_price=float(order.get('avg_price', 0)) if order.get('avg_price') else 0
        )
```

### 레이트리밋 대응

pyupbit API 제한에 맞춘 레이트리밋 설정:

| 카테고리 | 제한 | 권장 간격 |
|---------|------|----------|
| 시세 API | 초당 10회, 분당 600회 | 100ms+ 간격 |
| 주문 API | 초당 8회, 분당 200회 | 125ms+ 간격 |
| 기타 요청 | 초당 30회, 분당 900회 | 35ms+ 간격 |

```python
import time
import threading
from functools import wraps

class RateLimiter:
    """Thread-safe rate limiter"""

    def __init__(self, calls_per_second: float):
        self._min_interval = 1.0 / calls_per_second
        self._last_call = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            self.wait()
            return func(*args, **kwargs)
        return wrapper

# 용도별 리미터 인스턴스
market_limiter = RateLimiter(calls_per_second=8)   # 시세: 여유 있게 8/sec
order_limiter = RateLimiter(calls_per_second=6)    # 주문: 여유 있게 6/sec
```

### Market Data Agent 구현 예시

```python
import pyupbit
import pandas as pd
from dataclasses import dataclass
import time

@dataclass
class MarketSnapshot:
    symbol: str
    timestamp: float
    current_price: float
    ohlcv: pd.DataFrame      # 최근 N개 캔들
    orderbook: dict          # 호가 정보
    bid_ask_spread: float    # 스프레드 (%)

class UpbitMarketDataAgent:
    """Upbit 시장 데이터 수집 에이전트"""

    def __init__(self, symbols: list[str], interval: str = "minute1"):
        self.symbols = symbols
        self.interval = interval
        self._limiter = RateLimiter(8)

    def fetch_snapshot(self, symbol: str, candle_count: int = 200) -> MarketSnapshot:
        """단일 심볼의 시장 스냅샷 수집"""
        self._limiter.wait()
        price = pyupbit.get_current_price(symbol)

        self._limiter.wait()
        ohlcv = pyupbit.get_ohlcv(symbol, interval=self.interval, count=candle_count)

        self._limiter.wait()
        orderbook_data = pyupbit.get_orderbook(ticker=symbol)
        orderbook = orderbook_data[0] if orderbook_data else {}

        # 스프레드 계산
        spread = 0.0
        if orderbook and 'orderbook_units' in orderbook:
            units = orderbook['orderbook_units']
            if units:
                best_ask = units[0].get('ask_price', 0)
                best_bid = units[0].get('bid_price', 0)
                if best_bid > 0:
                    spread = (best_ask - best_bid) / best_bid * 100

        return MarketSnapshot(
            symbol=symbol,
            timestamp=time.time(),
            current_price=price,
            ohlcv=ohlcv,
            orderbook=orderbook,
            bid_ask_spread=spread
        )

    def fetch_all_snapshots(self) -> dict[str, MarketSnapshot]:
        """모든 추적 심볼의 스냅샷 수집"""
        return {symbol: self.fetch_snapshot(symbol) for symbol in self.symbols}

    def fetch_prices_batch(self, symbols: list[str] | None = None) -> dict[str, float]:
        """여러 심볼 현재가 일괄 조회 (최대 100개)"""
        target = symbols or self.symbols
        self._limiter.wait()
        return pyupbit.get_current_price(target[:100])
```

---

## 13) CoinMarketCap API 기반 시장 데이터 연동

> 참고: [CoinMarketCap API Documentation](https://coinmarketcap.com/api/documentation/v1/)

### CoinMarketCap API 개요

CoinMarketCap API는 **시장 데이터 중심** API로, 뉴스 콘텐츠보다는 가격/시총/거래량 데이터에 특화되어 있습니다.

| 항목 | Basic (무료) |
|------|-------------|
| 월간 크레딧 | 10,000 credits |
| 분당 요청 | 30 requests/min |
| 엔드포인트 | 11개 기본 엔드포인트 |
| 데이터 갱신 | 1분 주기 |
| 히스토리컬 | ❌ 미지원 |
| 상업적 사용 | ❌ 개인용만 |

### 크레딧 시스템

- 기본적으로 **100 데이터 포인트당 1 크레딧** 소비
- 10,000 크레딧 ≈ **일 333회** 호출 (월 기준)
- 엔드포인트별 크레딧 소비량이 다름

### 사용 가능한 주요 엔드포인트 (Basic Plan)

| 엔드포인트 | 용도 | 크레딧 |
|-----------|------|--------|
| `/v1/cryptocurrency/listings/latest` | 코인 목록 + 시세 | 1/100 items |
| `/v1/cryptocurrency/quotes/latest` | 특정 코인 시세 | 1/coin |
| `/v1/cryptocurrency/info` | 코인 메타데이터 | 1/coin |
| `/v2/cryptocurrency/quotes/latest` | 시세 (v2) | 1/coin |
| `/v1/global-metrics/quotes/latest` | 글로벌 시장 지표 | 1 |
| `/v1/tools/price-conversion` | 가격 변환 | 1 |

### CoinMarketCap API Provider 구현

```python
import requests
from dataclasses import dataclass
from datetime import datetime
from typing import Any

@dataclass
class CMCQuote:
    """CoinMarketCap 시세 데이터"""
    symbol: str
    name: str
    price_usd: float
    price_krw: float | None
    market_cap: float
    volume_24h: float
    percent_change_1h: float
    percent_change_24h: float
    percent_change_7d: float
    last_updated: datetime
    cmc_rank: int

@dataclass
class GlobalMetrics:
    """글로벌 시장 지표"""
    total_market_cap_usd: float
    total_volume_24h_usd: float
    btc_dominance: float
    eth_dominance: float
    active_cryptocurrencies: int
    last_updated: datetime

class CoinMarketCapProvider:
    """CoinMarketCap API 클라이언트"""

    BASE_URL = "https://pro-api.coinmarketcap.com"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({
            "X-CMC_PRO_API_KEY": api_key,
            "Accept": "application/json"
        })
        self._limiter = RateLimiter(calls_per_second=0.5)  # 30/min = 0.5/sec

    def get_quotes(self, symbols: list[str]) -> dict[str, CMCQuote]:
        """특정 심볼들의 현재 시세 조회"""
        self._limiter.wait()

        # KRW-BTC -> BTC 형태로 변환
        clean_symbols = [s.replace("KRW-", "").replace("USDT-", "") for s in symbols]

        resp = self._session.get(
            f"{self.BASE_URL}/v1/cryptocurrency/quotes/latest",
            params={
                "symbol": ",".join(clean_symbols),
                "convert": "USD,KRW"  # 원화 환산도 요청
            }
        )
        resp.raise_for_status()
        data = resp.json()

        quotes = {}
        for symbol, info in data.get("data", {}).items():
            usd_quote = info.get("quote", {}).get("USD", {})
            krw_quote = info.get("quote", {}).get("KRW", {})

            quotes[symbol] = CMCQuote(
                symbol=symbol,
                name=info.get("name", ""),
                price_usd=usd_quote.get("price", 0),
                price_krw=krw_quote.get("price") if krw_quote else None,
                market_cap=usd_quote.get("market_cap", 0),
                volume_24h=usd_quote.get("volume_24h", 0),
                percent_change_1h=usd_quote.get("percent_change_1h", 0),
                percent_change_24h=usd_quote.get("percent_change_24h", 0),
                percent_change_7d=usd_quote.get("percent_change_7d", 0),
                last_updated=datetime.fromisoformat(
                    usd_quote.get("last_updated", "").replace("Z", "+00:00")
                ),
                cmc_rank=info.get("cmc_rank", 0)
            )
        return quotes

    def get_global_metrics(self) -> GlobalMetrics:
        """글로벌 시장 지표 조회"""
        self._limiter.wait()

        resp = self._session.get(
            f"{self.BASE_URL}/v1/global-metrics/quotes/latest"
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})

        usd_quote = data.get("quote", {}).get("USD", {})
        return GlobalMetrics(
            total_market_cap_usd=usd_quote.get("total_market_cap", 0),
            total_volume_24h_usd=usd_quote.get("total_volume_24h", 0),
            btc_dominance=data.get("btc_dominance", 0),
            eth_dominance=data.get("eth_dominance", 0),
            active_cryptocurrencies=data.get("active_cryptocurrencies", 0),
            last_updated=datetime.fromisoformat(
                usd_quote.get("last_updated", "").replace("Z", "+00:00")
            )
        )

    def get_top_gainers_losers(self, limit: int = 10) -> dict[str, list[CMCQuote]]:
        """상위 상승/하락 코인 조회"""
        self._limiter.wait()

        resp = self._session.get(
            f"{self.BASE_URL}/v1/cryptocurrency/listings/latest",
            params={
                "limit": 100,
                "sort": "percent_change_24h",
                "sort_dir": "desc",
                "convert": "USD"
            }
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])

        all_quotes = []
        for coin in data:
            usd_quote = coin.get("quote", {}).get("USD", {})
            all_quotes.append(CMCQuote(
                symbol=coin.get("symbol", ""),
                name=coin.get("name", ""),
                price_usd=usd_quote.get("price", 0),
                price_krw=None,
                market_cap=usd_quote.get("market_cap", 0),
                volume_24h=usd_quote.get("volume_24h", 0),
                percent_change_1h=usd_quote.get("percent_change_1h", 0),
                percent_change_24h=usd_quote.get("percent_change_24h", 0),
                percent_change_7d=usd_quote.get("percent_change_7d", 0),
                last_updated=datetime.fromisoformat(
                    usd_quote.get("last_updated", "").replace("Z", "+00:00")
                ),
                cmc_rank=coin.get("cmc_rank", 0)
            ))

        return {
            "gainers": all_quotes[:limit],
            "losers": list(reversed(all_quotes[-limit:]))
        }
```

### 뉴스 데이터 대안 전략

CoinMarketCap Basic 플랜은 **뉴스 엔드포인트를 제공하지 않습니다**. 따라서 뉴스 분석은 다음 대안을 활용합니다:

```
┌─────────────────────────────────────────────────────────────┐
│              뉴스 데이터 수집 전략                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1차: CoinMarketCap 시장 데이터                             │
│       → 가격 변동률, 거래량 급등, 시총 변화                  │
│       → "뉴스 없이도 감지 가능한 시장 이벤트"               │
│                                                             │
│  2차: 무료 RSS 피드 직접 파싱                               │
│       → CoinDesk, CoinTelegraph RSS                        │
│       → 제목 + 발행 시간만 수집 (본문 없음)                 │
│                                                             │
│  3차: LLM 기반 뉴스 요약 (수동 입력)                        │
│       → 사용자가 중요 뉴스 텍스트 직접 입력                 │
│       → LLM이 요약/감성 분석                                │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### RSS 기반 뉴스 수집기 (무료 대안)

```python
import feedparser
from dataclasses import dataclass
from datetime import datetime

@dataclass
class NewsHeadline:
    """RSS 기반 뉴스 헤드라인"""
    title: str
    source: str
    published_at: datetime
    url: str
    # 본문은 RSS에서 제한적 (대부분 요약만 제공)

class RSSNewsCollector:
    """무료 RSS 피드 기반 뉴스 수집"""

    RSS_FEEDS = {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "CoinTelegraph": "https://cointelegraph.com/rss",
        "Bitcoin Magazine": "https://bitcoinmagazine.com/feed",
    }

    def fetch_headlines(self, limit: int = 20) -> list[NewsHeadline]:
        """모든 RSS 피드에서 최신 헤드라인 수집"""
        headlines = []

        for source, url in self.RSS_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:limit]:
                    published = entry.get("published_parsed")
                    headlines.append(NewsHeadline(
                        title=entry.get("title", ""),
                        source=source,
                        published_at=datetime(*published[:6]) if published else datetime.now(),
                        url=entry.get("link", "")
                    ))
            except Exception:
                continue

        # 최신순 정렬
        headlines.sort(key=lambda x: x.published_at, reverse=True)
        return headlines[:limit]

    def filter_btc_news(self, headlines: list[NewsHeadline]) -> list[NewsHeadline]:
        """BTC 관련 뉴스 필터링"""
        keywords = ["bitcoin", "btc", "비트코인", "satoshi", "halving"]
        return [
            h for h in headlines
            if any(kw in h.title.lower() for kw in keywords)
        ]
```

### 시장 이상 감지 (뉴스 대용)

```python
@dataclass
class MarketAnomaly:
    """시장 이상 감지 결과"""
    anomaly_type: str        # "volume_spike" | "price_surge" | "dominance_shift"
    severity: str            # "high" | "medium" | "low"
    description: str
    detected_at: datetime
    related_symbol: str | None

class MarketAnomalyDetector:
    """CoinMarketCap 데이터 기반 시장 이상 감지"""

    def __init__(self, cmc: CoinMarketCapProvider):
        self.cmc = cmc
        self._prev_metrics: GlobalMetrics | None = None
        self._prev_quotes: dict[str, CMCQuote] = {}

    def detect_anomalies(self, symbols: list[str] = ["BTC"]) -> list[MarketAnomaly]:
        """시장 이상 감지"""
        anomalies = []

        # 현재 데이터 수집
        current_quotes = self.cmc.get_quotes(symbols)
        current_metrics = self.cmc.get_global_metrics()

        for symbol, quote in current_quotes.items():
            # 1시간 급등락 감지 (±5% 이상)
            if abs(quote.percent_change_1h) >= 5:
                direction = "급등" if quote.percent_change_1h > 0 else "급락"
                anomalies.append(MarketAnomaly(
                    anomaly_type="price_surge",
                    severity="high" if abs(quote.percent_change_1h) >= 10 else "medium",
                    description=f"{symbol} 1시간 {direction}: {quote.percent_change_1h:+.2f}%",
                    detected_at=datetime.now(),
                    related_symbol=symbol
                ))

            # 이전 데이터와 거래량 비교
            if symbol in self._prev_quotes:
                prev = self._prev_quotes[symbol]
                volume_change = (quote.volume_24h - prev.volume_24h) / prev.volume_24h * 100
                if volume_change >= 50:  # 50% 이상 거래량 증가
                    anomalies.append(MarketAnomaly(
                        anomaly_type="volume_spike",
                        severity="high" if volume_change >= 100 else "medium",
                        description=f"{symbol} 거래량 급증: {volume_change:+.1f}%",
                        detected_at=datetime.now(),
                        related_symbol=symbol
                    ))

        # BTC 도미넌스 급변 감지
        if self._prev_metrics:
            dom_change = current_metrics.btc_dominance - self._prev_metrics.btc_dominance
            if abs(dom_change) >= 1:  # 1%p 이상 변화
                anomalies.append(MarketAnomaly(
                    anomaly_type="dominance_shift",
                    severity="medium",
                    description=f"BTC 도미넌스 변화: {dom_change:+.2f}%p",
                    detected_at=datetime.now(),
                    related_symbol="BTC"
                ))

        # 상태 업데이트
        self._prev_quotes = current_quotes
        self._prev_metrics = current_metrics

        return anomalies
```

### 크레딧 사용 계획 (일일 예산)

```yaml
# 일일 크레딧 예산: 333 credits (10,000 / 30일)

routine_calls:
  quotes_btc:           # 5분 주기 x 288회 = 288 credits
    endpoint: /v1/cryptocurrency/quotes/latest
    symbols: ["BTC"]
    interval: 5min
    daily_credits: ~3 (1 credit x 3 symbols 기준)

  global_metrics:       # 30분 주기 x 48회 = 48 credits
    endpoint: /v1/global-metrics/quotes/latest
    interval: 30min
    daily_credits: 48

  top_movers:           # 1시간 주기 x 24회 = 24 credits
    endpoint: /v1/cryptocurrency/listings/latest
    limit: 100
    interval: 1hour
    daily_credits: 24

total_daily: ~120 credits (여유 있게 사용)
monthly_buffer: ~6,400 credits 여유
```

---

## 14) 통합 아키텍처 다이어그램

```
┌──────────────────────────────────────────────────────────────────────┐
│                       LangGraph Orchestrator                          │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐     │
│  │ Market Agent    │   │ News Agent      │   │ Indicator Agent │     │
│  │                 │   │                 │   │                 │     │
│  └────────┬────────┘   └────────┬────────┘   └────────┬────────┘     │
│           │                     │                     │              │
│           ▼                     ▼                     ▼              │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐     │
│  │ CoinMarketCap   │   │ RSS Collector   │   │ pandas-ta       │     │
│  │ (시세/변동률)    │   │ (헤드라인)       │   │ (지표 계산)      │     │
│  └─────────────────┘   └─────────────────┘   └─────────────────┘     │
│           │                     │                     │              │
│           │            ┌─────────────────┐            │              │
│           │            │ Anomaly Detector│            │              │
│           └───────────▶│ (이상 감지)      │◀───────────┘              │
│                        └────────┬────────┘                           │
│                                 ▼                                    │
│                        ┌─────────────────┐                           │
│                        │ LLM Decision    │                           │
│                        │ (Proposal 생성) │                           │
│                        └────────┬────────┘                           │
│                                 ▼                                    │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐     │
│  │ Risk Manager    │◀─▶│ Execution Agent │──▶│ Ops/Alert Agent │     │
│  │ (검증/차단)      │   │ (주문 실행)      │   │ (모니터링/알림)  │     │
│  └─────────────────┘   └────────┬────────┘   └─────────────────┘     │
│                                 │                                    │
│                                 ▼                                    │
│                        ┌─────────────────┐                           │
│                        │ UpbitBroker     │                           │
│                        │ Adapter         │                           │
│                        │ (pyupbit)       │                           │
│                        └────────┬────────┘                           │
│                                 │                                    │
└─────────────────────────────────┼────────────────────────────────────┘
                                  ▼
                   ┌──────────────────────────┐
                   │        Upbit             │
                   │       Exchange           │
                   └──────────────────────────┘
```

### 데이터 흐름

```
1. 시세 수집
   pyupbit (OHLCV) ──────────────────────────┐
   CoinMarketCap (변동률/글로벌) ─────────────┼──▶ MarketSnapshot
                                             │
2. 뉴스/이벤트                                │
   RSS Headlines ────────────────────────────┼──▶ NewsContext
   시장 이상 감지 (CMC 데이터 기반) ───────────┘

3. 지표 계산
   MarketSnapshot ──▶ pandas-ta ──▶ IndicatorSignals

4. 의사결정
   MarketSnapshot + NewsContext + IndicatorSignals ──▶ LLM ──▶ Proposal

5. 검증 및 실행
   Proposal ──▶ RiskManager (검증) ──▶ ExecutionAgent ──▶ pyupbit (주문)
```

---

## 15) MVP 기술 스택 확정

```yaml
# Python 버전
python: ">=3.12"

# 거래소 연동 (주문/체결)
exchange: Upbit (KRW-BTC)
library:
  - pyupbit >= 0.2.0
  - pyjwt >= 2.0
auth: API Key + Secret Key (조회/주문 분리 권장)

# 시장 데이터 (보조)
market_data:
  provider: CoinMarketCap API (Basic Plan)
  library: requests
  features:
    - 글로벌 시장 지표 (BTC 도미넌스, 총 시총)
    - 코인별 변동률 (1h/24h/7d)
    - 상승/하락 랭킹
  limits:
    monthly_credits: 10,000
    rate_limit: 30 req/min

# 뉴스 수집 (무료)
news:
  primary: RSS 피드 (CoinDesk, CoinTelegraph)
  library: feedparser
  features:
    - 헤드라인 수집
    - BTC 키워드 필터링
  note: 본문 없음, LLM으로 제목 기반 감성 분석

# 지표 계산
indicators:
  - pandas-ta  # 순수 Python, 설치 간편

# 오케스트레이션
framework:
  - langgraph
  - langchain-anthropic  # Claude API
llm: Claude API (의사결정 계층)

# 데이터 저장
database:
  - SQLite (MVP)
  - PostgreSQL + TimescaleDB (확장 시)
logs:
  - 로컬 JSON 파일 (MVP)

# 알림
alerts:
  - Slack Webhook (MVP)
```

### 환경 변수 템플릿 (.env.example)

```bash
# Upbit API (조회/주문 분리 권장)
UPBIT_ACCESS_KEY=your-access-key
UPBIT_SECRET_KEY=your-secret-key

# CoinMarketCap API
CMC_API_KEY=your-cmc-api-key

# Claude API
ANTHROPIC_API_KEY=your-anthropic-key

# 알림 (선택)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# 운영 모드
TRADING_MODE=paper  # paper | live
MAX_DAILY_LOSS_PCT=3.0
MAX_POSITION_PCT=50.0
```

---

## 16) API 연동 테스트 체크리스트

### Upbit API (pyupbit) 테스트

- [ ] **인증**: API 키 유효성 확인
- [ ] **잔고 조회**: `get_balance()`, `get_balances()` 동작 확인
- [ ] **시세 조회**: `get_current_price()`, `get_ohlcv()` 응답 확인
- [ ] **호가 조회**: `get_orderbook()` 응답 확인
- [ ] **페이퍼 주문**: 테스트넷 또는 최소 금액으로 주문 테스트
- [ ] **레이트리밋**: 연속 호출 시 429 에러 발생 여부

### CoinMarketCap API 테스트

- [ ] **인증**: API 키 유효성 확인 (X-CMC_PRO_API_KEY 헤더)
- [ ] **시세 조회**: `/v1/cryptocurrency/quotes/latest` 응답 확인
- [ ] **글로벌 지표**: `/v1/global-metrics/quotes/latest` 응답 확인
- [ ] **크레딧 확인**: 응답 헤더에서 남은 크레딧 확인
- [ ] **레이트리밋**: 30 req/min 제한 테스트

### RSS 피드 테스트

- [ ] **CoinDesk RSS**: 파싱 성공 여부
- [ ] **CoinTelegraph RSS**: 파싱 성공 여부
- [ ] **BTC 필터링**: 키워드 기반 필터링 동작

### 테스트 스크립트

```python
import pyupbit
import requests
import feedparser
from datetime import datetime

def test_upbit_api(access_key: str, secret_key: str) -> dict:
    """Upbit API 연동 테스트"""
    results = {"success": True, "errors": []}

    try:
        # 1. 시세 조회 (인증 불필요)
        price = pyupbit.get_current_price("KRW-BTC")
        print(f"✓ BTC 현재가: {price:,.0f} KRW")

        # 2. OHLCV 조회
        ohlcv = pyupbit.get_ohlcv("KRW-BTC", interval="minute1", count=5)
        print(f"✓ OHLCV: {len(ohlcv)} candles")

        # 3. 인증 필요 기능
        upbit = pyupbit.Upbit(access_key, secret_key)
        balances = upbit.get_balances()
        print(f"✓ 잔고 조회: {len(balances)} assets")

    except Exception as e:
        results["success"] = False
        results["errors"].append(str(e))
        print(f"✗ Error: {e}")

    return results

def test_cmc_api(api_key: str) -> dict:
    """CoinMarketCap API 연동 테스트"""
    results = {"success": True, "credits_used": 0}

    headers = {
        "X-CMC_PRO_API_KEY": api_key,
        "Accept": "application/json"
    }

    try:
        # 1. BTC 시세 조회
        resp = requests.get(
            "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest",
            headers=headers,
            params={"symbol": "BTC", "convert": "USD"}
        )
        resp.raise_for_status()
        data = resp.json()

        btc = data["data"]["BTC"]
        price = btc["quote"]["USD"]["price"]
        print(f"✓ BTC 가격: ${price:,.2f}")

        # 크레딧 사용량 확인
        credits = resp.headers.get("X-CMC_PRO_API_Credit_Count", "?")
        print(f"✓ 크레딧 사용: {credits}")

        # 2. 글로벌 지표
        resp2 = requests.get(
            "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest",
            headers=headers
        )
        resp2.raise_for_status()
        global_data = resp2.json()["data"]
        print(f"✓ BTC 도미넌스: {global_data['btc_dominance']:.2f}%")

    except Exception as e:
        results["success"] = False
        print(f"✗ Error: {e}")

    return results

def test_rss_feeds() -> dict:
    """RSS 피드 테스트"""
    feeds = {
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "CoinTelegraph": "https://cointelegraph.com/rss",
    }

    results = {}
    for name, url in feeds.items():
        try:
            feed = feedparser.parse(url)
            entries = feed.entries[:5]
            btc_news = [e for e in entries if "bitcoin" in e.title.lower() or "btc" in e.title.lower()]
            print(f"✓ {name}: {len(entries)} articles, {len(btc_news)} BTC-related")
            results[name] = {"success": True, "count": len(entries)}
        except Exception as e:
            print(f"✗ {name}: {e}")
            results[name] = {"success": False, "error": str(e)}

    return results

if __name__ == "__main__":
    import os

    print("=== Upbit API Test ===")
    test_upbit_api(
        os.getenv("UPBIT_ACCESS_KEY", ""),
        os.getenv("UPBIT_SECRET_KEY", "")
    )

    print("\n=== CoinMarketCap API Test ===")
    test_cmc_api(os.getenv("CMC_API_KEY", ""))

    print("\n=== RSS Feeds Test ===")
    test_rss_feeds()
```

---

## 17) 프로젝트 디렉토리 구조 (권장)

```
auto-trading/
├── pyproject.toml              # 의존성 관리 (poetry/uv)
├── .env.example                # 환경변수 템플릿
├── .gitignore
├── README.md
├── llm_trading_agent_plan.md   # 이 문서
│
├── src/
│   └── trading/
│       ├── __init__.py
│       ├── config.py           # 설정 로드/검증
│       │
│       ├── adapters/           # 외부 시스템 어댑터
│       │   ├── __init__.py
│       │   ├── broker.py       # BrokerAdapter (추상)
│       │   ├── upbit.py        # UpbitBrokerAdapter (pyupbit)
│       │   ├── coinmarketcap.py # CoinMarketCapProvider
│       │   ├── rss_collector.py # RSSNewsCollector
│       │   └── market_data.py  # UpbitMarketDataAgent
│       │
│       ├── agents/             # Sub-agent 구현
│       │   ├── __init__.py
│       │   ├── market_agent.py    # 시장 데이터 수집
│       │   ├── news_agent.py      # 뉴스/이벤트 분석
│       │   ├── indicator_agent.py # 지표 계산
│       │   ├── decision_agent.py  # LLM 의사결정
│       │   ├── risk_agent.py      # 리스크 검증
│       │   ├── execution_agent.py # 주문 실행
│       │   └── ops_agent.py       # 모니터링/알림
│       │
│       ├── core/               # 핵심 도메인 모델
│       │   ├── __init__.py
│       │   ├── models.py       # OrderRequest, MarketSnapshot, CMCQuote 등
│       │   ├── state.py        # LangGraph State 스키마
│       │   ├── events.py       # 이벤트 정의
│       │   └── anomaly.py      # MarketAnomaly, AnomalyDetector
│       │
│       ├── graph/              # LangGraph 오케스트레이션
│       │   ├── __init__.py
│       │   ├── nodes.py        # 그래프 노드들
│       │   ├── edges.py        # 조건부 라우팅
│       │   └── builder.py      # 그래프 빌더
│       │
│       ├── indicators/         # 기술적 지표
│       │   ├── __init__.py
│       │   ├── trend.py        # 추세 지표 (SMA, EMA, MACD)
│       │   ├── momentum.py     # 모멘텀 지표 (RSI, Stochastic)
│       │   └── volatility.py   # 변동성 지표 (ATR, BB)
│       │
│       ├── risk/               # 리스크 관리
│       │   ├── __init__.py
│       │   ├── limits.py       # 손실/포지션 제한
│       │   ├── sizing.py       # 포지션 사이징
│       │   └── validator.py    # LLM 결정 검증
│       │
│       ├── llm/                # LLM 관련
│       │   ├── __init__.py
│       │   ├── prompts.py      # 프롬프트 템플릿
│       │   ├── schemas.py      # 입출력 스키마
│       │   └── client.py       # Claude API 클라이언트
│       │
│       └── utils/              # 유틸리티
│           ├── __init__.py
│           ├── rate_limiter.py # RateLimiter
│           └── logging.py      # 로깅 설정
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_adapters/
│   │   ├── test_upbit.py
│   │   ├── test_coinmarketcap.py
│   │   └── test_rss.py
│   ├── test_agents/
│   ├── test_risk/
│   └── test_llm/
│
├── scripts/
│   ├── test_apis.py            # API 연동 테스트 (위 섹션 참조)
│   ├── run_paper_trading.py    # 페이퍼 트레이딩 실행
│   └── backtest.py             # 백테스트
│
└── data/                       # 로컬 데이터 (gitignore)
    ├── logs/
    ├── snapshots/
    └── trades.db
```
