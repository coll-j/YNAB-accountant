"""
core/state.py
Lightweight JSON-based state persistence.
Tracks: today's transactions, pending (undefined category) items,
and conversation context for the WA reply flow.
"""
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/state.json")


@dataclass
class Transaction:
    ynab_id: str                   # YNAB transaction ID after creation
    amount: int                    # milliunits
    raw_amount: float
    currency: str
    date: str
    notes: str
    category_id: Optional[str]        # None if not resolved
    payee_id: Optional[str]
    email_id: str
    recorded_at: str               # ISO datetime
    reconciled: bool = False


@dataclass
class AgentState:
    date: str                      # "YYYY-MM-DD" — resets daily
    transactions: list[Transaction] = field(default_factory=list)
    processed_email_ids: list[str] = field(default_factory=list)
    # Pending WA conversation context
    awaiting_wa_reply: bool = False
    wa_conversation_id: Optional[str] = None


class StateManager:
    def __init__(self, state_file: Path = STATE_FILE):
        self.state_file = state_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    # ---- Persistence ----

    def _load(self) -> AgentState:
        today = date.today().isoformat()
        if self.state_file.exists():
            try:
                raw = json.loads(self.state_file.read_text())
                if raw.get("date") == today:
                    txns = [Transaction(**t) for t in raw.get("transactions", [])]
                    return AgentState(
                        date=raw["date"],
                        transactions=txns,
                        processed_email_ids=raw.get("processed_email_ids", []),
                        awaiting_wa_reply=raw.get("awaiting_wa_reply", False),
                        wa_conversation_id=raw.get("wa_conversation_id"),
                    )
            except Exception as e:
                logger.error(f"Could not load state: {e}")
        # New day / fresh state
        return AgentState(date=today)

    def save(self):
        data = {
            "date": self._state.date,
            "transactions": [asdict(t) for t in self._state.transactions],
            "processed_email_ids": self._state.processed_email_ids,
            "awaiting_wa_reply": self._state.awaiting_wa_reply,
            "wa_conversation_id": self._state.wa_conversation_id,
        }
        self.state_file.write_text(json.dumps(data, indent=2))

    # ---- Accessors ----

    @property
    def transactions(self) -> list[Transaction]:
        return self._state.transactions

    @property
    def processed_email_ids(self) -> list[str]:
        return self._state.processed_email_ids

    @property
    def awaiting_wa_reply(self) -> bool:
        return self._state.awaiting_wa_reply

    # ---- Mutations ----

    def add_transaction(self, txn: Transaction):
        self._state.transactions.append(txn)
        self._state.processed_email_ids.append(txn.email_id)
        self.save()

    def mark_email_processed(self, email_id: str):
        if email_id not in self._state.processed_email_ids:
            self._state.processed_email_ids.append(email_id)
            self.save()

    def is_email_processed(self, email_id: str) -> bool:
        return email_id in self._state.processed_email_ids

    def update_transaction(self, ynab_id: str, **kwargs):
        for txn in self._state.transactions:
            if txn.ynab_id == ynab_id:
                for k, v in kwargs.items():
                    setattr(txn, k, v)
        self.save()

    def set_awaiting_wa_reply(self, flag: bool, conversation_id: str = None):
        self._state.awaiting_wa_reply = flag
        self._state.wa_conversation_id = conversation_id
        self.save()

    def get_undefined_transactions(self) -> list[Transaction]:
        """Transactions with no category resolved."""
        return [t for t in self._state.transactions if t.category_id is None]

    def get_total_recorded(self) -> float:
        """Sum of all transaction amounts (raw)."""
        return sum(t.raw_amount for t in self._state.transactions)

    def reset_for_new_day(self):
        self._state = AgentState(date=date.today().isoformat())
        self.save()
