"""
main.py
OpenClaw YNAB Agent — Main Orchestrator

Runs two loops in parallel:
  1. Email polling loop  — checks Gmail every N seconds for payment emails
  2. Scheduler          — fires the daily summary at 23:59
  3. Flask webhook      — receives WhatsApp replies from Twilio

Usage:
    python main.py

Requires:
    pip install -r requirements.txt
    Gmail OAuth token in credentials/ (run EmailAgent.authorize() once)
    config.yaml filled in with your credentials and rules
"""
import logging
import threading
import time
from datetime import datetime, date

import schedule
import yaml
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse

from agents.email_agent import EmailAgent
from agents.ynab_agent import YNABAgent
from agents.whatsapp_agent import WhatsAppAgent, parse_wa_reply
from core.email_parser import EmailParser
from core.rules_engine import RulesEngine
from core.state import StateManager, Transaction

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================
# Bootstrap
# ============================================================
def load_config() -> dict:
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)


cfg = load_config()
state = StateManager()

email_agent = EmailAgent(
    credentials_file=cfg["gmail"]["credentials_file"],
    token_file=cfg["gmail"]["token_file"],
    trigger_keyword=cfg["gmail"]["trigger_subject_keyword"],
)
ynab = YNABAgent(
    api_token=cfg["ynab"]["api_token"],
    budget_id=cfg["ynab"]["budget_id"],
    account_id=cfg["ynab"]["account_id"],
)
wa = WhatsAppAgent(
    account_sid=cfg["whatsapp"]["account_sid"],
    auth_token=cfg["whatsapp"]["auth_token"],
    from_number=cfg["whatsapp"]["from_number"],
    to_number=cfg["whatsapp"]["to_number"],
)
rules = RulesEngine(cfg["rules"])
parser = EmailParser()


# ============================================================
# Email → YNAB pipeline
# ============================================================
def process_payment_email(email: dict):
    """Parse email, resolve category, create YNAB transaction."""
    if state.is_email_processed(email["id"]):
        return

    logger.info(f"Processing email: {email['subject']}")

    # 1. Parse
    parsed = parser.parse(email["body"], email["subject"], email["id"])
    if not parsed:
        logger.warning(f"Could not parse email {email['id']}, skipping.")
        email_agent.mark_as_read(email["id"])
        state.mark_email_processed(email["id"])
        return

    # 2. Resolve category
    match = rules.match(parsed.notes)
    category_id = match.category_id if match else None
    payee_id = match.payee_id if match else None

    # 3. Record in YNAB
    try:
        ynab_id = ynab.create_transaction(
            date=parsed.date,
            amount=parsed.amount,
            payee_id=payee_id,
            category_id=category_id,
            memo=parsed.notes,
        )
    except Exception as e:
        logger.error(f"YNAB create failed for email {email['id']}: {e}")
        return

    # 4. Persist to local state
    txn = Transaction(
        ynab_id=ynab_id,
        amount=parsed.amount,
        raw_amount=parsed.raw_amount,
        currency=parsed.currency,
        date=parsed.date,
        notes=parsed.notes,
        category_id=category_id,
        payee_id=payee_id,
        email_id=email["id"],
        recorded_at=datetime.now().isoformat(),
    )
    state.add_transaction(txn)

    if match:
        logger.info(f"✅ Recorded: {payee_id} | {parsed.currency} {parsed.raw_amount:,.0f} → {category_id}")
    else:
        logger.info(f"⚠️  Recorded (no category): {parsed.raw_amount:,.0f} | notes='{parsed.notes}'")

    email_agent.mark_as_read(email["id"])


def email_polling_loop():
    """Runs continuously, polling Gmail every N seconds."""
    interval = cfg["gmail"]["poll_interval_seconds"]
    logger.info(f"Email polling started (every {interval}s)")
    while True:
        try:
            emails = email_agent.fetch_new_payment_emails()
            for email in emails:
                process_payment_email(email)
        except Exception as e:
            logger.error(f"Email polling error: {e}")
        time.sleep(interval)


