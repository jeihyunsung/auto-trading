# Trading Bot Tuning Memory

라이브 관찰에서 발견한 봇 동작 패턴, 진단, 적용 fix를 시간순/카테고리별로 기록합니다.
새 사례 발견 시 [Case Entries](#case-entries)에 append.

## How to Use

1. **새 패턴 관찰 → 이력 검색**: 비슷한 증상이 있었는지 [Index](#index)에서 확인
2. **새 사례 발견 → 추가**: `### #<카테고리><번호> — 한 줄 제목` 형식으로 [Case Entries](#case-entries)에 append
3. **fix 적용 → backlink**: commit hash + 파일/라인 명시
4. **결과 검증 후 outcome 갱신**: 며칠 운영 후 효과 측정값 기입

## Index

| 카테고리 | 케이스 |
|---|---|
| Hysteresis | [#h1](#h1) [#h2](#h2) [#h3](#h3) [#h4](#h4) [#h5](#h5) |
| Stop-loss / Take-profit | [#s1](#s1) [#s2](#s2) [#t1](#t1) |
| LLM behavior | [#l1](#l1) [#l2](#l2) [#l3](#l3) [#l4](#l4) [#l5](#l5) [#l6](#l6) |
| Operations / Infra | [#o1](#o1) [#o2](#o2) [#o3](#o3) |
| PositionSizer | [#p1](#p1) |
| RiskValidator | [#r1](#r1) |

## Current Open Questions

- [#l4](#l4) Volume spike false positive — 24h 약세 중에도 volume 13.2x → BUY 발생. 충분한 데이터 없음.
- ~~[#l5](#l5) BUY 정체~~ — **자체 해소 (5/30 04:53)**. RSI 47.7로 하락하며 정상 BUY 발동. 옵션 A는 진입을 *지연*만 하고 *금지* 안 함을 검증.
- [#l6](#l6) **RSI 22 극단 과매도 + bearish MTF → HOLD** (5/31). Trend Confirmation Rule이 작동. 며칠 후 결과(bottom vs 추가 하락)로 정책 평가.
- Take-profit ([#t1](#t1)) 실전 발동 0회 — +1.5% 도달 케이스 부재. 시장 환경 영향.
- ~~[#h5](#h5) SELL conf < last BUY conf 스테일메이트~~ — **Fix shipped** (commit `1ac6e3a`, 6/01). Anchor decay (6h grace, -0.02/h, floor 0.55) + 보조 prompt calibration. 실전 효과는 다음 stalemate 사이클에서 검증.

## Active Settings (요약)

| 설정 | 값 | 결정 케이스 |
|---|---|---|
| `HysteresisConfig.streaming().action_reversal_delta` | 0.15 | [#h1](#h1) |
| `same_direction_cooldown_buy` | 15분 | [#h3](#h3) |
| `same_direction_cooldown_sell` | 5분 | [#h3](#h3) |
| `stop_loss_pct` | 2.0 | [#s1](#s1) |
| `take_profit_pct` | 1.5 | [#t1](#t1) |
| `take_profit_sell_fraction` | 0.5 | [#t1](#t1) |
| `buy_conf_cap_rsi_threshold` | 60.0 | [#l3](#l3) |
| `buy_conf_cap_value` | 0.65 | [#l3](#l3) |
| `llm_request_timeout_seconds` | 45.0 | [#o1](#o1) |
| `pattern_agent_enabled` (env) | false | [#o3](#o3) |
| `reversal_anchor_decay_start` | 6h | [#h5](#h5) |
| `reversal_anchor_decay_per_hour` | 0.02 | [#h5](#h5) |
| `reversal_anchor_conf_floor` | 0.55 | [#h5](#h5) |

---

## Case Entries

### #h1 — Hysteresis가 SELL 신호를 4시간 차단 {#h1}

- **Date**: 2026-05-24 19:24~23:26 KST
- **Symptom**: 19:11 BUY 후 13분만에 LLM이 SELL 신호 발동 → 17+ 회 연속 차단 → 4시간 후 conf 0.97로 결국 통과 (이미 -0.58% 손실).
- **Evidence**:
  ```
  19:24 SELL conf 0.63 — blocked: delta=-0.14 < 0.15
  19:49 SELL conf 0.58 with target=0% (전량) — blocked
  23:26 SELL conf 0.97 — finally passes @ 114.27M (BUY was 115.13M)
  ```
- **Root cause**: 직전 BUY confidence 0.77이 reversal threshold anchor. 일반 SELL이 0.92+ 도달 못함.
- **Fix**: `HysteresisConfig.streaming().action_reversal_delta` 0.25 → 0.15
  - File: `src/trading/core/hysteresis.py:59` · Commit `1b27876`
- **Outcome**: 5/28 13분 round-trip에서 SELL 통과 확인 ([#l4](#l4))
- **Related**: [#h2](#h2) (sizing-aware 추가 완화), [#h4](#h4) (cumulative counter)

### #h2 — Sizing-aware Hysteresis relaxation {#h2}

- **Date**: 2026-05-24 추가 fix
- **Symptom**: PositionSizer가 `target=0%` (전량 매도) 요청해도 Hysteresis가 confidence delta만 보고 차단.
- **Root cause**: Hysteresis는 sizing의 강도를 무시.
- **Fix**: `|position_delta_pct| ≥ 25%` → required delta × 0.5 / `≥ 15%` → × 0.7 (multiplier only, NOT full bypass per Codex correction)
  - File: `src/trading/core/hysteresis.py` apply_hysteresis · Commit `1b27876`
- **Codex 정정**: 초기 구현은 full bypass였으나 "mediocre SELL이 큰 sizing만 있으면 통과하는 새 failure mode" 경고 → multiplier로 후퇴.
- **Outcome**: 5/28 SELL delta=-7%이라 sizing relaxation 미작동, 그러나 [#h1](#h1) + [#l3](#l3)만으로 통과.

### #h3 — Same-direction cooldown (BUY→BUY, SELL→SELL) {#h3}

- **Date**: 2026-05-24
- **Symptom**: 5/24 17:36 BUY → 17:48 BUY (12분 안에 2회). 가격 거의 동일 (114.9M → 115.0M). DCA 효과 없이 수수료만 2배.
- **Root cause**: `post_trade_cooldown=15min`은 reversal에만 적용. 같은 방향 trades에 cooldown 없음. WebSocket 트리거가 매분 발동 → LLM 같은 신호 반복 발화.
- **Fix**: 비대칭 cooldown 추가
  - `same_direction_cooldown_buy=15min`
  - `same_direction_cooldown_sell=5min` (SELL은 손절 민첩성 위해 더 짧게)
  - File: `src/trading/core/hysteresis.py` HysteresisConfig + apply_hysteresis · Commit `1b27876`
- **Codex 입장**: "코드에 명시된 control gap, 13 trades는 overfit이지만 fix 명확"
- **Outcome**: 5/25 BUY 분산 확인 (08:43 → 13:38 → 16:06, 시간 간격 잘 분포).
- **Related**: [#l2](#l2) (LLM self-throttling prompt nudge)

### #h4 — Cumulative blocked-action relaxation {#h4}

- **Date**: 2026-05-24 (Codex 제안)
- **Symptom**: 30분 내 같은 방향 SELL이 ≥3회 차단되면 "gradual conviction growth" 패턴. emergency_override (0.85) 영구 미도달.
- **Fix**: `_blocked_actions` deque (maxlen=100) 추가. 30분 내 ≥3회 차단 시 required delta × max(0.4, 1 - 0.15·(count-2))
  - File: `src/trading/core/hysteresis.py` `_count_recent_blocks` + apply_hysteresis · Commit `1b27876`
- **Outcome**: 실전 미발동 (다른 fix들이 먼저 작동).

### #s1 — Stop-loss force exit + bypass {#s1}

- **Date**: 2026-05-23 도입, 2026-05-27 실전 발동
- **Symptom (도입 동기)**: [#h1](#h1) 4시간 stalemate. 손실이 hysteresis로 인해 누적.
- **Fix**: `detect_stop_loss()`을 `_decide_with_llm` **앞에** 배치. unrealized_pnl < -stop_loss_pct (default -2%)면 즉시 SELL with `bypass_hysteresis=True`
  - File: `src/trading/agents/decision_agent.py:218` · Commit `1b27876`
- **Outcome**: 5/27 02:31~03:07 4회 발동 — **그러나 분할 발동 버그 발생** ([#s2](#s2)로 fix)
- **Related**: [#r1](#r1) (validator의 max_single_trade_pct가 stop-loss size를 잘랐던 문제)

### #s2 — Stop-loss 분할 발동 fix (RiskValidator bypass) {#s2}

- **Date**: 2026-05-27 (5/27 새벽 stop-loss 4회 분할 발동 후 즉시 fix)
- **Symptom**: 1차 stop-loss가 32.5% 전량 exit 요청 → RiskValidator의 `max_single_trade_pct=10%`로 10%만 매도 → 30분간 4회 분할 발동
  ```
  02:31 SELL 10% (32.5% → 22.5%)
  02:40 SELL 10% (22.5% → 12.5%)
  03:00 SELL 10% (12.5% → 2.5%)
  03:07 SELL 잔량 (2.5% → 0%)
  ```
- **Root cause**: validator가 urgent decision도 일반 trade와 동일하게 max_single_trade로 제한.
- **Fix**: `decision.bypass_hysteresis == True`이면 RiskValidator의 `adjust_trade_size()` 우회. SELL은 exposure cap만, BUY는 cash+room cap만.
  - File: `src/trading/risk/validator.py` validate() · Commit `3037e26`
- **검증**: 32.5% exposure stop-loss → 32.5% 한 번에 매도 (이전 10%×4회). 가격 drift로 ~700원 추가 손실 막음.
- **Related**: [#r1](#r1)

### #t1 — Take-profit auto-exit {#t1}

- **Date**: 2026-05-27 추가
- **Motivation**: 사용자 피드백 "BUY 사이즈는 그대로, SELL 반응 속도만 빠르게" → take-profit이 가장 직접적 해결.
- **Symptom 컨텍스트**: [#h1](#h1)에서 SELL이 4시간 lag — 그 사이 익절 기회 놓침. LLM/Hysteresis 기다리지 않고 자동 청산하면 lag 제거.
- **Fix**: `detect_take_profit()` ([#s1](#s1)과 대칭). unrealized_pnl > +1.5% 도달 시 50% 자동 매도 (`bypass_hysteresis=True`). 나머지 50%는 trend 따라 ride.
  - File: `src/trading/agents/decision_agent.py:262` · Commit `3175e9c`
- **Settings**: `take_profit_pct=1.5`, `take_profit_sell_fraction=0.5`
- **Outcome**: 실전 발동 0회 (5/24~5/28 동안 +1.5% 도달 케이스 없음). 시장이 횡보~약세였음.

### #l1 — LLM confidence calibration (strict prompt) {#l1}

- **Date**: 2026-05-24
- **Symptom**: LLM이 RSI 65~66 + bullish trend에서 conf 0.77 부여. 후속 SELL이 hysteresis 차단됨 ([#h1](#h1)).
- **Fix**: `DECISION_SYSTEM_PROMPT` 재작성:
  - 0.85+ requires trend match + RSI easy zone + MACD aligned + derivatives confirm + ≥3 MTF aligned
  - 0.70+ never on neutral RSI 45-65 band
  - Self-check rule: "1% 반전에 SELL 가능하면 BUY conf -0.10"
  - File: `src/trading/llm/prompts.py` · Commit `1b27876`
- **Outcome**: 부분 효과. 5/25 BUY들 conf 73~77 여전 (cap [#l3](#l3) 도입 필요)
- **Related**: [#l3](#l3) (코드 레벨 cap)

### #l2 — LLM self-throttling prompt rule {#l2}

- **Date**: 2026-05-24
- **Symptom**: LLM이 직전 trade 정보를 받지만 prompt에 명시적 throttle policy 없음 → 12분 안에 또 같은 방향 trade 권고.
- **Fix**: prompt에 "Self-Throttling Rule" 섹션 추가
  - "마지막 trade가 BUY면 15분 / SELL이면 5분 내 같은 방향 권고 자제"
  - File: `src/trading/llm/prompts.py:186` · Commit `1b27876`
- **Outcome**: Hysteresis [#h3](#h3)이 코드 레벨 enforcement이므로 prompt nudge는 보조 효과. 검증 데이터 부족.

### #l3 — BUY confidence cap at high RSI (옵션 A) {#l3}

- **Date**: 2026-05-27
- **Symptom (Codex 진단)**: BUY가 RSI 58~66에서 발생, MTF +0.1 보너스로 raw 0.77 → 0.87 final → PositionSizer 50% tier + Hysteresis anchor 0.87 → 후속 SELL 0.93+ 불가.
- **숨겨진 메커니즘 발견**: MTF가 SELL은 차단할 수 있지만 **BUY는 conf +0.1만 부여하고 차단 안 함** → 비대칭성. PositionSizer는 confidence만 보고 RSI 무시.
- **Fix**: `cap_high_rsi_buy_confidence(action, conf, rsi, threshold=60, cap=0.65)` 헬퍼
  - BUY만 적용, MTF adjustment 적용 **후**에 cap
  - File: `src/trading/agents/decision_agent.py:177` (helper) + `_decide_with_llm` + `_decide_rule_based` · Commit `dc7b9ca`
- **Trade-off**: 강한 상승장 진입 사이즈 작아짐. 사용자가 의식적으로 수용.
- **Outcome 검증 (5/28)**:
  - BUY conf cap to 0.60 (실제로 LLM이 0.60 부여, RSI 67.4)
  - 13분 후 SELL conf 0.77 → delta +0.17 > 0.15 → 통과 ✅
  - 만약 cap 없었으면: BUY conf 0.77 → SELL 0.92 이상 필요 → 차단됨
- **Codex 경고**: "13 trades is overfit territory" — 더 많은 데이터로 검증 필요.

### #l6 — RSI 극단 과매도 (≤25) + bearish MTF → BUY 보류 {#l6}

- **Date**: 2026-05-31 (관찰 16:00~17:00 KST)
- **Symptom**: BTC가 109.3M에서 점진 하락. RSI가 30.6 → 27.3 → 22.1로 떨어졌으나 33개 결정 모두 HOLD. 신규 BUY 0회.
- **Evidence**:
  ```
  15:53 RSI=30.6, MTF [Be,Be,Be,Be] (4/4 bearish) → HOLD conf 0.60
  16:24 RSI=27.3, MTF bearish → HOLD conf 0.60
  16:56 RSI=22.1, MTF bearish → HOLD conf 0.60 ← 극단적 과매도인데 HOLD
  Position sizing: target=25%, current=23.1%, delta=+1.9% → HOLD (delta < 5% 임계)
  Hysteresis blocked: BUY -> HOLD (delta=-0.05 < 0.07)
  ```
- **Root cause**: Trend Confirmation Rule (LLM prompt) — "RSI oversold AND trend bearish이면 falling knife 회피 → HOLD". 5/27 -4.7% 폭락 직전과 같은 패턴 신호.
- **추가 차단 요인**:
  1. Position sizing이 current 23.1% vs target 25% → delta 1.9%만 부족 → HOLD trade=False
  2. 5/30 20:09 BUY conf 0.65가 Hysteresis anchor → 후속 BUY 0.72+ 필요
- **Status**: 미수정 — 의도된 보수성.
  - 만약 여기가 bottom + 반등이면: BUY 미스 (lost opportunity)
  - 만약 추가 하락이면: 봇 보호 ([#s1] -2% stop-loss 대기)
- **Trade-off**: [#l3] cap이 RSI 60+에서 가짜 BUY 막듯, Trend Confirmation Rule이 RSI 25-에서 falling knife 막음. 양극단 모두 보수적.
- **Possible fix candidates (검토만)**:
  - 강한 oversold (RSI ≤ 25) + 다른 reversal 신호 (예: MACD 양수 전환, 5분봉 trend 변화) 조합 시 일부 진입 허용
  - 그러나 [#l4] volume spike false positive처럼 noise BUY 위험
- **Related**: [#l5](#l5) (RSI 60+에서 HOLD), [#l1](#l1) (prompt rule), [#s1](#s1) (stop-loss 백업)

### #l5 — BUY signal 정체: 상승장 진입 실패 (옵션 A 부작용 본격 발현) {#l5}

- **Date**: 2026-05-29 (관찰 09:18~18:21 KST)
- **Symptom**: BTC +0.96% 상승 중. 봇 노출 3% (보유 0.000274 BTC, +0.93% 평가이익). 36개 결정 모두 HOLD. 신규 BUY 0회.
- **Evidence**:
  ```
  PositionSizer: target=25%, current=3%, delta=+22%, action=BUY, trade=True (LLM 미사용 기준)
  LLM 17:19: RSI=62.6, Trend=bullish → HOLD conf 0.60 ("매수 확신 낮음")
  LLM 17:51: RSI=64.2, Trend=bullish → HOLD conf 0.60 ("과매수 근접, 매수 확신 낮음")
  LLM 18:21: RSI=70.6, Trend=bullish → HOLD conf 0.60 ("과매수 근접 단기 조정 가능성")
  MTF 09:18~18:21: [1d=Be, 1h=Bu, 4h=Be, 5m=Bu] → neutral (0/4 aligned, adj=-0.10)
  ```
- **Root cause**: **옵션 A([#l3])의 예상된 부작용**. RSI 60+에서 BUY conf cap=0.65 + prompt 강화([#l1]) "RSI 65+는 single signal로 BUY 불가" → LLM 자체가 0.6 이상 BUY 권고 안 함. MTF가 mixed (1d/4h bearish 잔재 + 1h/5m bullish)라 정렬 보너스(+0.1) 못 받음 — 오히려 -0.10 페널티.
- **User feedback**: "가격이 점점 상승하고 있는데 액션이 없네" — 사용자가 [#l3] 도입 시 우려한 "강한 추세장 진입 사이즈 작아짐" 정확히 발현
- **Outcome (2026-05-30 04:53 KST)**: 자체 해소 — BTC 가격이 새벽에 약간 하락하며 RSI 47.7로 떨어진 시점 LLM이 conf 0.67 BUY 권고 → 0.000910 BTC @ 108,884,000 매수. **옵션 A([#l3])의 cap이 RSI > 60 구간에만 적용된다는 점 검증됨** (RSI 47.7은 cap 미적용, PositionSizer 0.6-0.7 tier 25% target).
- **검증된 동작**: 옵션 A는 진입을 *지연*시킬 뿐 *금지*하지 않음. RSI가 30~55 구간으로 내려오는 자연스러운 조정 + bullish trend 동시 발생하면 정상 BUY 가능.
- **수정 결정**: **fix 안 함** — 시장이 자체적으로 RSI를 진입 가능 영역으로 가져옴. 며칠 더 관찰 후 BUY 빈도 정상 범위인지 판단.
- **Lesson**: 옵션 A는 "RSI 60+에서 자신감 큰 추격 매수"만 막는다. 정상 가격 조정 시 진입은 작동.
- **Related**: [#l3](#l3) (cap 자체), [#h1](#h1) (cap 도입 원인이었던 4h stalemate), [#l1](#l1) (prompt confidence 강화)

### #l4 — Volume spike false positive (5/28 13분 round-trip) {#l4}

- **Date**: 2026-05-28 16:18~16:31 KST
- **Symptom**: 24h -1.16% 약세 중인데 Volume spike 13.2x 트리거 → LLM BUY conf 0.77 → cap 적용 0.60 → 13분 후 SELL 0.77로 청산. 가격 0.04% 차이로 사실상 -127원 손실.
- **Trade detail**:
  ```
  16:18 BUY  108,318,000  RSI 67.4  MTF bearish (override)  MACD +104K  Volume 13.2x
  16:31 SELL 108,276,000  RSI 64.6  MTF aligned for SELL    LLM "보호적 매도"
  ```
- **Hypothesis**: LLM이 volume spike를 "매수 관심"으로 해석. 실제로는 매도 압력의 일부 (큰 거래가 들어왔지만 가격 안 오름).
- **Root cause 후보**:
  1. Volume spike trigger에 24h trend sanity check 없음
  2. MTF override (conf ≥ 0.65)가 raw LLM conf 0.77 기준 → cap 적용 전 통과 → bearish MTF 무시
- **Status**: 미수정. 단일 사례 → 데이터 더 모은 후 패턴 반복되면 fix 고려.
- **Possible fix (Option α)**: prompt 또는 코드에 "24h_change < -0.5% AND volume_spike > 5x이면 BUY conf cap to 0.55" sanity check
- **Related**: [#l3](#l3) (cap이 이미 일부 완화), [#h1](#h1) (해당 케이스는 cap 효과로 안 발생)

### #o1 — LLM HTTP timeout (18h 42min freeze 방지) {#o1}

- **Date**: 2026-05-27 (5/27 04:32~23:15 KST 18시간 freeze 후)
- **Symptom**: systemd "active running" 18시간 유지인데 로그 0. `ChatOpenAI`에 timeout 없어 stuck connection이 event loop 영구 차단.
- **Fix**:
  - `LLMClient.__init__`: `timeout=settings.llm_request_timeout_seconds, max_retries=2`
  - `pattern_agent._analyze_with_vision`: 동일 timeout 적용
  - 신규 설정 `llm_request_timeout_seconds` (default 45.0)
  - File: `src/trading/llm/client.py` + `src/trading/agents/pattern_agent.py` · Commit `3037e26`
- **Outcome**: 5/27 이후 LLM-level freeze 없음. 단 [#o3](#o3) (pattern_agent 다른 종류 hang)은 별도.

### #o2 — Watchdog cron (8분 stale 자동 재시작) — v1 버그 + v2 수정 {#o2}

- **Date**: v1 2026-05-27 도입 / v2 2026-05-28 수정
- **v1 문제**: `journalctl -u trading-bot -n 1 --since "30 minutes ago"`가 30분 window의 **첫** 로그를 가져와서 항상 ~1800s stale 계산 → 매분 잘못된 restart.
- **Symptom**: 5/28 12:30~13:11 사이 10분에 봇 PID 10개 (매분 restart). 거래 사이클이 매번 중단됨.
- **Fix (v2)**: `journalctl -u "$SERVICE" --reverse -n 1` 로 진짜 최신 로그 시각 사용. stale threshold 8분 → 10분.
  - File: `/usr/local/bin/trading-bot-watchdog.sh` (VM 로컬, repo 외)
  - Cron: `/etc/cron.d/trading-bot-watchdog` 매분 실행
- **Outcome**: 5/28 13:11 이후 false STALE alert 0. 단일 PID 안정 유지.
- **Note**: VM 로컬 스크립트라 git에 없음 — 향후 `scripts/` 디렉토리에 보관 권장.

### #o3 — Pattern_agent kill switch (vision LLM hang) {#o3}

- **Date**: 2026-05-28
- **Symptom**: indicator 계산 후 곧바로 봇 hang. LLM timeout([#o1](#o1))으로도 해소 안 됨. matplotlib chart 생성 또는 vision LLM call 어딘가에서 block.
- **Diagnosis**: 패턴 — `Trend channel:` 로그 후 다음 사이클까지 30분+ 무로그. trigger 조건 (price change ≥1%, volume spike, BB breakout) 자주 발동 → vision agent 들어가서 hang.
- **Fix**: `pattern_agent_enabled` 설정 (default True). False면 `pattern_agent_node`가 즉시 `_no_pattern()` 반환 (matplotlib/LLM 코드 미실행).
  - File: `src/trading/config.py` + `src/trading/agents/pattern_agent.py:471` · Commit `d569d24`
  - VM `.env`: `PATTERN_AGENT_ENABLED=false`
- **Outcome**: 5/28 13:11 이후 사이클당 ~4초 이내 완료. Decision: HOLD 정상 출력.
- **TODO**: 근본 원인 (matplotlib vs vision LLM) 격리 + 영구 fix. 현재는 임시 비활성.

### #p1 — PositionSizer가 RSI를 입력으로 받지 않음 (구조적 한계) {#p1}

- **Date**: Codex 분석 (2026-05-27)
- **Discovery**: `PositionSizer.calculate_target_position()` 티어는 confidence만 봄. RSI 65에서 BUY와 RSI 35에서 BUY가 같은 confidence면 같은 사이즈.
- **Why it matters**: RSI 65+ BUY는 구조적으로 late entry. Sizing이 RSI를 고려하지 않으면 늦은 진입에 큰 사이즈.
- **Indirect fix**: [#l3](#l3) BUY conf cap이 confidence를 통해 sizing tier를 간접 다운그레이드 (0.7-0.8 tier → 0.6-0.7 tier).
- **Direct fix candidate**: `PositionSizer.calculate()`에 RSI 파라미터 추가 → high RSI에서 target % 직접 reduction. 미적용 (간접 fix가 충분히 작동).

### #r1 — RiskValidator의 max_single_trade_pct가 urgent exit 방해 {#r1}

- **Date**: 2026-05-27
- **Issue**: [#s1](#s1) stop-loss decision이 size 100% 요청해도 validator가 10%로 잘라냄.
- **Fix**: [#s2](#s2) 참조 — `decision.bypass_hysteresis` 기반 우회.
- **Related**: 향후 새로운 urgent decision 추가 시 같은 `bypass_hysteresis=True` 플래그 사용하면 자동으로 같은 경로 통과.

---

### #h5 — Hysteresis stalemate: SELL conf < last BUY conf (음수 delta) {#h5}

- **Date**: 2026-06-01
- **Symptom**: 5/31 23:09 ~ 6/01 06:00 (약 7시간) 동안 LLM이 거의 매 cycle SELL 권고했지만 hysteresis가 모두 차단. 같은 기간 BTC -0.55% 하락 (109.14M → 108.54M). 격리 잔고 6.5% exposure 그대로 유지.
- **Evidence**:
  ```
  May 31 23:09 SELL -> HOLD (delta=-0.05 < 0.07)
  May 31 23:22 SELL -> HOLD (delta=-0.07 < 0.09)  [sizing-aware 적용 후에도]
  May 31 23:33 SELL -> HOLD (delta=-0.02 < 0.06)  [cumulative 0.4× 적용 후]
  May 31 23:50 SELL -> HOLD (delta=-0.05 < 0.05)
  Last trade: 5/30 20:09 BUY @ 109.14M, conf=0.65
  6/01 SELL decisions: conf=0.60, 0.65, 0.71 — 모두 음수 또는 0 delta
  ```
- **Root cause**: Hysteresis는 `new_conf - last_trade_conf ≥ threshold`를 요구. SELL conf가 anchor BUY conf보다 낮거나 같으면 delta가 음수가 됨. Cumulative blocking ([#h4](#h4))이 threshold를 0.06까지 풀어줘도 음수 delta는 절대 통과 못 함.
  - [#h2](#h2)는 sizing relaxation (multiplier만)으로 부분 해결.
  - [#h4](#h4)는 cumulative count 기반 (양수 delta가 필요하다는 가정).
  - [#h5](#h5)는 두 가지 모두 작동했지만 **delta가 음수**라서 unreachable.
- **Why now**: 6/01 시장은 sideways → bearish. RSI 51~57 중립, MACD 약한 상승. LLM이 SELL을 "conviction 0.60"으로 신호 — anchor BUY 0.65보다 낮음.
- **Status**: **Fixed** (commit `1ac6e3a`, 6/01) — A안 + 보조 D안 채택. Codex 권고.
- **Fix (A 주)**: `_decay_reversal_anchor_confidence()` — `last_trade_time` 후 6h grace까지 anchor 유지, 이후 시간당 -0.02 감쇠, floor 0.55. anchor 0.65 BUY는 11h 후 0.55까지 내려가서 SELL 0.60+이 자연스럽게 통과.
- **Fix (D 보조)**: prompt `Decision Consistency` — "conf > 0.8 to reverse"를 시간 조건부(15분 이내)로 한정. 신규 섹션 "Protective SELL Confidence"로 LLM에게 entry conf에 앵커링 X, 현재 setup만 평가하라고 지시.
- **검토 후 채택 안한 후보**:
  - B (연속 SELL bypass) — flip-flop 보호 깨고 cadence 의존성 큼
  - C (가격 drift reset) — stop-loss와 이원화, 침습도 큼
- **Verification**: 4개 단위 테스트 통과 (18h decay 통과 / 2h grace 차단 / 100h floor 클램프 / same-direction 영향 없음). 실전 효과는 다음 stalemate 발생 시 측정.
- **Related**: [#h1](#h1) (anchor 자체 개념), [#h4](#h4) (cumulative relaxation), [#l5](#l5) ([#h5](#h5)와 반대 — 누적 BUY 권고 → 자체 해소 패턴 검증).

---

## Cross-Reference Table

| 사례 트리거 | 원인 카테고리 | 해결 케이스 |
|---|---|---|
| BUY→SELL 4시간 차단 | Hysteresis anchoring | [#h1](#h1) + [#l3](#l3) |
| Stop-loss 분할 발동 | RiskValidator size cap | [#s2](#s2) |
| 18시간 freeze | LLM HTTP no timeout | [#o1](#o1) |
| 봇 매분 재시작 | Watchdog parsing bug | [#o2](#o2) |
| Indicator 후 hang | Pattern_agent matplotlib/vision | [#o3](#o3) |
| BUY cluster (12분 안 3회) | Same-direction no cooldown | [#h3](#h3) |
| 고점 매수 패턴 | LLM over-confidence at high RSI | [#l1](#l1) + [#l3](#l3) |
| 13분 round-trip whipsaw | Volume spike false positive | [#l4](#l4) (관찰) |

## Behavioral Patterns Observed

### Pattern A: Lag is structural (Trend Confirmation Rule)
- 봇은 trend-following이라 entry/exit가 본질적으로 후행
- 매수 평균 RSI ~58, 매도 평균 RSI ~36 → 22 unit lag = 약 1.4% 가격 후행
- Mean reversion 도입은 [#l4](#l4) 같은 false positive 폭증 위험 → Codex가 net negative 평가
- **수용 가능한 lag**: stop-loss [#s1](#s1) + take-profit [#t1](#t1)로 양극단 보호

### Pattern B: Confidence는 hysteresis와 sizing의 공통 입력
- LLM conf 1개가 두 layer 동시 컨트롤 → 잘못 calibrate 시 양쪽 모두 lag
- [#l3](#l3) cap이 single intervention으로 양쪽 효과 (highest leverage per Codex)

### Pattern C: Watchdog/timeout이 코드 hang을 항상 못 잡음
- LLM HTTP는 [#o1](#o1) timeout으로 잡힘
- matplotlib / 다른 sync hang은 [#o3](#o3) kill switch 필요
- 향후 비슷한 hang은 *별도 비활성 flag* 패턴 권장

## Future Work

- [ ] `scripts/watchdog.sh` 를 repo에 보관 ([#o2](#o2))
- [ ] Pattern_agent root cause 격리 후 재활성 ([#o3](#o3))
- [ ] [#l4](#l4) Volume spike false positive — 데이터 모은 후 sanity check 추가 결정
- [ ] [#p1](#p1) PositionSizer RSI 인풋 직접 추가 vs 현재 간접 cap 유지 결정
- [ ] Win rate 통계 (현재 13 trades, overfit territory) — 50+ trades 후 재평가
