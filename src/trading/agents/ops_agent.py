"""Operations and alerting agent."""

import logging
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from trading.config import get_settings
from trading.core.time import KST
from trading.core.decision_history import DecisionRecord, get_decision_writer
from trading.core.derivatives_history import get_derivatives_writer
from trading.core.isolated_balance import get_isolated_tracker
from trading.core.state import TradingState

logger = logging.getLogger(__name__)

# Module-level rate limiting for Slack
_last_slack_send_time: float = 0.0
_MIN_SLACK_INTERVAL_SECONDS: float = 2.0  # Minimum 2 seconds between messages


def _get_portfolio_section(current_price: float) -> str:
    """Get portfolio section for Slack message if isolated mode is active.

    Args:
        current_price: Current BTC price in KRW.

    Returns:
        Formatted portfolio section string, or empty string if not in isolated mode.
    """
    tracker = get_isolated_tracker()
    if tracker is None:
        return ""

    if current_price <= 0:
        return ""

    portfolio = tracker.get_portfolio_value(current_price)

    # Skip if no activity yet (still at initial capital)
    initial = portfolio["initial_capital_krw"]
    total = portfolio["total_value_krw"]

    # Format return with sign
    pnl_pct = portfolio["pnl_pct"]
    return_sign = "+" if pnl_pct >= 0 else ""

    section = (
        f"\n\n💰 *봇 포트폴리오*\n"
        f"• 초기 자본: {initial:,.0f} KRW\n"
        f"• 현재 가치: {total:,.0f} KRW ({return_sign}{pnl_pct:.1f}%)\n"
        f"• 보유 KRW: {portfolio['krw_balance']:,.0f}\n"
        f"• 보유 BTC: {portfolio['btc_balance']:.8f}\n"
        f"• 총 수수료: {portfolio['total_fees_krw']:,.0f} KRW"
    )

    return section