# ============================================================
# Daily summary job
# ============================================================
def send_daily_summary():
    """Called at 23:59 daily by the scheduler."""
    logger.info("Sending daily summary via WhatsApp...")
    txns = state.transactions
    if not txns:
        wa.send_message("📊 No transactions recorded today.")
        return

    currency = txns[0].currency if txns else "IDR"
    total = state.get_total_recorded()
    undefined = state.get_undefined_transactions()

    wa.send_daily_summary(total, currency, undefined)
    state.set_awaiting_wa_reply(True, conversation_id="daily")
    logger.info(f"Summary sent: total={total}, undefined={len(undefined)}")


# ============================================================
# WhatsApp reply handler (Flask webhook)
# ============================================================
app = Flask(__name__)


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """Twilio calls this when you send a WhatsApp reply."""
    incoming = request.form.get("Body", "")
    sender = request.form.get("From", "")

    logger.info(f"WA reply from {sender}: {incoming}")

    if not state.awaiting_wa_reply:
        # Not in a conversation — ignore
        return Response(str(MessagingResponse()), mimetype="text/xml")

    try:
        handle_wa_reply(incoming)
    except Exception as e:
        logger.error(f"Failed to handle WA reply: {e}")
        wa.send_message(f"❌ Error processing reply: {e}\nPlease try again.")

    return Response(str(MessagingResponse()), mimetype="text/xml")


def handle_wa_reply(reply_text: str):
    """
    Process the user's reply:
      1. Update undefined transaction categories in YNAB
      2. Reconcile if balance matches, or report difference
    """
    parsed_reply = parse_wa_reply(reply_text)
    undefined = state.get_undefined_transactions()
    currency = state.transactions[0].currency if state.transactions else "IDR"

    # --- Update categories for undefined transactions ---
    for idx, update in parsed_reply["category_updates"].items():
        if 1 <= idx <= len(undefined):
            txn = undefined[idx - 1]
            category_id = update["category_id"]
            payee_id = update["payee_id"]

            ynab.update_transaction(
                transaction_id=txn.ynab_id,
                category_id=category_id,
                payee_id=payee_id,
            )
            state.update_transaction(txn.ynab_id, category_id=category_id, payee_id=payee_id)
            logger.info(f"Updated txn {txn.ynab_id}: {category_id} / {payee_id}")

    # --- Reconcile if balance provided ---
    actual_balance = parsed_reply.get("actual_balance")
    if actual_balance is not None:
        ynab_balance = ynab.get_account_balance()
        matched = abs(ynab_balance - actual_balance) < 1  # within 1 unit tolerance

        # Mark all today's transactions as cleared
        for txn in state.transactions:
            ynab.mark_cleared(txn.ynab_id)

        if matched:
            # Trigger YNAB reconciliation
            ynab.reconcile_account(int(actual_balance * 1000))
        else:
            # YNAB reconcile will create an adjustment transaction automatically
            ynab.reconcile_account(int(actual_balance * 1000))

        wa.send_reconciliation_result(matched, ynab_balance, actual_balance, currency)
        state.set_awaiting_wa_reply(False)

    elif not parsed_reply["category_updates"]:
        wa.send_message(
            "I couldn't parse your reply. Please use:\n"
            "`balance: 1,234,567`\n"
            "`1: Category / Payee`"
        )


# ============================================================
# Scheduler thread
# ============================================================
def scheduler_loop():
    summary_time = cfg["scheduler"]["daily_summary_time"]
    schedule.every().day.at(summary_time).do(send_daily_summary)
    logger.info(f"Scheduler started — daily summary at {summary_time}")
    while True:
        schedule.run_pending()
        time.sleep(30)


# ============================================================
# Entry point
# ============================================================
if __name__ == "__main__":
    # Start email polling in background thread
    email_thread = threading.Thread(target=email_polling_loop, daemon=True)
    email_thread.start()

    # Start scheduler in background thread
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    scheduler_thread.start()

    # Start Flask webhook server (foreground)
    # In production: use gunicorn or expose via ngrok
    logger.info("Starting Flask webhook server on port 5000...")
    logger.info("To expose locally: ngrok http 5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
