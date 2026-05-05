"""
agents/whatsapp_agent.py
Handles WhatsApp messaging via Twilio.

Outbound: send daily summary
Inbound: receive your reply via webhook (run with ngrok or a server)

Twilio setup:
  1. Create a Twilio account at twilio.com
  2. Activate WhatsApp Sandbox (or production WA Business number)
  3. Set the sandbox webhook URL to: https://YOUR_NGROK_URL/webhook/whatsapp
  4. Fill in config.yaml with your Twilio credentials
"""
import logging
from typing import Optional

from twilio.rest import Client as TwilioClient

logger = logging.getLogger(__name__)


class WhatsAppAgent:
    def __init__(self, account_sid: str, auth_token: str, from_number: str, to_number: str):
        self.client = TwilioClient(account_sid, auth_token)
        self.from_number = from_number
        self.to_number = to_number

    def send_message(self, message: str) -> str:
        """Send a WhatsApp message. Returns the message SID."""
        msg = self.client.messages.create(
            from_=self.from_number,
            to=self.to_number,
            body=message,
        )
        logger.info(f"WhatsApp message sent: {msg.sid}")
        return msg.sid

    def send_daily_summary(
        self,
        total_recorded: float,
        currency: str,
        undefined_transactions: list,
    ) -> str:
        """Format and send the end-of-day summary."""
        currency_symbol = "Rp" if currency == "IDR" else "฿" if currency == "THB" else currency
        total_fmt = f"{currency_symbol} {total_recorded:,.0f}"

        lines = [
            "📊 *Daily YNAB Summary*",
            f"🗓 {__import__('datetime').date.today().strftime('%A, %d %b %Y')}",
            "",
            f"💰 Total recorded in YNAB: *{total_fmt}*",
            "",
        ]

        if undefined_transactions:
            lines.append(f"⚠️ *{len(undefined_transactions)} transaction(s) need your input:*")
            for i, txn in enumerate(undefined_transactions, 1):
                amt_fmt = f"{currency_symbol} {txn.raw_amount:,.0f}"
                notes_display = txn.notes if txn.notes else "_(no notes)_"
                lines.append(f"{i}. {amt_fmt} | {txn.date} | Notes: {notes_display}")
            lines.append("")
            lines.append("Please reply with:")
            lines.append("1. *Actual balance* in the format: `balance: 1,234,567`")
            lines.append("2. *Category for undefined txns* (one per line):")
            lines.append("   `1: Dining Out / Warung Makan`")
            lines.append("   `2: Shopping / Tokopedia`")
            lines.append("   _(format: `number: Category / Payee`)_")
        else:
            lines.append("✅ All transactions have categories.")
            lines.append("")
            lines.append("Please reply with the *actual account balance*:")
            lines.append("`balance: 1,234,567`")

        message = "\n".join(lines)
        return self.send_message(message)

    def send_reconciliation_result(self, matched: bool, ynab_total: float, actual: float, currency: str):
        """Send the reconciliation outcome."""
        symbol = "Rp" if currency == "IDR" else "฿" if currency == "THB" else currency
        diff = actual - ynab_total

        if matched:
            msg = (
                f"✅ *Reconciliation complete!*\n"
                f"YNAB balance matches your actual balance: *{symbol} {actual:,.0f}*\n"
                f"All cleared transactions marked as reconciled."
            )
        else:
            direction = "over" if diff > 0 else "under"
            msg = (
                f"⚠️ *Balance mismatch detected*\n"
                f"YNAB recorded: {symbol} {ynab_total:,.0f}\n"
                f"Actual balance: {symbol} {actual:,.0f}\n"
                f"Difference: *{symbol} {abs(diff):,.0f} ({direction})*\n\n"
                f"A reconciliation adjustment has been added in YNAB.\n"
                f"Please review your transactions for any missing entries."
            )
        return self.send_message(msg)


def parse_wa_reply(reply_text: str) -> dict:
    """
    Parse the user's WhatsApp reply into structured data.

    Expected format (flexible):
        balance: 1,234,567
        1: Dining Out / Warung Makan
        2: Shopping / Tokopedia

    Returns:
        {
          "actual_balance": 1234567.0 or None,
          "category_updates": {1: {"category": "Dining Out", "payee": "Warung Makan"}, ...}
        }
    """
    import re

    result = {"actual_balance": None, "category_updates": {}}

    for line in reply_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Match balance line: "balance: 1,234,567" or "bal 1234567"
        balance_match = re.match(r"(?:balance|bal|saldo)[:\s]+([\d,.\s]+)", line, re.IGNORECASE)
        if balance_match:
            raw = balance_match.group(1).replace(",", "").replace(".", "").replace(" ", "")
            try:
                result["actual_balance"] = float(raw)
            except ValueError:
                pass
            continue

        # Match category update: "1: Category / Payee" or "1. Category / Payee"
        cat_match = re.match(r"(\d+)[.:]\s*(.+?)(?:\s*/\s*(.+))?$", line)
        if cat_match:
            idx = int(cat_match.group(1))
            category = cat_match.group(2).strip()
            payee = cat_match.group(3).strip() if cat_match.group(3) else category
            result["category_updates"][idx] = {"category": category, "payee": payee}

    return result
