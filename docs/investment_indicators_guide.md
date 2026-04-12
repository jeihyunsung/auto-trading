# 매수 근거 체크리스트 — 지표 설명 및 확인 방법

작성일: 2026-04-05

---

## 체크리스트 요약

```
□ 차트      — 이격도, RSI 과매도, 주요 지지선
□ 유동성    — TGA 감소 추세, Fed 완화 방향, 역레포 변화
□ 정책      — 금리 인하 시그널, 재정 확대 기조
□ 지정학    — 충격 이벤트 피크아웃 (악재 소화 단계)
□ 모멘텀    — 선도 섹터 존재, 실적 서프라이즈
```

---

## 1. 차트

차트는 예측 도구가 아니라 "시장 참여자들이 어떤 상태인가"를 읽는 도구.

### 이격도 (Disparity Index)

현재 가격이 이동평균선에서 얼마나 떨어져 있는지 보여주는 지표.

```
이격도 = (현재 가격 / 이동평균선) × 100 - 100

예시: 나스닥 200일 이동평균 = 18,000, 현재 가격 = 13,500
      이격도 = (13,500 / 18,000) × 100 - 100 = -25%
```

고무줄처럼 생각하면 된다. 평균에서 멀어질수록 되돌아오려는 힘이 강해진다.

| 이격도 | 상태 | 의미 |
|--------|------|------|
| -25% 이하 | 극단적 과매도 | 반등 확률 높음 |
| -10~-25% | 과매도 | 관심 구간 |
| -10~+10% | 정상 | 평균 근처 |
| +10~+20% | 과매수 | 주의 |
| +20% 이상 | 극단적 과열 | 조정 가능성 높음 |

**확인 방법:**
- TradingView: https://www.tradingview.com/chart/
- 심볼: `NASDAQ:QQQ` 또는 `NASDAQ:NDX` 입력
- 상단 "지표(Indicators)" 클릭 → "Disparity Index" 검색
- 커뮤니티 스크립트에서 "Disparity Index" 선택
- 대안: "Moving Average Envelope" 검색 — 가격과 이동평균의 괴리를 시각화
- 설정: 기간을 200일로 설정하면 장기 이격도 확인 가능

### RSI (Relative Strength Index, 상대강도지수)

최근 14일간 상승폭 vs 하락폭의 비율. "너무 많이 올랐나, 너무 많이 내렸나"를 0~100으로 표현.

| RSI | 상태 | 의미 |
|-----|------|------|
| 0~20 | 극단적 과매도 | 팔 사람은 거의 다 팔았다 |
| 20~30 | 과매도 | 관심 구간 |
| 30~70 | 중립 | 특별한 신호 없음 |
| 70~80 | 과매수 | 단기 조정 가능 |
| 80~100 | 극단적 과열 | 하락 가능성 |

**확인 방법:**
- TradingView: https://www.tradingview.com/chart/?symbol=NASDAQ:QQQ
- 상단 "지표(Indicators)" 클릭 → "RSI" 검색
- 기본 내장 지표 "Relative Strength Index" 선택 (기본 기간: 14일)
- 차트 하단에 RSI 라인이 표시됨
- 30 이하 / 70 이상 구간에 자동으로 음영 표시

### 주요 지지선

가격이 하락할 때 매수세가 몰려 반등하는 가격대. 두 가지 유형이 있다.

#### 유형 1: 수평 지지선 (횡보/반등 구간이 있는 차트)

과거에 가격이 2회 이상 비슷한 수준에서 반등한 가격대.

```
예시: 나스닥이 15,000에서 3번 반등 → 15,000이 지지선
      그 가격대에서 "싸다"고 판단하는 매수자가 많기 때문
```

- 현재 가격이 지지선 **±2% 이내**면 "도달"로 판단
- 지지선에서 **양봉 출현** → 반등 시작 신호
- 지지선을 **종가 기준으로 이탈** → 그 지지선은 무효, 다음 지지선 확인

#### 유형 2: 피보나치 되돌림 (쭉 올라간 차트)

QQQ처럼 뚜렷한 반등 지점 없이 장기 상승한 차트에서는 수평 지지선이 거의 없다.
이런 경우 **피보나치 되돌림(Fibonacci Retracement)** 으로 지지 가격대를 추정한다.

