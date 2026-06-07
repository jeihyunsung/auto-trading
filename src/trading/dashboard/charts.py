"""Chart components for dashboard using Plotly."""

from datetime import datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from trading.core.derivatives_history import DerivativesSnapshot
from trading.core.indicator_history import IndicatorSnapshot
from trading.dashboard.i18n import Language, get_text


def _add_trade_markers(
    fig: go.Figure,
    trades: list[dict],
    row: int | None = None,
    col: int | None = None,
    lang: Language = "ko",
) -> None:
    """Add BUY/SELL markers to a price chart.

    Args:
        fig: Plotly figure to add markers to.
        trades: List of trade dicts with timestamp, decision.action, result.average_price.
        row: Subplot row (None for single plot).
        col: Subplot column (None for single plot).
        lang: Language for labels.
    """
    if not trades:
        return

    # Separate BUY and SELL trades
    buy_times, buy_prices = [], []
    sell_times, sell_prices = [], []

    for trade in trades:
        try:
            ts = trade.get("timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)

            action = trade.get("decision", {}).get("action", "").upper()
            price = trade.get("result", {}).get("average_price")

            if not price or price <= 0:
                continue

            if action == "BUY":
                buy_times.append(ts)
                buy_prices.append(price)
            elif action == "SELL":
                sell_times.append(ts)
                sell_prices.append(price)
        except Exception:
            continue

    # Add BUY markers (green, triangle-up)
    if buy_times:
        trace_kwargs = dict(
            x=buy_times,
            y=buy_prices,
            mode="markers",
            name=get_text("buy", lang),
            marker=dict(
                symbol="triangle-up",
                size=12,
                color="#22C55E",
                line=dict(width=1, color="white"),
            ),
            hovertemplate=f"{get_text('buy', lang)}: %{{y:,.0f}} KRW<br>%{{x}}<extra></extra>",
        )
        if row is not None and col is not None:
            fig.add_trace(go.Scatter(**trace_kwargs), row=row, col=col)
        else:
            fig.add_trace(go.Scatter(**trace_kwargs))

    # Add SELL markers (red, triangle-down)
    if sell_times:
        trace_kwargs = dict(
            x=sell_times,
            y=sell_prices,
            mode="markers",
            name=get_text("sell", lang),
            marker=dict(
                symbol="triangle-down",
                size=12,
                color="#EF4444",
                line=dict(width=1, color="white"),
            ),
            hovertemplate=f"{get_text('sell', lang)}: %{{y:,.0f}} KRW<br>%{{x}}<extra></extra>",
        )
        if row is not None and col is not None:
            fig.add_trace(go.Scatter(**trace_kwargs), row=row, col=col)
        else:
            fig.add_trace(go.Scatter(**trace_kwargs))


def create_price_chart(
    indicators: list[IndicatorSnapshot],
    lang: Language = "ko",
    trades: list[dict] | None = None,
) -> go.Figure:
    """Create BTC price chart with optional trade markers.

    Args:
        indicators: List of indicator snapshots.
        lang: Language for labels.
        trades: Optional list of trade dicts to show as markers.

    Returns:
        Plotly figure.
    """
    if not indicators:
        fig = go.Figure()
        fig.add_annotation(
            text=get_text("no_data", lang),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        return fig

    timestamps = [i.timestamp for i in indicators]
    prices = [i.btc_price for i in indicators]

    # Calculate Y-axis range with 5% padding
    min_price = min(prices)
    max_price = max(prices)
    price_range = max_price - min_price
    padding = price_range * 0.05 if price_range > 0 else max_price * 0.01
    y_min = min_price - padding
    y_max = max_price + padding

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=prices,
            mode="lines",
            name=get_text("btc_price", lang),
            line=dict(color="#F7931A", width=2),
        )
    )

    fig.update_layout(
        title=get_text("btc_price", lang),
        xaxis_title="",
        yaxis_title="KRW",
        height=300,
        margin=dict(l=0, r=0, t=40, b=0),
        yaxis=dict(tickformat=",", range=[y_min, y_max]),
        hovermode="x unified",
    )

    # Add trade markers if provided
    if trades:
        _add_trade_markers(fig, trades, lang=lang)

    return fig


