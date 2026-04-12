# Auto Trading Bot

LLM 기반 BTC 자동 매매 에이전트 (LangGraph + OpenAI)

## 설치

```bash
# uv 사용
uv sync

# 또는 pip 사용
pip install -e ".[dev]"
```

## 환경 설정

```bash
cp .env.example .env
# .env 파일에 API 키 입력
```

## 실행

```bash
# 설정 검증
python -m trading.main --validate-only

# 단일 사이클 실행 (Paper Trading)
python -m trading.main --mode single

# 연속 실행
python -m trading.main --mode continuous --interval 300
```

## 테스트

```bash
pytest tests/ -v
```