```
피보나치 되돌림 = 상승폭의 일정 비율만큼 되돌아갈 때의 가격

계산법:
  상승 시작점(저점): A
  고점: B
  상승폭: B - A

  38.2% 되돌림 = B - (B - A) × 0.382  ← 1차 지지
  50.0% 되돌림 = B - (B - A) × 0.500  ← 2차 지지
  61.8% 되돌림 = B - (B - A) × 0.618  ← 3차 지지 (여기 깨지면 상승 추세 자체 의심)
```

| 되돌림 비율 | 의미 | 판단 |
|------------|------|------|
| **38.2%** | 건강한 조정, 상승 추세 유지 | 관심 구간 |
| **50.0%** | 상승분의 절반 반납 | 적극 관심 |
| **61.8%** | 황금비율, 마지막 지지선 | 여기서 반등 못 하면 추세 전환 |

**확인 방법:**
- TradingView: https://www.tradingview.com/chart/?symbol=NASDAQ:QQQ
- **피보나치 되돌림 그리기:**
  1. 왼쪽 도구바 → 세 번째 아이콘(기울어진 선) 클릭 → "피보나치 되돌림" 선택
  2. **상승 시작점(저점)** 에서 클릭 → **고점**까지 드래그
  3. 자동으로 38.2%, 50%, 61.8% 수평선이 표시됨
  4. 현재 가격이 어떤 선에 근접한지 확인
- **이동평균선 (동적 지지선):**
  1. 상단 "Indicators" → "MA" 검색 → Moving Average 추가
  2. 기간을 **200일**로 설정
  3. 가격이 200일선에 닿으면 = 이격도 0%, 동적 지지선 도달
  4. 사실상 이격도와 같은 개념 — 이격도가 지지선 역할을 대체

#### 어떤 유형을 쓸지 판단

```
차트에 뚜렷한 반등 지점이 2회 이상 보이는가?
├── YES → 수평 지지선 사용
└── NO  → 피보나치 되돌림 + 200일 이동평균 사용
```

> **참고:** 장기 상승 차트에서는 이격도(200일선 대비)가 사실상 지지선의 역할을 한다.
> 이격도 -10% = 200일선 아래 10% = 동적 지지선 아래로 진입한 상태.

---

## 2. 유동성

시장에 돈이 얼마나 풀려 있고, 앞으로 더 풀릴 건지 줄어들 건지. 주가는 결국 돈의 흐름을 따른다.

### TGA (Treasury General Account, 재무부 일반계정)

미국 정부의 "통장 잔고". 정부가 돈을 쓰면 시중에 유동성이 공급된다.

```
TGA 감소 = 정부가 돈을 쓰는 중 = 시중에 돈이 풀림 = 주가 상승 압력
TGA 증가 = 정부가 돈을 모으는 중 = 시중에서 돈이 빠짐 = 주가 하락 압력
```

**확인 방법:**
- FRED: https://fred.stlouisfed.org/series/WTREGEN
- 시리즈: WTREGEN — "U.S. Treasury, General Account, Weekly"
- 직접 접속하면 차트가 바로 보임
- "Edit Graph" 클릭해서 날짜 범위 조정 가능
- 업데이트: 매주 수요일
- 무료, 회원가입 불필요

**읽는 법:**
- 차트가 우하향 = TGA 감소 중 = 유동성 공급 = 긍정적
- 차트가 우상향 = TGA 증가 중 = 유동성 회수 = 부정적

### Fed 대차대조표 (Balance Sheet)

Fed가 보유한 자산의 총규모. Fed가 채권을 사면 시중에 돈이 풀리고, 팔면 돈이 빠진다.

```
대차대조표 증가 = 양적완화(QE), 돈을 푸는 중 = 주가 상승 압력
대차대조표 감소 = 양적긴축(QT), 돈을 거두는 중 = 주가 하락 압력
```

**확인 방법:**
- FRED: https://fred.stlouisfed.org/series/WALCL
- 시리즈: WALCL — "Assets: Total Assets (Less Eliminations from Consolidation)"
- 업데이트: 매주 수요일
- 무료, 회원가입 불필요

### 역레포 (Reverse Repo, RRP)

금융기관들이 남는 현금을 Fed에 하루짜리로 맡기는 것.

