---
name: trading-log-analysis
description: GCP에서 가동 중인 BTC auto-trading 봇의 운영 로그를 종합 분석. 사용자가 "지금까지 로그 분석", "봇 현황 봐줘", "오늘까지 거래 분석", "n일 지났는데 분석" 같은 요청을 할 때 자동 트리거. 봇 상태 / 격리 잔고 / 거래 detail / 결정 분포 / safety triggers / LLM 비용 + 새 패턴 발견 시 docs/TUNING_MEMORY.md에 사례 등록까지 일괄 실행.
---

# Trading Bot 운영 로그 분석

## When to use

다음 사용자 표현 중 하나라도 매치되면 즉시 이 skill 사용:
- "지금까지의 로그 분석해줘", "봇 현황", "오늘까지의 로그"
- "n일 지났는데 분석", "다시 분석", "한번 더 살펴봐줘"
- "거래 분석", "봇 동작 검토"

## Workflow

### Step 1: 데이터 수집 (단일 명령)

```bash
DAYS_BACK=4 scripts/analyze_bot_logs.sh
```

또는 특정 섹션만:
- `scripts/analyze_bot_logs.sh snapshot` — 봇 상태 + 잔고 + BTC 가격
- `scripts/analyze_bot_logs.sh trades` — 최근 거래 detail + rationale
- `scripts/analyze_bot_logs.sh decisions` — action 분포
- `scripts/analyze_bot_logs.sh safety` — stop-loss / take-profit / hysteresis 발동
- `scripts/analyze_bot_logs.sh llm` — OpenAI 호출/캐시/비용
- `scripts/analyze_bot_logs.sh recent` — 최근 30분 흐름

스크립트가 `gcloud compute ssh trading-bot --zone=asia-northeast3-a`로 VM에 접속해 systemd / journalctl / JSONL 로그를 한 번에 가져온다.

### Step 2: 분석 흐름

이 순서대로 보고서를 만든다:

1. **봇 안정성**: PID 가동 시간, watchdog healthy 여부, 재시작 흔적
2. **격리 잔고 P&L**: KRW + BTC × 현재가 = 총 평가액, initial 대비 P&L %
3. **거래 흐름**: 최근 BUY/SELL 시간순, 평균 매수가 vs 매도가 spread
4. **결정 분포**: HOLD/BUY/SELL 비율, confidence range
5. **Safety triggers 발동**: stop-loss / take-profit / hysteresis 차단 / BUY conf cap / same-direction cooldown
6. **LLM 효율**: 일평균 OpenAI 호출, 캐시 히트율, 비용 추정
7. **시장 대비 알파**: BTC 같은 기간 변동 vs 봇 P&L

### Step 3: 신규 패턴 발견 시 — TUNING_MEMORY.md에 case append

이건 [`tuning-memory-workflow`](~/.claude/projects/-Users-dawn-h-PycharmProjects-auto-trading/memory/tuning-memory-workflow.md) 메모리 룰 그대로:

- 신규 증상 (이전 케이스에 없음) → `docs/TUNING_MEMORY.md`의 `## Case Entries`에 append
- ID 형식 `#<category><n>`: h=Hysteresis, s=Stop-loss, t=Take-profit, l=LLM, o=Operations, p=Sizer, r=Validator
- 구조: Date · Symptom · Evidence (로그 인용) · Root cause · Status (Fixed / 미수정) · Possible fix · Related
- `## Index` 카테고리 줄과 `## Current Open Questions`에도 추가
- 이전에 [#l5] (5/29 BUY 정체) → [#l6] (5/31 RSI 22 HOLD) 같은 식으로 진행함

### Step 4: 사용자에게 보고

다음 형식으로 정리해서 출력:

```
# 📊 N일 분석 — <한 줄 요약>

## 💰 격리 잔고 변화 (어제 → 오늘 표)

## 📜 거래 흐름 (시간순)

## 🌡 의사결정 패턴 (HOLD/BUY/SELL 분포 + 핵심 케이스 1-2개)

## ✅ 안전장치 작동 검증 (이번 분석 기간)

## 🤖 봇 안정성 (PID, watchdog, freeze)

## 🆕 신규 사례 등록 (있을 때만)
[#xN] 한 줄 — TUNING_MEMORY.md에 등록됨

## 📈 시장 대비 알파 (Buy & Hold 비교)
```

## 주의사항

### 시간대 함정
- `journalctl --since "X 00:00:00 KST"`는 KST 인식 못 함 → **UTC로 변환해서 전달**
- `date -u -d "yesterday" +%Y-%m-%d` 사용
- 거래 JSONL은 KST timestamp 포함 — 이건 그대로 사용

### 보고하지 말아야 할 것
- LLM이 항상 HOLD라는 사실 자체 (그게 정상). **변화**만 보고.
- 트리거 수천 건 발동 — 정상 (rule-based, 비용 0)

### 이전 분석과 비교
- 매번 새 사례인지 기존 [#xN]과 같은 패턴인지 먼저 확인
- 같은 패턴이면 기존 case의 outcome 라인만 업데이트
- 다른 패턴이면 새 케이스 추가

## 알려진 한계

- VM 로그 timezone 파싱이 약함 → UTC로 통일
- pattern_agent 비활성 상태라 vision LLM 통계 0
- Take-profit ([#t1]) 실전 미발동 — 시장이 +1.5% 도달 안 했을 뿐, 코드는 정상
