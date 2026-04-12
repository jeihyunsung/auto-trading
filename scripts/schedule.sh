#!/bin/bash
# 스케줄 실행 관리 스크립트
# 사용법: ./schedule.sh [install|uninstall|status|next]

PROJECT_DIR="/Users/dawn-h/PycharmProjects/auto-trading"
PLIST_NAME="com.autotrading.scheduled"
PLIST_PATH="$PROJECT_DIR/scripts/$PLIST_NAME.plist"
LAUNCHD_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_FILE="$PROJECT_DIR/logs/scheduled.log"

case "$1" in
    install)
        echo "=== 스케줄 실행 설치 ==="

        # 로그 디렉토리 생성
        mkdir -p "$PROJECT_DIR/logs"

        # 기존 제거
        launchctl unload "$LAUNCHD_PATH" 2>/dev/null

        # plist 복사
        cp "$PLIST_PATH" "$LAUNCHD_PATH"

        # 로드
        launchctl load "$LAUNCHD_PATH"

        echo ""
        echo "✅ 설치 완료!"
        echo ""
        echo "실행 스케줄:"
        echo "  - 매일 09:00"
        echo "  - 매일 13:00"
        echo "  - 매일 17:00"
        echo "  - 매일 21:00"
        echo ""
        echo "맥북이 꺼져 있다가 켜지면 놓친 실행이 즉시 수행됩니다."
        ;;

    uninstall)
        echo "=== 스케줄 실행 제거 ==="
        launchctl unload "$LAUNCHD_PATH" 2>/dev/null
        rm -f "$LAUNCHD_PATH"
        echo "✅ 제거 완료"
        ;;

    status)
        echo "=== 스케줄 상태 ==="
        if launchctl list | grep -q "$PLIST_NAME"; then
            echo "상태: 활성화됨 ✅"
            echo ""
            echo "실행 스케줄: 매일 09:00, 13:00, 17:00, 21:00"
        else
            echo "상태: 비활성화됨 ❌"
            echo ""
            echo "활성화: ./schedule.sh install"
        fi

        echo ""
        echo "=== 최근 실행 로그 (마지막 20줄) ==="
        tail -20 "$LOG_FILE" 2>/dev/null || echo "(로그 없음)"
        ;;

    logs)
        echo "=== 스케줄 실행 로그 ==="
        tail -f "$LOG_FILE"
        ;;

    run)
        echo "=== 수동 실행 (1 사이클) ==="
        cd "$PROJECT_DIR"
        uv run python -m trading.main --mode single
        ;;

    *)
        echo "스케줄 실행 관리"
        echo ""
        echo "사용법: $0 {install|uninstall|status|logs|run}"
        echo ""
        echo "  install   - 스케줄 등록 (4시간마다 자동 실행)"
        echo "  uninstall - 스케줄 제거"
        echo "  status    - 상태 및 최근 로그"
        echo "  logs      - 실시간 로그 보기"
        echo "  run       - 지금 바로 1회 실행"
        exit 1
        ;;
esac