```
역레포 잔고 감소 = 돈이 시장으로 이동 중 = 주가 상승 압력
역레포 잔고 증가 = 돈이 시장에서 빠짐 = 주가 하락 압력
역레포 0에 수렴 = 더 이상 풀 돈이 없음 = 유동성 공급 한계
```

**확인 방법:**
- FRED: https://fred.stlouisfed.org/series/RRPONTSYD
- 시리즈: RRPONTSYD — "Overnight Reverse Repurchase Agreements"
- 뉴욕 연준: https://www.newyorkfed.org/markets/desk-operations/reverse-repo
  - 일별 RRP 운용 결과, 참여 기관 수, 총 금액 확인 가능
- 무료, 회원가입 불필요

### 유동성 종합 판단

```
TGA 감소 + Fed 대차대조표 확대 + 역레포 감소
= 세 곳에서 돈이 풀리는 중 → 유동성 체크 충족

TGA 증가 + Fed 대차대조표 축소 + 역레포 증가
= 세 곳에서 돈이 빠지는 중 → 유동성 불리
```

---

## 3. 정책

정부와 중앙은행이 앞으로 경제를 어떤 방향으로 끌고 가려 하는가.

### 금리 방향 — CME FedWatch Tool

시장 참여자들이 예상하는 다음 FOMC 회의에서의 금리 변동 확률.

| FedWatch 확률 | 해석 |
|---------------|------|
| 70% 이상 인하 예상 | 시장은 인하를 기정사실화 |
| 30~70% | 불확실, 데이터에 따라 변동 |
| 30% 미만 인하 예상 | 인하 가능성 낮음 |

**확인 방법:**
- CME FedWatch: https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html
- 접속하면 바로 다음 FOMC 회의별 금리 확률이 막대그래프로 표시
- 각 회의 날짜를 클릭하면 상세 확률 분포 확인 가능
- 무료, 회원가입 불필요

### FOMC 일정 및 회의록

Fed가 금리를 결정하는 회의. 연 8회 개최.

**확인 방법:**
- FOMC 일정: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
  - 올해/내년 회의 날짜, 성명서, 회의록 링크 모두 제공
- FOMC 회의록: https://www.federalreserve.gov/monetarypolicy/fomc_minutes.htm
  - 회의 3주 후 공개. 위원들의 논의 내용, 경제 전망 포함
- 무료

### Fed 점도표 (Dot Plot)

Fed 위원들(18명)이 각자 예상하는 미래 금리를 점으로 표시한 차트. 분기별(3, 6, 9, 12월 회의) 공개.

```
점들이 아래에 몰림 = 위원들이 금리 인하를 예상 = 완화적
점들이 위에 몰림 = 위원들이 금리 인상/유지 예상 = 긴축적
```

**확인 방법:**
- Fed 공식: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
  - "Projection Materials" 링크가 있는 회의 → PDF 다운로드
  - "Summary of Economic Projections (SEP)" 안에 점도표 포함
- CME에서도 시각화 제공: FedWatch 페이지 내 Dot Plot 탭
- 무료

### 재정 정책 확인

```
재정 확대 = 인프라 투자, 보조금, 감세 → 경제에 돈 풀림 → 호재
재정 긴축 = 지출 삭감, 증세 → 경제 위축 → 악재
```

**확인 방법:**
- 뉴스 기반으로 확인 (정량 지표가 아닌 정성 판단)
- Reuters, Bloomberg, CNBC 등에서 미국 재정 정책 뉴스 추적
- 주요 키워드: infrastructure bill, stimulus, tax cut, spending cut, debt ceiling

---

## 4. 지정학

전쟁, 무역 갈등, 제재 등 정치적 이벤트의 시장 심리 충격.

### 피크아웃 판단법

악재 자체가 끝나지 않아도, 시장이 그 악재에 무감각해지는 순간이 피크아웃.

| 신호 | 의미 |
|------|------|
| 같은 뉴스에 주가가 더 이상 빠지지 않는다 | 악재 소화 중 |
| VIX가 고점 찍고 내려오기 시작 | 공포 피크아웃 |
| 안전자산(금, 달러, 국채)에서 돈이 빠진다 | 위험자산으로 복귀 시작 |
| 협상/회담 뉴스 등장 | 최악은 지나가는 중 |