def create_rsi_chart(
    indicators: list[IndicatorSnapshot],
    lang: Language = "ko",
) -> go.Figure:
    """Create RSI chart with overbought/oversold zones.

    Args:
        indicators: List of indicator snapshots.
        lang: Language for labels.

    Returns:
        Plotly figure.
    """
    if not indicators:
        fig = go.Figure()
        fig.add_annotation(
            text=get_text("no_data", lang),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        return fig

    timestamps = [i.timestamp for i in indicators]
    rsi_values = [i.rsi for i in indicators]

    fig = go.Figure()

    # Overbought zone (70-100)
    fig.add_hrect(
        y0=70,
        y1=100,
        fillcolor="rgba(255, 99, 71, 0.1)",
        line_width=0,
    )

    # Oversold zone (0-30)
    fig.add_hrect(
        y0=0,
        y1=30,
        fillcolor="rgba(50, 205, 50, 0.1)",
        line_width=0,
    )

    # RSI line
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=rsi_values,
            mode="lines",
            name=get_text("rsi", lang),
            line=dict(color="#8B5CF6", width=2),
        )
    )

    # Reference lines
    fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5)
    fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5)
    fig.add_hline(y=50, line_dash="dot", line_color="gray", opacity=0.3)

    fig.update_layout(
        title=get_text("rsi", lang),
        xaxis_title="",
        yaxis_title="RSI",
        height=250,
        margin=dict(l=0, r=0, t=40, b=0),
        yaxis=dict(range=[0, 100]),
        hovermode="x unified",
    )

    # Add annotations for zones
    fig.add_annotation(
        x=timestamps[-1] if timestamps else datetime.now(),
        y=80,
        text=get_text("overbought", lang),
        showarrow=False,
        font=dict(color="red", size=10),
        xanchor="right",
    )
    fig.add_annotation(
        x=timestamps[-1] if timestamps else datetime.now(),
        y=20,
        text=get_text("oversold", lang),
        showarrow=False,
        font=dict(color="green", size=10),
        xanchor="right",
    )

    return fig


def create_macd_chart(
    indicators: list[IndicatorSnapshot],
    lang: Language = "ko",
) -> go.Figure:
    """Create MACD chart with histogram and signal line.

    Args:
        indicators: List of indicator snapshots.
        lang: Language for labels.

    Returns:
        Plotly figure.
    """
    if not indicators:
        fig = go.Figure()
        fig.add_annotation(
            text=get_text("no_data", lang),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        return fig

    timestamps = [i.timestamp for i in indicators]
    macd_line = [i.macd_line for i in indicators]
    signal_line = [i.macd_signal for i in indicators]
    histogram = [i.macd_histogram for i in indicators]

    # Color histogram bars based on value
    colors = ["green" if h >= 0 else "red" for h in histogram]

    fig = go.Figure()

    # Histogram bars
    fig.add_trace(
        go.Bar(
            x=timestamps,
            y=histogram,
            name=get_text("histogram", lang),
            marker_color=colors,
            opacity=0.6,
        )
    )

    # MACD line
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=macd_line,
            mode="lines",
            name="MACD",
            line=dict(color="#3B82F6", width=2),
        )
    )

    # Signal line
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=signal_line,
            mode="lines",
            name=get_text("signal", lang),
            line=dict(color="#EF4444", width=1.5, dash="dash"),
        )
    )

    # Zero line
    fig.add_hline(y=0, line_dash="solid", line_color="gray", opacity=0.3)

    fig.update_layout(
        title=get_text("macd", lang),
        xaxis_title="",
        yaxis_title="MACD",
        height=250,
        margin=dict(l=0, r=0, t=40, b=0),
        hovermode="x unified",
        barmode="relative",
    )

    return fig


