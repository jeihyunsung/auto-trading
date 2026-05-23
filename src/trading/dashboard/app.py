"""Streamlit dashboard for trading bot monitoring."""

from datetime import datetime
from pathlib import Path

import streamlit as st

from trading.core.history_reader import HistoryReader
from trading.core.time import KST
from trading.dashboard.charts import (
    create_bollinger_bands_chart,
    create_combined_chart,
    create_derivatives_chart,
    create_macd_chart,
    create_obv_chart,
    create_price_chart,
    create_rsi_chart,
)
from trading.dashboard.i18n import (
    Language,
    get_action_text,
    get_status_text,
    get_text,
)

# Page config
st.set_page_config(
    page_title="Trading Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def get_log_dir() -> Path:
    """Get log directory from environment or default."""
    import os

    log_dir = os.environ.get("TRADING_LOG_DIR", "logs")
    return Path(log_dir)


def format_krw(value: float) -> str:
    """Format KRW value with commas."""
    return f"{value:,.0f}"


def format_pct(value: float) -> str:
    """Format percentage with sign."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def get_action_emoji(action: str) -> str:
    """Get emoji for action."""
    emojis = {
        "BUY": "🟢",
        "SELL": "🔴",
        "HOLD": "⚪",
    }
    return emojis.get(action.upper(), "⚪")


def to_kst(dt: datetime) -> datetime:
    """Convert datetime to KST.

    Args:
        dt: datetime object (naive or aware).

    Returns:
        datetime in KST.
    """
    if dt.tzinfo is None:
        # Naive datetime is assumed to be UTC (from VM running in UTC)
        # First attach UTC timezone, then convert to KST
        return dt.replace(tzinfo=timezone.utc).astimezone(KST)
    return dt.astimezone(KST)


def get_status_emoji(status: str) -> str:
    """Get emoji for status."""
    emojis = {
        "pending": "",
        "approved": "",
        "rejected": "",
        "executed": "",
    }
    return emojis.get(status.lower(), "")


def render_sidebar(lang: Language) -> tuple[int, bool, int]:
    """Render sidebar settings.

    Returns:
        Tuple of (days, auto_refresh, refresh_interval).
    """
    st.sidebar.title(get_text("page_icon", lang) + " " + get_text("page_title", lang))

    # Language selector
    lang_options = {"ko": "한국어", "en": "English"}
    selected_lang = st.sidebar.selectbox(
        get_text("language", lang),
        options=list(lang_options.keys()),
        format_func=lambda x: lang_options[x],
        index=0 if lang == "ko" else 1,
        key="language_selector",
    )

    # Auto refresh
    auto_refresh = st.sidebar.checkbox(
        get_text("auto_refresh", lang),
        value=True,
        key="auto_refresh",
    )

    refresh_interval = st.sidebar.slider(
        get_text("refresh_interval", lang),
        min_value=10,
        max_value=300,
        value=30,
        step=10,
        key="refresh_interval",
    )

    # Days to show
    days = st.sidebar.slider(
        get_text("days_to_show", lang),
        min_value=1,
        max_value=30,
        value=7,
        key="days_to_show",
    )

    # Refresh button
    if st.sidebar.button(get_text("refresh_now", lang), key="refresh_button"):
        st.rerun()

    # Update language in session state
    if selected_lang != lang:
        st.session_state["lang"] = selected_lang
        st.rerun()

    return days, auto_refresh, refresh_interval


def render_portfolio_section(reader: HistoryReader, lang: Language) -> None:
    """Render portfolio status section."""
    st.header(get_text("portfolio_status", lang))

    # Get latest data
    portfolio = reader.get_latest_portfolio()
    isolated = reader.get_isolated_balance()
    indicators = reader.get_indicators(days=1)

    # Get latest price
    latest_price = 0.0
    if indicators:
        latest_price = indicators[-1].btc_price

    # Calculate values
    total_invested = 0.0
    if isolated:
        krw = float(isolated.get("krw", 0))
        btc = float(isolated.get("btc", 0))
        initial = float(isolated.get("initial_capital", 200000))
        total_invested = float(isolated.get("total_invested", 0))
        total_value = krw + btc * latest_price if latest_price > 0 else krw
        pnl_pct = ((total_value - initial) / initial * 100) if initial > 0 else 0
    elif portfolio:
        krw = portfolio.get("cash_krw", 0)
        btc = portfolio.get("btc_balance", 0)
        initial = portfolio.get("initial_capital", 100000)
        total_invested = portfolio.get("total_invested_krw", 0)
        total_value = portfolio.get("total_value_krw", krw)
        pnl_pct = portfolio.get("pnl_pct", 0)
    else:
        krw, btc, initial, total_value, pnl_pct = 0, 0, 0, 0, 0

    # Exposure
    if total_value > 0 and latest_price > 0:
        exposure = (btc * latest_price / total_value) * 100
    else:
        exposure = 0

    # Unrealized P&L: BTC position only (current BTC value vs invested amount)
    btc_value = btc * latest_price if latest_price > 0 else 0
    if total_invested > 0 and btc > 0:
        unrealized_pnl_pct = ((btc_value / total_invested) - 1) * 100
    else:
        unrealized_pnl_pct = 0.0

    # Display metrics
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            get_text("total_value", lang),
            f"{format_krw(total_value)} KRW",
            format_pct(pnl_pct),
        )

    with col2:
        st.metric(
            get_text("krw_balance", lang),
            f"{format_krw(krw)} KRW",
        )

    with col3:
        st.metric(
            get_text("btc_balance", lang),
            f"{btc:.8f} BTC",
            format_pct(unrealized_pnl_pct) if btc > 0 else None,
        )

    with col4:
        st.metric(
            get_text("exposure", lang),
            f"{exposure:.1f}%",
        )

    with col5:
        st.metric(
            get_text("pnl", lang),
            format_pct(unrealized_pnl_pct) if btc > 0 else "N/A",
            f"{format_krw(btc_value - total_invested)} KRW" if btc > 0 and total_invested > 0 else None,
        )

    # Latest indicator info
    if indicators:
        latest = indicators[-1]
        latest_time_kst = to_kst(latest.timestamp)
        st.caption(
            f"{get_text('last_updated', lang)}: {latest_time_kst.strftime('%Y-%m-%d %H:%M:%S')} KST | "
            f"RSI: {latest.rsi:.1f} | "
            f"{get_text('trend', lang)}: {latest.trend} | "
            f"{get_text('volatility', lang)}: {latest.volatility}"
        )


def render_charts_section(reader: HistoryReader, days: int, lang: Language) -> None:
    """Render indicator charts section."""
    st.header(get_text("indicator_charts", lang))

    indicators = reader.get_indicators(days=days)
    trades = reader.get_trades(days=days)

    if not indicators:
        st.info(get_text("no_data", lang))
        return

    # Combined chart with trade markers
    fig = create_combined_chart(indicators, lang, trades=trades)
    st.plotly_chart(fig, use_container_width=True)

    # Individual charts in expander
    with st.expander("Individual Charts"):
        col1, col2 = st.columns(2)

        with col1:
            fig_rsi = create_rsi_chart(indicators, lang)
            st.plotly_chart(fig_rsi, use_container_width=True)

        with col2:
            fig_macd = create_macd_chart(indicators, lang)
            st.plotly_chart(fig_macd, use_container_width=True)

        # Bollinger Bands (with trade markers) and OBV charts
        col3, col4 = st.columns(2)

        with col3:
            fig_bb = create_bollinger_bands_chart(indicators, lang, trades=trades)
            st.plotly_chart(fig_bb, use_container_width=True)

        with col4:
            fig_obv = create_obv_chart(indicators, lang)
            st.plotly_chart(fig_obv, use_container_width=True)


def render_derivatives_section(reader: HistoryReader, days: int, lang: Language) -> None:
    """Render derivatives data section."""
    st.header(get_text("derivatives_data", lang))

    derivatives = reader.get_derivatives(days=days)
    latest = reader.get_latest_derivatives()

    if not latest:
        st.info(get_text("no_derivatives_data", lang))
        return

    # Current values display
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        # Long/Short Ratio with color indicator
        ls_ratio = latest.long_short_ratio
        ls_color = "inverse" if ls_ratio > 1.5 else ("off" if ls_ratio < 0.67 else "normal")
        st.metric(
            get_text("long_short_ratio", lang),
            f"{ls_ratio:.2f}",
            delta=f"{latest.position_bias}",
            delta_color=ls_color,
        )

    with col2:
        # Funding Rate with direction indicator
        funding_pct = latest.funding_rate * 100
        st.metric(
            get_text("funding_rate", lang),
            f"{funding_pct:+.4f}%",
            delta=latest.funding_signal,
            delta_color="inverse" if latest.funding_signal == "overheated_long" else (
                "normal" if latest.funding_signal == "overheated_short" else "off"
            ),
        )

    with col3:
        # Open Interest with change
        oi_value_b = latest.open_interest_value / 1_000_000_000  # Convert to Billions
        st.metric(
            get_text("open_interest", lang),
            f"${oi_value_b:.2f}B",
            delta=f"{latest.oi_change_pct_1h:+.1f}% (1h)",
        )

    with col4:
        # Top Trader L/S
        st.metric(
            get_text("top_trader_ls", lang),
            f"{latest.top_trader_long_short_ratio:.2f}",
            delta=f"{latest.oi_trend}",
        )

    # Derivatives chart
    if derivatives and len(derivatives) > 1:
        fig = create_derivatives_chart(derivatives, lang)
        st.plotly_chart(fig, use_container_width=True)

    # Signal interpretation
    with st.expander(get_text("signal_interpretation", lang)):
        signals = []

        # Position bias signal
        if latest.position_bias == "long_heavy":
            signals.append(f"- {get_text('long_heavy_signal', lang)}")
        elif latest.position_bias == "short_heavy":
            signals.append(f"+ {get_text('short_heavy_signal', lang)}")

        # Funding signal
        if latest.funding_signal == "overheated_long":
            signals.append(f"- {get_text('overheated_long_signal', lang)}")
        elif latest.funding_signal == "overheated_short":
            signals.append(f"+ {get_text('overheated_short_signal', lang)}")

        # OI trend signal
        if latest.oi_trend == "increasing":
            signals.append(f"* {get_text('oi_increasing_signal', lang)}")
        elif latest.oi_trend == "decreasing":
            signals.append(f"* {get_text('oi_decreasing_signal', lang)}")

        if signals:
            st.markdown("\n".join(signals))
        else:
            st.markdown(get_text("neutral_signal", lang))


def render_decisions_section(reader: HistoryReader, days: int, lang: Language) -> None:
    """Render decision history section."""
    st.header(get_text("decision_history", lang))

    decisions = reader.get_decisions(days=days)

    if not decisions:
        st.info(get_text("no_data", lang))
        return

    # Convert to display data
    data = []
    for d in decisions[:100]:  # Limit to 100 most recent
        status_emoji = get_status_emoji(d.status)
        action_emoji = get_action_emoji(d.action)
        time_kst = to_kst(d.timestamp)

        data.append({
            get_text("time", lang): time_kst.strftime("%m/%d %H:%M"),
            get_text("action", lang): f"{action_emoji} {get_action_text(d.action, lang)}",
            get_text("confidence", lang): f"{d.confidence:.0%}",
            get_text("price", lang): format_krw(d.market_price),
            get_text("status", lang): f"{status_emoji} {get_status_text(d.status, lang)}",
            get_text("rationale", lang): d.rationale[:100] + "..." if len(d.rationale) > 100 else d.rationale,
        })

    st.dataframe(
        data,
        use_container_width=True,
        hide_index=True,
    )

    # Stats
    total = len(decisions)
    buys = sum(1 for d in decisions if d.action == "BUY")
    sells = sum(1 for d in decisions if d.action == "SELL")
    holds = sum(1 for d in decisions if d.action == "HOLD")
    executed = sum(1 for d in decisions if d.was_executed)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total", total)
    col2.metric("BUY", buys)
    col3.metric("SELL", sells)
    col4.metric("HOLD", holds)
    col5.metric("Executed", executed)

    # Full rationale expander
    with st.expander(get_text("full_rationale", lang)):
        # Show selector for recent decisions
        decision_options = []
        for i, d in enumerate(decisions[:20]):  # Last 20 decisions
            time_kst = to_kst(d.timestamp)
            action_emoji = get_action_emoji(d.action)
            label = f"{time_kst.strftime('%m/%d %H:%M')} - {action_emoji} {d.action} ({d.confidence:.0%})"
            decision_options.append((label, d))

        if decision_options:
            selected_label = st.selectbox(
                get_text("select_decision", lang),
                options=[opt[0] for opt in decision_options],
                key="decision_selector",
            )

            # Find selected decision
            selected_decision = None
            for label, d in decision_options:
                if label == selected_label:
                    selected_decision = d
                    break

            if selected_decision:
                time_kst = to_kst(selected_decision.timestamp)
                st.markdown(f"**{get_text('time', lang)}:** {time_kst.strftime('%Y-%m-%d %H:%M:%S')} KST")
                st.markdown(f"**{get_text('action', lang)}:** {get_action_emoji(selected_decision.action)} {selected_decision.action}")
                st.markdown(f"**{get_text('confidence', lang)}:** {selected_decision.confidence:.1%}")
                st.markdown(f"**{get_text('price', lang)}:** {format_krw(selected_decision.market_price)} KRW")
                st.markdown(f"**{get_text('status', lang)}:** {get_status_text(selected_decision.status, lang)}")
                st.markdown("---")
                st.markdown(f"**{get_text('rationale', lang)}:**")
                st.markdown(selected_decision.rationale)


def render_trades_section(reader: HistoryReader, days: int, lang: Language) -> None:
    """Render recent trades section."""
    st.header(get_text("recent_trades", lang))

    trades = reader.get_trades(days=days)

    if not trades:
        st.info(get_text("no_trades", lang))
        return

    # Display trades
    data = []
    for t in trades[:50]:  # Limit to 50 most recent
        # Extract from nested structure
        decision = t.get("decision", {})
        result = t.get("result", {})

        action = decision.get("action", "")
        action_emoji = get_action_emoji(action)

        # Parse and convert timestamp to KST
        ts_str = t.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            time_kst = to_kst(ts)
            time_display = time_kst.strftime("%m/%d %H:%M")
        except (ValueError, AttributeError):
            time_display = ts_str[:16].replace("T", " ")

        # Get price and quantity from result
        price = result.get("average_price", 0)
        quantity = result.get("filled_quantity", 0)
        rationale = decision.get("rationale", "")

        data.append({
            get_text("time", lang): time_display,
            get_text("action", lang): f"{action_emoji} {get_action_text(action, lang)}",
            get_text("price", lang): format_krw(price),
            get_text("quantity", lang): f"{quantity:.8f}",
            get_text("rationale", lang): rationale[:80] if rationale else "",
        })

    st.dataframe(
        data,
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    """Main dashboard entry point."""
    # Initialize session state
    if "lang" not in st.session_state:
        st.session_state["lang"] = "ko"

    lang: Language = st.session_state["lang"]

    # Render sidebar and get settings
    days, auto_refresh, refresh_interval = render_sidebar(lang)

    # Initialize reader
    log_dir = get_log_dir()
    reader = HistoryReader(log_dir)

    # Main content
    render_portfolio_section(reader, lang)
    st.divider()

    render_charts_section(reader, days, lang)
    st.divider()

    render_derivatives_section(reader, days, lang)
    st.divider()

    # Two columns for decisions and trades
    col1, col2 = st.columns([2, 1])

    with col1:
        render_decisions_section(reader, days, lang)

    with col2:
        render_trades_section(reader, days, lang)

    # Auto refresh
    if auto_refresh:
        import time

        time.sleep(refresh_interval)
        st.rerun()


if __name__ == "__main__":
    main()