class OpsAgent:
    """Agent for monitoring and sending alerts."""

    def __init__(self, slack_webhook: str | None = None):
        """Initialize ops agent.

        Args:
            slack_webhook: Slack webhook URL (uses config if None).
        """
        settings = get_settings()
        self.slack_webhook = slack_webhook or settings.slack_webhook_url

        # Email settings
        self.email_enabled = settings.email_enabled
        self.email_smtp_server = settings.email_smtp_server
        self.email_smtp_port = settings.email_smtp_port
        self.email_sender = settings.email_sender
        self.email_password = settings.email_password
        self.email_recipient = settings.email_recipient

    @property
    def is_slack_enabled(self) -> bool:
        """Check if Slack notifications are enabled."""
        return bool(self.slack_webhook)

    @property
    def is_email_enabled(self) -> bool:
        """Check if Email notifications are enabled."""
        return self.email_enabled and all([
            self.email_smtp_server,
            self.email_sender,
            self.email_password,
            self.email_recipient,
        ])

    def send_slack_message(self, message: str, color: str = "#36a64f") -> bool:
        """Send message to Slack with rate limiting.

        Args:
            message: Message text.
            color: Attachment color (green=#36a64f, red=#ff0000, yellow=#ffcc00).

        Returns:
            True if sent successfully.
        """
        global _last_slack_send_time

        if not self.slack_webhook:
            logger.debug("Slack webhook not configured")
            return False

        # Rate limiting: wait if necessary
        now = time.time()
        elapsed = now - _last_slack_send_time
        if elapsed < _MIN_SLACK_INTERVAL_SECONDS:
            wait_time = _MIN_SLACK_INTERVAL_SECONDS - elapsed
            logger.debug(f"Slack rate limit: waiting {wait_time:.2f}s")
            time.sleep(wait_time)

        payload = {
            "attachments": [
                {
                    "color": color,
                    "text": message,
                    "footer": "Auto Trading Bot",
                    "ts": datetime.now(KST).timestamp(),
                }
            ]
        }

        try:
            response = requests.post(
                self.slack_webhook,
                json=payload,
                timeout=5,
            )
            response.raise_for_status()
            _last_slack_send_time = time.time()
            return True

        except requests.RequestException as e:
            logger.error(f"Failed to send Slack message: {e}")
            _last_slack_send_time = time.time()  # Still update to avoid rapid retries
            return False

    def send_email(self, subject: str, body: str) -> bool:
        """Send email notification.

        Args:
            subject: Email subject.
            body: Email body (plain text).

        Returns:
            True if sent successfully.
        """
        if not self.is_email_enabled:
            logger.debug("Email not configured")
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self.email_sender
            msg["To"] = self.email_recipient
            msg["Subject"] = f"[Trading Bot] {subject}"

            # Add timestamp to body
            full_body = f"{body}\n\n---\n{datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}"
            msg.attach(MIMEText(full_body, "plain"))

            with smtplib.SMTP(self.email_smtp_server, self.email_smtp_port) as server:
                server.starttls()
                server.login(self.email_sender, self.email_password)
                server.send_message(msg)

            logger.info(f"Email sent: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def send_alert(self, subject: str, message: str, color: str = "#36a64f") -> None:
        """Send alert via all configured channels.

        Args:
            subject: Alert subject (for email).
            message: Alert message.
            color: Slack color.
        """
        # Send to Slack
        self.send_slack_message(message, color)

        # Send to Email
        # Convert markdown-like format to plain text
        plain_message = message.replace("*", "").replace("•", "-")
        self.send_email(subject, plain_message)

    def alert_trade_executed(
        self,
        action: str,
        symbol: str,
        price: float,
        quantity: float,
        rationale: str,
    ) -> None:
        """Send alert for executed trade.

        Args:
            action: Trade action (BUY/SELL).
            symbol: Trading pair.
            price: Execution price.
            quantity: Executed quantity.
            rationale: Decision rationale.
        """
        emoji = "📈" if action == "BUY" else "📉"
        color = "#36a64f" if action == "BUY" else "#ff6b6b"
        action_kr = "매수" if action == "BUY" else "매도"

        message = (
            f"{emoji} *거래 체결*\n"
            f"• 액션: {action_kr}\n"
            f"• 종목: {symbol}\n"
            f"• 가격: {price:,.0f} KRW\n"
            f"• 수량: {quantity:.8f}\n"
            f"• 판단근거: {rationale[:200]}"
        )

        # Add portfolio section if in isolated mode
        if price > 0:
            message += _get_portfolio_section(price)

        self.send_alert(f"거래 체결: {action_kr} {symbol}", message, color)
        logger.info(f"Trade alert sent: {action} {quantity:.8f} {symbol} @ {price:,.0f}")

    def alert_error(self, error: str, context: str = "") -> None:
        """Send alert for system error.

        Args:
            error: Error message.
            context: Additional context.
        """
        message = (
            f"🚨 *시스템 오류*\n"
            f"• 오류: {error}\n"
        )
        if context:
            message += f"• 컨텍스트: {context}"

        self.send_alert("시스템 오류", message, "#ff0000")
        logger.error(f"Error alert sent: {error}")

    def alert_kill_switch(self, reason: str) -> None:
        """Send alert when kill switch is activated.

        Args:
            reason: Reason for activation.
        """
        message = (
            f"🛑 *긴급 정지 활성화*\n"
            f"• 사유: {reason}\n"
            f"• 모든 거래가 중단되었습니다."
        )

        self.send_alert("긴급 정지 활성화", message, "#ff0000")
        logger.critical(f"Kill switch alert: {reason}")

    def alert_decision(
        self,
        action: str,
        confidence: float,
        rationale: str,
        current_price: float = 0,
    ) -> None:
        """Send alert for trading decision.

        Args:
            action: Decision action (BUY/SELL/HOLD).
            confidence: Confidence level (0-1).
            rationale: Decision rationale.
            current_price: Current BTC price.
        """
        emoji_map = {"BUY": "📈", "SELL": "📉", "HOLD": "⏸️"}
        color_map = {"BUY": "#36a64f", "SELL": "#ff6b6b", "HOLD": "#808080"}
        action_kr_map = {"BUY": "매수", "SELL": "매도", "HOLD": "보유"}

        emoji = emoji_map.get(action, "📊")
        color = color_map.get(action, "#808080")
        action_kr = action_kr_map.get(action, action)

        message = (
            f"{emoji} *거래 결정: {action_kr}*\n"
            f"• 확신도: {confidence:.0%}\n"
            f"• 현재가: {current_price:,.0f} KRW\n"
            f"• 판단근거: {rationale[:300]}"
        )

        # Add portfolio section if in isolated mode
        if current_price > 0:
            message += _get_portfolio_section(current_price)

        self.send_alert(f"거래 결정: {action_kr}", message, color)
        logger.info(f"Decision alert sent: {action} ({confidence:.0%})")

def ops_agent_node(state: TradingState) -> dict:
    """LangGraph node function for ops agent.

    Args:
        state: Current trading state.

    Returns:
        State updates (usually none, just sends alerts).
    """
    logger.info("Ops agent: sending alerts")
    agent = OpsAgent()

    try:
        # Note: Anomaly alerts removed - view in dashboard instead

        # Check for errors to alert
        error = state.get("error")
        if error:
            agent.alert_error(error)

        # Note: News alerts removed - view in dashboard instead

        # Check for executed trades only
        decision = state.get("decision")
        market = state.get("market") or {}

        if decision:
            action = decision.get("action", "HOLD")
            status = decision.get("status", "")

            if status == "executed":
                # Alert for executed trade only
                agent.alert_trade_executed(
                    action=action,
                    symbol=market.get("symbol", "KRW-BTC"),
                    price=market.get("current_price", 0),
                    quantity=decision.get("suggested_size_pct", 0) / 100,
                    rationale=decision.get("rationale", ""),
                )
            else:
                # All non-executed decisions (BUY/SELL/HOLD) logged only, view in dashboard
                logger.debug(
                    f"Decision logged (no alert): {action} (confidence={decision.get('confidence', 0):.0%})"
                )

            # Record decision to history for dashboard (with final status)
            writer = get_decision_writer()
            if writer:
                writer.record(DecisionRecord(
                    timestamp=datetime.now(KST),
                    action=action,
                    confidence=decision.get("confidence", 0),
                    rationale=decision.get("rationale", ""),
                    status=status,
                    market_price=market.get("current_price", 0),
                    was_executed=(status == "executed"),
                    original_action=decision.get("original_action"),
                    cycle_count=state.get("cycle_count", 0),
                ))

        # Record derivatives data for dashboard
        derivatives = state.get("derivatives")
        if derivatives:
            derivatives_writer = get_derivatives_writer()
            if derivatives_writer:
                derivatives_writer.record_from_state(
                    derivatives, state.get("cycle_count", 0)
                )

        # Check kill switch
        risk = state.get("risk") or {}
        if risk.get("is_kill_switch_on"):
            agent.alert_kill_switch("Risk limit breached")

        return {
            "last_updated": datetime.now(KST).isoformat(),
        }

    except Exception as e:
        logger.error(f"Ops agent failed: {e}")
        return {
            "error": f"Ops agent error: {e}",
            "last_updated": datetime.now(KST).isoformat(),
        }