def create_combined_chart(
    indicators: list[IndicatorSnapshot],
    lang: Language = "ko",
    trades: list[dict] | None = None,
    asset: str = "BTC",
) -> go.Figure:
    """Create combined chart with price, RSI, and MACD subplots.

    Args:
        indicators: List of indicator snapshots.
        lang: Language for labels.
        trades: Optional list of trade dicts to show as markers on price chart.
        asset: Asset symbol used to render the price label dynamically.

    Returns:
        Plotly figure with subplots.
    """
    price_label = get_text("asset_price", lang).format(asset=asset)
    if not indicators:
        fig = go.Figure()
        fig.add_annotation(
            text=get_text("no_data", lang),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        return fig

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.5, 0.25, 0.25],
        subplot_titles=(
            price_label,
            get_text("rsi", lang),
            get_text("macd", lang),
        ),
    )

    timestamps = [i.timestamp for i in indicators]
    prices = [i.btc_price for i in indicators]
    rsi_values = [i.rsi for i in indicators]
    macd_line = [i.macd_line for i in indicators]
    signal_line = [i.macd_signal for i in indicators]
    histogram = [i.macd_histogram for i in indicators]

    # Calculate Y-axis range for price with 5% padding
    min_price = min(prices)
    max_price = max(prices)
    price_range = max_price - min_price
    padding = price_range * 0.05 if price_range > 0 else max_price * 0.01
    y_min = min_price - padding
    y_max = max_price + padding

    # Price chart
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=prices,
            mode="lines",
            name=price_label,
            line=dict(color="#F7931A", width=2),
        ),
        row=1,
        col=1,
    )

    # RSI chart
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=rsi_values,
            mode="lines",
            name=get_text("rsi", lang),
            line=dict(color="#8B5CF6", width=2),
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=2, col=1)

    # MACD histogram
    colors = ["green" if h >= 0 else "red" for h in histogram]
    fig.add_trace(
        go.Bar(
            x=timestamps,
            y=histogram,
            name=get_text("histogram", lang),
            marker_color=colors,
            opacity=0.6,
        ),
        row=3,
        col=1,
    )

    # MACD lines
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=macd_line,
            mode="lines",
            name="MACD",
            line=dict(color="#3B82F6", width=2),
        ),
        row=3,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=signal_line,
            mode="lines",
            name=get_text("signal", lang),
            line=dict(color="#EF4444", width=1.5, dash="dash"),
        ),
        row=3,
        col=1,
    )

    # Update layout
    fig.update_layout(
        height=700,
        margin=dict(l=0, r=0, t=40, b=0),
        hovermode="x unified",
        showlegend=False,
    )

    # Update y-axes
    fig.update_yaxes(tickformat=",", range=[y_min, y_max], row=1, col=1)
    fig.update_yaxes(range=[0, 100], row=2, col=1)

    # Add trade markers to price subplot
    if trades:
        _add_trade_markers(fig, trades, row=1, col=1, lang=lang)

    return fig