### VIX (공포지수)

S&P 500 옵션의 내재 변동성. 시장의 공포 수준을 숫자로 표현.

| VIX | 상태 |
|-----|------|
| 12 이하 | 극단적 안정 (오히려 과열 주의) |
| 12~20 | 정상 |
| 20~30 | 불안 |
| 30~35 | 높은 공포 |
| 35 이상 | 극단적 공포 → 레버리지 진입 신호 중 하나 |

**확인 방법:**
- TradingView: https://www.tradingview.com/chart/?symbol=CBOE:VIX
- CBOE (공식): https://www.cboe.com/tradable_products/vix/
- Google에 "VIX" 검색하면 실시간 값 표시
- 무료

### Fear & Greed Index (공포/탐욕 지수)

CNN이 7가지 지표를 종합해서 0~100으로 시장 심리를 표현.

```
0~25:  극단적 공포 (Extreme Fear) → 반등 가능성 관심
25~45: 공포 (Fear)
45~55: 중립 (Neutral)
55~75: 탐욕 (Greed)
75~100: 극단적 탐욕 (Extreme Greed) → 과열 주의
```

**확인 방법:**
- CNN: https://edition.cnn.com/markets/fear-and-greed
- 접속하면 바로 현재 지수 + 구성 7가지 지표 확인 가능
- 7가지 구성: 시장 모멘텀, 주가 강도, 주가 폭, 풋/콜 비율, 정크본드 수요, 시장 변동성, 안전자산 수요
- 무료, 회원가입 불필요

---

## 5. 모멘텀/섹터

어떤 분야가 돈을 끌어당기고 있는가.

### 섹터 퍼포먼스

```
선도 섹터가 명확하다 = 돈의 방향이 있다 = 시장 건강
모든 섹터가 골고루 오른다 = 후반부일 수 있음 = 과열 주의
선도 섹터 없이 횡보 = 방향성 부재 = 관망
선도 섹터가 무너진다 = 시장 전체 하락 신호
```

**확인 방법:**
- Finviz 섹터 성과: https://finviz.com/groups.ashx?g=sector&v=140&o=-perf1w
  - 섹터별 1일/1주/1개월/3개월/6개월/1년 수익률 비교
  - 컬럼 헤더 클릭으로 정렬 가능
- Finviz 히트맵: https://finviz.com/map.ashx
  - 시장 전체를 섹터별 시각 히트맵으로 표시
  - 빨강 = 하락, 초록 = 상승, 크기 = 시가총액
- TradingView 섹터: https://www.tradingview.com/markets/us/sectorandindustry-performance/
- 무료

### 실적 서프라이즈 (Earnings Surprise)

기업 실적이 시장 예상(컨센서스)을 초과했는지 여부.

```
다수 기업 서프라이즈 = 경제가 예상보다 좋다 = 상승 근거
다수 기업 실적 미스 = 경제가 예상보다 나쁘다 = 하락 근거
가이던스 상향 = 앞으로도 좋다 = 강한 호재
가이던스 하향 = 실적은 좋았지만 앞으로 나쁘다 = 주의
```

실적 시즌: 1월, 4월, 7월, 10월에 집중 확인.

**확인 방법:**
- Yahoo Finance 실적 캘린더: https://finance.yahoo.com/calendar/earnings/
  - 날짜별 실적 발표 기업, 예상 EPS vs 실제 EPS 확인
- Finviz 캘린더: https://finviz.com/calendar.ashx
- Earnings Whispers: https://www.earningswhispers.com/calendar
  - 가장 기대되는 실적 발표를 시각적으로 표시
- 무료

---

## 6. 경제 기초체력 지표

레버리지 진입(전략 C) 판단과 전반적 경기 상태 확인용.

### 신규 실업수당 (Initial Jobless Claims)

매주 발표. 새로 실업급여를 신청한 사람 수.

```
30만 명 미만 = 고용시장 건재 = 경기침체 아닌 심리적 과매도
30만 명 이상 지속 = 고용 악화 신호 = 실제 경기침체 가능성
```

