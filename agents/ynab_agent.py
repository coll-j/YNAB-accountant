"""
agents/ynab_agent.py
Wraps the YNAB v1 REST API for all transaction operations.
Docs: https://api.youneedabudget.com/v1
"""
import logging
from typing import Optional
import ynab
from ynab.models.post_transactions_wrapper import PostTransactionsWrapper

import requests

logger = logging.getLogger(__name__)

YNAB_BASE = "https://api.youneedabudget.com/v1"


class YNABAgent:
    def __init__(self, api_token: str, budget_id: str):
        
        self.ynab_configuration = ynab.Configuration(access_token=api_token)
        self.ynab_client = ynab.ApiClient(self.ynab_configuration)
        self.budget_id = budget_id

        # self.budget_id = budget_id
        # self.account_id = account_id
        # self.session = requests.Session()
        # self.session.headers.update({
        #     "Authorization": f"Bearer {api_token}",
        #     "Content-Type": "application/json",
        # })

    # ---- Core methods ----

    def create_transaction(
        self,
        date: str,           # "YYYY-MM-DD"
        amount: int,         # milliunits (negative = outflow)
        payee_id: Optional[str],
        category_id: Optional[str],
        memo: Optional[str],
    ) -> Optional[str]:
        """
        Creates a transaction and returns the YNAB transaction ID.
        Amount should be negative for spending (outflow).
        """

        payload = {
            "transaction": {
                "account_id": self.account_id,
                "date": date,
                "amount": -abs(amount),   # always outflow
                "payee_name": payee_name or "Unknown",
                "category_id": category_id,
                "memo": memo,
                "cleared": "uncleared",
                "approved": False,
            }
        }

        resp = self.session.post(
            f"{YNAB_BASE}/budgets/{self.budget_id}/transactions",
            json=payload,
        )
        resp.raise_for_status()
        txn_id = resp.json()["data"]["transaction"]["id"]
        logger.info(f"Created YNAB transaction {txn_id} for {payee_name} ({amount})")
        return txn_id

    def update_transaction(
        self,
        transaction_id: str,
        category_name: Optional[str] = None,
        payee_name: Optional[str] = None,
        memo: Optional[str] = None,
        cleared: Optional[str] = None,   # "cleared" | "uncleared" | "reconciled"
    ):
        """Patch an existing transaction."""
        updates = {}
        if category_name:
            cid = self._resolve_category_id(category_name)
            if cid:
                updates["category_id"] = cid
        if payee_name:
            updates["payee_name"] = payee_name
        if memo:
            updates["memo"] = memo
        if cleared:
            updates["cleared"] = cleared

        if not updates:
            return

        resp = self.session.put(
            f"{YNAB_BASE}/budgets/{self.budget_id}/transactions/{transaction_id}",
            json={"transaction": updates},
        )
        resp.raise_for_status()
        logger.info(f"Updated YNAB transaction {transaction_id}: {updates}")

    def get_account_balance(self) -> float:
        """Returns the cleared balance of the account in human units."""
        resp = self.session.get(
            f"{YNAB_BASE}/budgets/{self.budget_id}/accounts/{self.account_id}"
        )
        resp.raise_for_status()
        account = resp.json()["data"]["account"]
        # YNAB balance is in milliunits
        return account["cleared_balance"] / 1000

    def reconcile_account(self, actual_balance_milliunits: int):
        """
        Marks all cleared transactions as reconciled and creates a
        reconciliation adjustment if the balance doesn't match.
        Uses YNAB's reconcile endpoint.
        """
        resp = self.session.post(
            f"{YNAB_BASE}/budgets/{self.budget_id}/accounts/{self.account_id}/reconcile",
            json={"current_balance": actual_balance_milliunits},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        logger.info(f"Reconciliation complete. Adjustment: {data.get('reconciliation_transaction', {})}")
        return data

    def mark_cleared(self, transaction_id: str):
        """Mark a single transaction as cleared."""
        self.update_transaction(transaction_id, cleared="cleared")

    def get_today_transactions(self) -> list[dict]:
        """Fetch all transactions for the mbanking account from today."""
        from datetime import date
        today = date.today().isoformat()
        resp = self.session.get(
            f"{YNAB_BASE}/budgets/{self.budget_id}/accounts/{self.account_id}/transactions",
            params={"since_date": today},
        )
        resp.raise_for_status()
        return resp.json()["data"]["transactions"]

    # ---- Helpers ----

    def _get_categories(self) -> list[dict]:
        """Fetch all categories (cached per instance)."""
        if not hasattr(self, "_categories_cache"):
            resp = self.session.get(
                f"{YNAB_BASE}/budgets/{self.budget_id}/categories"
            )
            resp.raise_for_status()
            groups = resp.json()["data"]["category_groups"]
            self._categories_cache = [
                cat
                for group in groups
                for cat in group["categories"]
                if not cat["deleted"] and not cat["hidden"]
            ]
        return self._categories_cache

    def _resolve_category_id(self, category_name: str) -> Optional[str]:
        """Find YNAB category ID by name (case-insensitive partial match)."""
        name_lower = category_name.lower()
        for cat in self._get_categories():
            if cat["name"].lower() == name_lower:
                return cat["id"]
        # Try partial match
        for cat in self._get_categories():
            if name_lower in cat["name"].lower():
                return cat["id"]
        logger.warning(f"Category '{category_name}' not found in YNAB")
        return None