def create_bollinger_bands_chart(
    indicators: list[IndicatorSnapshot],
    lang: Language = "ko",
    trades: list[dict] | None = None,
) -> go.Figure:
    """Create Bollinger Bands chart with price overlay and trade markers.

    Args:
        indicators: List of indicator snapshots.
        lang: Language for labels.
        trades: Optional list of trade dicts to show as markers.

    Returns:
        Plotly figure.
    """
    if not indicators:
        fig = go.Figure()
        fig.add_annotation(
            text=get_text("no_data", lang),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        return fig

    timestamps = [i.timestamp for i in indicators]
    prices = [i.btc_price for i in indicators]
    bb_upper = [i.bb_upper for i in indicators]
    bb_middle = [i.bb_middle for i in indicators]
    bb_lower = [i.bb_lower for i in indicators]

    # Filter out zero values (missing data)
    has_bb_data = any(u > 0 for u in bb_upper)

    # Calculate Y-axis range with 5% padding
    # Include BB bands if available for proper scaling
    all_values = prices.copy()
    if has_bb_data:
        all_values.extend([v for v in bb_upper if v > 0])
        all_values.extend([v for v in bb_lower if v > 0])
    min_val = min(all_values)
    max_val = max(all_values)
    val_range = max_val - min_val
    padding = val_range * 0.05 if val_range > 0 else max_val * 0.01
    y_min = min_val - padding
    y_max = max_val + padding

    fig = go.Figure()

    if has_bb_data:
        # Upper band
        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=bb_upper,
                mode="lines",
                name=get_text("bb_upper", lang),
                line=dict(color="rgba(59, 130, 246, 0.5)", width=1),
            )
        )

        # Lower band (fill between upper and lower)
        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=bb_lower,
                mode="lines",
                name=get_text("bb_lower", lang),
                line=dict(color="rgba(59, 130, 246, 0.5)", width=1),
                fill="tonexty",
                fillcolor="rgba(59, 130, 246, 0.1)",
            )
        )

        # Middle band (SMA 20)
        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=bb_middle,
                mode="lines",
                name=get_text("bb_middle", lang),
                line=dict(color="#3B82F6", width=1, dash="dash"),
            )
        )

    # Price line (always show)
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=prices,
            mode="lines",
            name=get_text("btc_price", lang),
            line=dict(color="#F7931A", width=2),
        )
    )

    fig.update_layout(
        title=get_text("bollinger_bands", lang),
        xaxis_title="",
        yaxis_title="KRW",
        height=300,
        margin=dict(l=0, r=0, t=40, b=0),
        yaxis=dict(tickformat=",", range=[y_min, y_max]),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # Add trade markers if provided
    if trades:
        _add_trade_markers(fig, trades, lang=lang)

    return fig


def create_obv_chart(
    indicators: list[IndicatorSnapshot],
    lang: Language = "ko",
) -> go.Figure:
    """Create On-Balance Volume chart.

    Args:
        indicators: List of indicator snapshots.
        lang: Language for labels.

    Returns:
        Plotly figure.
    """
    if not indicators:
        fig = go.Figure()
        fig.add_annotation(
            text=get_text("no_data", lang),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        return fig

    timestamps = [i.timestamp for i in indicators]
    obv_values = [i.obv for i in indicators]

    # Check if we have OBV data
    has_obv_data = any(v != 0 for v in obv_values)

    fig = go.Figure()

    if has_obv_data:
        # Color based on OBV trend (comparing to previous value)
        colors = []
        for i, obv in enumerate(obv_values):
            if i == 0:
                colors.append("#3B82F6")  # neutral blue for first
            elif obv >= obv_values[i - 1]:
                colors.append("#22C55E")  # green for increasing
            else:
                colors.append("#EF4444")  # red for decreasing

        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=obv_values,
                mode="lines",
                name=get_text("obv", lang),
                line=dict(color="#3B82F6", width=2),
            )
        )

        # Add area fill with gradient effect
        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=obv_values,
                mode="none",
                fill="tozeroy",
                fillcolor="rgba(59, 130, 246, 0.1)",
                showlegend=False,
            )
        )

        # Zero line
        fig.add_hline(y=0, line_dash="solid", line_color="gray", opacity=0.3)
    else:
        fig.add_annotation(
            text=get_text("no_data", lang),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )

    fig.update_layout(
        title=get_text("obv", lang),
        xaxis_title="",
        yaxis_title="Volume",
        height=250,
        margin=dict(l=0, r=0, t=40, b=0),
        yaxis=dict(tickformat=","),
        hovermode="x unified",
    )

    return fig


