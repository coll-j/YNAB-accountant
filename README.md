# OpenClaw YNAB Agent

Automated transaction recording from mobile banking emails → YNAB,
with end-of-day WhatsApp summary and interactive reconciliation.

---

## Architecture

```
Gmail (payment email)
       │
       ▼
  EmailAgent (polls every 60s)
       │
       ▼
  EmailParser (extract amount, date, notes)
       │
       ▼
  RulesEngine (map notes → category/payee)
       │
       ▼
  YNABAgent (create transaction)
       │
  StateManager (persist locally)

23:59 daily ──► WhatsApp Summary
                      │
               You reply via WA
                      │
               Webhook (Flask)
                      │
               ┌──────┴──────┐
          Update cats    Reconcile YNAB
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Gmail API
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **Gmail API**
3. Create **OAuth 2.0 credentials** (Desktop App) → Download as `credentials/gmail_oauth.json`
4. Run one-time auth:
   ```bash
   python -c "from agents.email_agent import EmailAgent; EmailAgent.authorize()"
   ```
   This opens a browser for you to approve access, then saves `credentials/gmail_token.json`.

### 3. YNAB
1. Get your **Personal Access Token** at: https://app.youneedabudget.com/settings/developer
2. Find your **Budget ID** from the YNAB URL: `https://app.youneedabudget.com/BUDGET_ID/budget`
3. Find your **Account ID**:
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" \
     https://api.youneedabudget.com/v1/budgets/YOUR_BUDGET_ID/accounts
   ```
4. Fill in `config.yaml`

### 4. Twilio WhatsApp
1. Create a [Twilio account](https://www.twilio.com/)
2. Activate the **WhatsApp Sandbox** (or upgrade to Business)
3. Note your `account_sid` and `auth_token`
4. Set sandbox webhook to: `https://YOUR_PUBLIC_URL/webhook/whatsapp`
5. Fill in `config.yaml`

### 5. Expose webhook (local dev)
Use [ngrok](https://ngrok.com/) to expose Flask locally:
```bash
ngrok http 5000
# Copy the https URL → paste in Twilio sandbox settings
```

### 6. Configure rules
Edit `config.yaml` → `rules:` section. Add keywords matching your
transaction notes to map them to YNAB categories and payees.

---

## Running

```bash
python main.py
```

This starts:
- **Email polling** loop (background thread)
- **Scheduler** for 23:59 daily summary (background thread)
- **Flask webhook** server on port 5000 (foreground)

---

## Daily Flow

```
Throughout day:
  Payment email arrives → agent records in YNAB automatically

At 23:59:
  WhatsApp message to you:
  ┌─────────────────────────────────────┐
  │ 📊 Daily YNAB Summary               │
  │ 🗓 Monday, 04 May 2026              │
  │                                     │
  │ 💰 Total recorded: Rp 450,000       │
  │                                     │
  │ ⚠️ 2 transactions need your input:  │
  │ 1. Rp 75,000 | Notes: (no notes)   │
  │ 2. Rp 120,000 | Notes: pak budi    │
  │                                     │
  │ Reply with:                         │
  │ balance: 1,234,567                  │
  │ 1: Groceries / Warung               │
  │ 2: Personal / Pak Budi             │
  └─────────────────────────────────────┘

You reply:
  balance: 5,230,000
  1: Groceries / Warung
  2: Personal / Pak Budi

Agent:
  → Updates categories in YNAB
  → Reconciles if balance matches
  → Reports difference if not
```

---

## Customizing Email Parsing

If your bank's email format isn't parsed correctly:

1. Print a raw email body:
   ```python
   from agents.email_agent import EmailAgent
   import yaml
   cfg = yaml.safe_load(open("config.yaml"))
   ea = EmailAgent(cfg["gmail"]["credentials_file"], cfg["gmail"]["token_file"], "payment")
   emails = ea.fetch_new_payment_emails()
   print(emails[0]["body"])
   ```

2. Edit `core/email_parser.py`:
   - Add a new pattern to `AMOUNT_PATTERNS`
   - Add a new pattern to `NOTES_PATTERNS`
   - Adjust `_extract_date()` for your bank's date format

---

## File Structure

```
openclaw-ynab/
├── main.py                   # Orchestrator + Flask webhook
├── config.yaml               # Credentials, rules, settings
├── requirements.txt
├── agents/
│   ├── email_agent.py        # Gmail polling
│   ├── ynab_agent.py         # YNAB REST API client
│   └── whatsapp_agent.py     # Twilio WhatsApp send + reply parser
├── core/
│   ├── email_parser.py       # Extract amount/date/notes from email body
│   ├── rules_engine.py       # Keyword → category/payee mapping
│   └── state.py              # JSON persistence layer
├── credentials/              # (git-ignored) OAuth tokens
└── data/
    └── state.json            # Daily transaction state
```

---

## Notes
- `state.json` auto-resets each day
- Processed email IDs are tracked — no double-recording
- YNAB's reconciliation endpoint handles balance adjustments automatically
- All amounts stored in YNAB milliunits internally (IDR 50,000 = 50,000,000 milliunits)
