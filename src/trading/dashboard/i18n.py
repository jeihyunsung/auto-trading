"""Internationalization for dashboard."""

from typing import Literal

Language = Literal["ko", "en"]

TRANSLATIONS = {
    "ko": {
        # Page
        "page_title": "트레이딩 대시보드",
        "page_icon": "📊",

        # Sidebar
        "language": "언어",
        "asset": "자산",
        "auto_refresh": "자동 새로고침",
        "refresh_interval": "새로고침 간격 (초)",
        "days_to_show": "표시 기간 (일)",
        "refresh_now": "지금 새로고침",

        # Portfolio section
        "portfolio_status": "포트폴리오 현황",
        "total_value": "총 가치",
        "krw_balance": "KRW 잔고",
        "btc_balance": "BTC 잔고",
        "asset_balance": "{asset} 잔고",
        "exposure": "노출도",
        "pnl": "손익",
        "initial_capital": "초기 자본",

        # Charts section
        "indicator_charts": "지표 차트",
        "btc_price": "BTC 가격",
        "asset_price": "{asset} 가격",
        "rsi": "RSI",
        "macd": "MACD",
        "overbought": "과매수",
        "oversold": "과매도",
        "histogram": "히스토그램",
        "signal": "시그널",

        # Bollinger Bands
        "bollinger_bands": "볼린저 밴드",
        "bb_upper": "상단",
        "bb_middle": "중간",
        "bb_lower": "하단",
        "bb_width": "밴드폭",

        # OBV
        "obv": "OBV (거래량)",
        "obv_change": "OBV 변화율",

        # Decision history
        "decision_history": "결정 히스토리",
        "time": "시간",
        "action": "액션",
        "confidence": "확신도",
        "rationale": "판단근거",
        "status": "상태",
        "price": "가격",
        "full_rationale": "판단근거 상세보기",
        "select_decision": "결정 선택",

        # Actions
        "buy": "매수",
        "sell": "매도",
        "hold": "보유",

        # Status
        "pending": "대기중",
        "approved": "승인",
        "rejected": "거부",
        "executed": "체결",

        # Recent trades
        "recent_trades": "최근 거래",
        "quantity": "수량",
        "no_trades": "거래 내역 없음",

        # Trend
        "trend": "추세",
        "bullish": "상승",
        "bearish": "하락",
        "neutral": "중립",

        # Volatility
        "volatility": "변동성",
        "high": "높음",
        "medium": "보통",
        "low": "낮음",

        # Derivatives
        "derivatives_data": "파생상품 지표",
        "long_short_ratio": "롱/숏 비율",
        "global_ls": "글로벌 L/S",
        "top_trader_ls": "탑 트레이더 L/S",
        "funding_rate": "펀딩비",
        "open_interest": "미결제약정 (OI)",
        "no_derivatives_data": "파생상품 데이터 없음",
        "signal_interpretation": "신호 해석",
        "long_heavy_signal": "롱 과다: 숏 스퀴즈 또는 하락 반전 주의",
        "short_heavy_signal": "숏 과다: 롱 스퀴즈 또는 상승 반전 주의",
        "overheated_long_signal": "롱 과열: 펀딩비 높음, 하락 압력",
        "overheated_short_signal": "숏 과열: 펀딩비 낮음, 상승 압력",
        "oi_increasing_signal": "OI 증가: 추세 강화, 새 포지션 유입",
        "oi_decreasing_signal": "OI 감소: 추세 약화, 포지션 청산 중",
        "neutral_signal": "중립 신호 - 명확한 방향성 없음",

        # Misc
        "no_data": "데이터 없음",
        "last_updated": "마지막 업데이트",
        "cycle": "사이클",
    },
    "en": {
        # Page
        "page_title": "Trading Dashboard",
        "page_icon": "📊",

        # Sidebar
        "language": "Language",
        "asset": "Asset",
        "auto_refresh": "Auto Refresh",
        "refresh_interval": "Refresh Interval (sec)",
        "days_to_show": "Days to Show",
        "refresh_now": "Refresh Now",

        # Portfolio section
        "portfolio_status": "Portfolio Status",
        "total_value": "Total Value",
        "krw_balance": "KRW Balance",
        "btc_balance": "BTC Balance",
        "asset_balance": "{asset} Balance",
        "exposure": "Exposure",
        "pnl": "P&L",
        "initial_capital": "Initial Capital",

        # Charts section
        "indicator_charts": "Indicator Charts",
        "btc_price": "BTC Price",
        "asset_price": "{asset} Price",
        "rsi": "RSI",
        "macd": "MACD",
        "overbought": "Overbought",
        "oversold": "Oversold",
        "histogram": "Histogram",
        "signal": "Signal",

        # Bollinger Bands
        "bollinger_bands": "Bollinger Bands",
        "bb_upper": "Upper",
        "bb_middle": "Middle",
        "bb_lower": "Lower",
        "bb_width": "Band Width",

        # OBV
        "obv": "On-Balance Volume",
        "obv_change": "OBV Change",

        # Decision history
        "decision_history": "Decision History",
        "time": "Time",
        "action": "Action",
        "confidence": "Confidence",
        "rationale": "Rationale",
        "status": "Status",
        "price": "Price",
        "full_rationale": "Full Rationale Details",
        "select_decision": "Select Decision",

        # Actions
        "buy": "BUY",
        "sell": "SELL",
        "hold": "HOLD",

        # Status
        "pending": "Pending",
        "approved": "Approved",
        "rejected": "Rejected",
        "executed": "Executed",

        # Recent trades
        "recent_trades": "Recent Trades",
        "quantity": "Quantity",
        "no_trades": "No trades",

        # Trend
        "trend": "Trend",
        "bullish": "Bullish",
        "bearish": "Bearish",
        "neutral": "Neutral",

        # Volatility
        "volatility": "Volatility",
        "high": "High",
        "medium": "Medium",
        "low": "Low",

        # Derivatives
        "derivatives_data": "Derivatives Data",
        "long_short_ratio": "Long/Short Ratio",
        "global_ls": "Global L/S",
        "top_trader_ls": "Top Trader L/S",
        "funding_rate": "Funding Rate",
        "open_interest": "Open Interest (OI)",
        "no_derivatives_data": "No derivatives data",
        "signal_interpretation": "Signal Interpretation",
        "long_heavy_signal": "Long Heavy: Watch for short squeeze or bearish reversal",
        "short_heavy_signal": "Short Heavy: Watch for long squeeze or bullish reversal",
        "overheated_long_signal": "Long Overheated: High funding, bearish pressure",
        "overheated_short_signal": "Short Overheated: Low funding, bullish pressure",
        "oi_increasing_signal": "OI Increasing: Trend strengthening, new positions entering",
        "oi_decreasing_signal": "OI Decreasing: Trend weakening, positions closing",
        "neutral_signal": "Neutral Signal - No clear direction",

        # Misc
        "no_data": "No data",
        "last_updated": "Last Updated",
        "cycle": "Cycle",
    },
}


def get_text(key: str, lang: Language = "ko") -> str:
    """Get translated text.

    Args:
        key: Translation key.
        lang: Language code.

    Returns:
        Translated string or key if not found.
    """
    return TRANSLATIONS.get(lang, TRANSLATIONS["ko"]).get(key, key)


def get_action_text(action: str, lang: Language = "ko") -> str:
    """Get translated action text.

    Args:
        action: Action string (BUY/SELL/HOLD).
        lang: Language code.

    Returns:
        Translated action.
    """
    action_map = {
        "BUY": get_text("buy", lang),
        "SELL": get_text("sell", lang),
        "HOLD": get_text("hold", lang),
    }
    return action_map.get(action.upper(), action)


def get_status_text(status: str, lang: Language = "ko") -> str:
    """Get translated status text.

    Args:
        status: Status string.
        lang: Language code.

    Returns:
        Translated status.
    """
    status_map = {
        "pending": get_text("pending", lang),
        "approved": get_text("approved", lang),
        "rejected": get_text("rejected", lang),
        "executed": get_text("executed", lang),
    }
    return status_map.get(status.lower(), status)
