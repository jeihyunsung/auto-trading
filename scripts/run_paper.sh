#!/bin/bash
# Paper Trading 실행 스크립트

cd /Users/dawn-h/PycharmProjects/auto-trading

# 환경 확인
echo "=== Auto Trading Bot - Paper Mode ==="
echo "시작 시간: $(date)"
echo ""

# 설정 검증
uv run python -m trading.main --validate-only
if [ $? -ne 0 ]; then
    echo "설정 검증 실패. .env 파일을 확인하세요."
    exit 1
fi

echo ""
echo "Paper Trading을 시작합니다..."
echo "중지하려면 Ctrl+C를 누르세요."
echo ""

# Paper Trading 실행 (5분 간격, 최대 12사이클 = 1시간)
uv run python -m trading.main --mode continuous --interval 300 --max-cycles 12
