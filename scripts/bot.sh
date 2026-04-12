#!/bin/bash
# Auto Trading Bot 관리 스크립트
# 사용법: ./bot.sh [start|stop|status|logs|test]

PROJECT_DIR="/Users/dawn-h/PycharmProjects/auto-trading"
PLIST_NAME="com.autotrading.bot"
PLIST_PATH="$PROJECT_DIR/scripts/$PLIST_NAME.plist"
LAUNCHD_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$PROJECT_DIR/logs"

cd "$PROJECT_DIR"

case "$1" in
    start)
        echo "=== Auto Trading Bot 시작 ==="

        # 로그 디렉토리 생성
        mkdir -p "$LOG_DIR"

        # plist 복사 (없으면)
        if [ ! -f "$LAUNCHD_PATH" ]; then
            cp "$PLIST_PATH" "$LAUNCHD_PATH"
        fi

        # 서비스 로드 및 시작
        launchctl load "$LAUNCHD_PATH" 2>/dev/null
        launchctl start "$PLIST_NAME"

        echo "봇이 시작되었습니다."
        echo "로그 확인: ./bot.sh logs"
        ;;

    stop)
        echo "=== Auto Trading Bot 중지 ==="
        launchctl stop "$PLIST_NAME" 2>/dev/null
        launchctl unload "$LAUNCHD_PATH" 2>/dev/null
        echo "봇이 중지되었습니다."
        ;;

    status)
        echo "=== Auto Trading Bot 상태 ==="
        if launchctl list | grep -q "$PLIST_NAME"; then
            echo "상태: 실행 중"
            launchctl list | grep "$PLIST_NAME"
        else
            echo "상태: 중지됨"
        fi

        echo ""
        echo "최근 로그 (마지막 10줄):"
        tail -10 "$LOG_DIR/stdout.log" 2>/dev/null || echo "(로그 없음)"
        ;;

    logs)
        echo "=== Auto Trading Bot 로그 ==="
        echo "실시간 로그 (Ctrl+C로 종료):"
        tail -f "$LOG_DIR/stdout.log"
        ;;

    test)
        echo "=== Paper Trading 테스트 (1 사이클) ==="
        uv run python -m trading.main --mode single
        ;;

    validate)
        echo "=== 설정 검증 ==="
        uv run python -m trading.main --validate-only
        ;;

    *)
        echo "Auto Trading Bot 관리 스크립트"
        echo ""
        echo "사용법: $0 {start|stop|status|logs|test|validate}"
        echo ""
        echo "  start    - 백그라운드에서 봇 시작"
        echo "  stop     - 봇 중지"
        echo "  status   - 상태 및 최근 로그 확인"
        echo "  logs     - 실시간 로그 보기"
        echo "  test     - Paper Trading 1 사이클 테스트"
        echo "  validate - 설정 검증만 수행"
        exit 1
        ;;
esac