**확인 방법:**
- FRED: https://fred.stlouisfed.org/series/ICSA
- 시리즈: ICSA — "Initial Claims"
- 업데이트: 매주 목요일 오전 (미국 동부시간)
- 계속 실업수당: https://fred.stlouisfed.org/series/CCSA
- 무료, 회원가입 불필요

### CPI (Consumer Price Index, 소비자물가지수)

물가 상승률. Fed의 금리 결정에 가장 큰 영향을 미치는 지표.

```
CPI 하락 추세 = 인플레이션 둔화 = 금리 인하 가능성 = 주식 호재
CPI 상승 추세 = 인플레이션 가속 = 금리 인상 가능성 = 주식 악재
```

**확인 방법:**
- FRED (CPI 전체): https://fred.stlouisfed.org/series/CPIAUCSL
- BLS (공식): https://www.bls.gov/cpi/
- 발표 일정: https://www.bls.gov/schedule/news_release/cpi.htm
- 업데이트: 월 1회 (보통 매월 10~15일)
- 무료

### PMI (Purchasing Managers' Index, 구매관리자지수)

기업 구매 담당자에게 물어본 경기 체감 지수.

```
50 이상 = 경기 확장
50 미만 = 경기 수축
50 근처에서 방향이 중요 (상승 추세인지 하락 추세인지)
```

**확인 방법:**
- ISM (공식): https://www.ismworld.org/supply-management-news-and-reports/reports/ism-report-on-business/
  - 제조업 PMI + 서비스업 PMI
- Investing.com: https://www.investing.com/economic-calendar/ism-manufacturing-pmi-173
  - 예상치 vs 실제치 비교, 과거 데이터 포함
- 업데이트: 월 1회 (매월 첫 영업일)
- 무료 (ISM 헤드라인 숫자는 무료, 상세 리포트는 유료)

---

## 모니터링 루틴 요약

### 매주 확인 (주말 30분)

| 지표 | 소스 | 확인 내용 |
|------|------|----------|
| 이격도/RSI | TradingView | QQQ 과매도 구간인지 |
| TGA 잔고 | FRED WTREGEN | 감소 추세인지 |
| 역레포 | FRED RRPONTSYD | 감소 추세인지 |
| VIX | TradingView CBOE:VIX | 35 이상인지 |
| Fear & Greed | CNN | 극단적 공포 구간인지 |
| 섹터 퍼포먼스 | Finviz | 선도 섹터 존재 여부 |

### 매주 목요일

| 지표 | 소스 | 확인 내용 |
|------|------|----------|
| 신규 실업수당 | FRED ICSA | 30만 미만 유지 여부 |

### 월 1회 (발표일)

| 지표 | 소스 | 확인 내용 |
|------|------|----------|
| CPI | BLS / FRED | 인플레이션 방향 |
| PMI | ISM | 50 이상/이하, 방향 |

### FOMC 회의 전후

| 지표 | 소스 | 확인 내용 |
|------|------|----------|
| FedWatch 확률 | CME | 금리 인하/인상 확률 |
| 점도표 | Fed (분기별) | 위원들의 금리 전망 방향 |
| 회의록 | Fed (회의 3주 후) | 논의 내용, 완화/긴축 분위기 |

### 실적 시즌 (1월, 4월, 7월, 10월)

| 지표 | 소스 | 확인 내용 |
|------|------|----------|
| 실적 서프라이즈 | Yahoo Finance | 주요 기업 EPS 예상 vs 실제 |
| 가이던스 | Earnings Whispers | 향후 전망 상향/하향 |

---

## 전략 C 레버리지 진입 3신호 확인법

3가지가 **동시에** 충족될 때만 진입. 10년에 2~3번.

| 신호 | 기준 | 확인 소스 |
|------|------|----------|
| 이격도 -25% | 200일 이평 대비 -25% 이하 | TradingView — Disparity Index |
| VIX ≥ 35 | 공포 극점 | TradingView — CBOE:VIX |
| 신규 실업수당 < 30만 | 경제 기초체력 건재 | FRED — ICSA 시리즈 |

```
□ 이격도 -25% 이하?    → TradingView 확인
□ VIX 35 이상?         → TradingView 또는 Google "VIX" 검색
□ 실업수당 30만 미만?   → FRED ICSA 최신 데이터 확인

3개 모두 충족 → 레버리지 진입 고려 (비중 15% 이내, 익절 20~30%)
```