def create_derivatives_chart(
    derivatives: list[DerivativesSnapshot],
    lang: Language = "ko",
) -> go.Figure:
    """Create derivatives data chart with L/S ratio, funding rate, and OI.

    Args:
        derivatives: List of derivatives snapshots.
        lang: Language for labels.

    Returns:
        Plotly figure with subplots.
    """
    if not derivatives or len(derivatives) < 2:
        fig = go.Figure()
        fig.add_annotation(
            text=get_text("no_data", lang),
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
        return fig

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.35, 0.35, 0.30],
        subplot_titles=(
            get_text("long_short_ratio", lang),
            get_text("funding_rate", lang),
            get_text("open_interest", lang),
        ),
    )

    timestamps = [d.timestamp for d in derivatives]
    ls_ratio = [d.long_short_ratio for d in derivatives]
    top_ls_ratio = [d.top_trader_long_short_ratio for d in derivatives]
    funding_rate = [d.funding_rate * 100 for d in derivatives]  # Convert to %
    oi_value = [d.open_interest_value / 1_000_000_000 for d in derivatives]  # In Billions

    # --- Row 1: Long/Short Ratio ---
    # Global L/S ratio
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=ls_ratio,
            mode="lines",
            name=get_text("global_ls", lang),
            line=dict(color="#3B82F6", width=2),
        ),
        row=1,
        col=1,
    )

    # Top trader L/S ratio
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=top_ls_ratio,
            mode="lines",
            name=get_text("top_trader_ls", lang),
            line=dict(color="#8B5CF6", width=2, dash="dash"),
        ),
        row=1,
        col=1,
    )

    # Balanced zone (0.8-1.2)
    fig.add_hrect(
        y0=0.8,
        y1=1.2,
        fillcolor="rgba(128, 128, 128, 0.1)",
        line_width=0,
        row=1,
        col=1,
    )
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray", opacity=0.5, row=1, col=1)
    fig.add_hline(y=1.5, line_dash="dot", line_color="red", opacity=0.3, row=1, col=1)
    fig.add_hline(y=0.67, line_dash="dot", line_color="green", opacity=0.3, row=1, col=1)

    # --- Row 2: Funding Rate ---
    # Color based on positive/negative
    colors = ["#EF4444" if f > 0 else "#22C55E" for f in funding_rate]

    fig.add_trace(
        go.Bar(
            x=timestamps,
            y=funding_rate,
            name=get_text("funding_rate", lang),
            marker_color=colors,
            opacity=0.7,
        ),
        row=2,
        col=1,
    )

    # Overheated thresholds
    fig.add_hline(y=0.1, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
    fig.add_hline(y=-0.05, line_dash="dash", line_color="green", opacity=0.5, row=2, col=1)
    fig.add_hline(y=0, line_dash="solid", line_color="gray", opacity=0.3, row=2, col=1)

    # --- Row 3: Open Interest ---
    # Color based on change
    oi_colors = []
    for i, oi in enumerate(oi_value):
        if i == 0:
            oi_colors.append("#3B82F6")
        elif oi >= oi_value[i - 1]:
            oi_colors.append("#22C55E")
        else:
            oi_colors.append("#EF4444")

    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=oi_value,
            mode="lines",
            name=get_text("open_interest", lang),
            line=dict(color="#F7931A", width=2),
        ),
        row=3,
        col=1,
    )

    # Add area fill
    fig.add_trace(
        go.Scatter(
            x=timestamps,
            y=oi_value,
            mode="none",
            fill="tozeroy",
            fillcolor="rgba(247, 147, 26, 0.1)",
            showlegend=False,
        ),
        row=3,
        col=1,
    )

    # Update layout
    fig.update_layout(
        height=500,
        margin=dict(l=0, r=0, t=40, b=0),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    # Update y-axes
    fig.update_yaxes(title_text="Ratio", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_yaxes(title_text="$B", row=3, col=1)

    return fig
