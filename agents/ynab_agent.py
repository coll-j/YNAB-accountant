"""
agents/ynab_agent.py
Wraps the YNAB v1 REST API for all transaction operations.
Docs: https://api.youneedabudget.com/v1
"""
import logging
from typing import Optional
import rich
import ynab
from ynab.models.post_transactions_wrapper import PostTransactionsWrapper
from ynab.models.transaction_cleared_status import TransactionClearedStatus as TransactionClearedStatus

import requests

logger = logging.getLogger(__name__)

YNAB_BASE = "https://api.youneedabudget.com/v1"


class YNABAgent:
    def __init__(
            self, 
            api_token: str, 
            budget_id: str, 
            account_id: str):
        
        self.ynab_configuration = ynab.Configuration(access_token=api_token)
        self.ynab_client = ynab.ApiClient(self.ynab_configuration)
        self.budget_id = budget_id
        self.account_id = account_id

        self.transactions_api = ynab.TransactionsApi(self.ynab_client)
        self.account_api = ynab.AccountsApi(self.ynab_client)

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
                "amount": -abs(amount)*1000,   # always outflow, convert to milliunits
                "category_id": category_id,
                "cleared": TransactionClearedStatus.CLEARED,
                "approved": True,
            }
        }

        if payee_id:
            payload["transaction"]["payee_id"] = payee_id
        if memo:
            payload["transaction"]["memo"] = memo

        data = ynab.PostTransactionsWrapper().from_dict(payload) # PostTransactionsWrapper | The transaction or transactions to create.  To create a single transaction you can specify a value for the `transaction` object and to create multiple transactions you can specify an array of `transactions`.  It is expected that you will only provide a value for one of these objects.

        # Create an instance of the API class
        try:
            # Create a single transaction or multiple transactions
            api_response = self.transactions_api.create_transaction(self.budget_id, data)
            print("The response of TransactionsApi->create_transaction:\n")
            logger.info(f"Created YNAB transaction with details:")
            logger.info(rich.print(api_response.data.transaction))
            return api_response.data.transaction.id
        
        except Exception as e:
            logger.info("Exception when calling TransactionsApi->create_transaction: %s\n" % e)
            return -1

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

        data = ynab.PutTransactionWrapper(transaction=updates)

        try:
            # Update a transaction
            api_response = self.transactions_api.update_transaction(self.budget_id, transaction_id, data)
            print("The response of TransactionsApi->update_transaction:\n")
            logger.info(rich.print(api_response.data.transaction))
        except Exception as e:
            print("Exception when calling TransactionsApi->update_transaction: %s\n" % e)

    def get_account_balance(self) -> float:
        """Returns the cleared balance of the account in human units."""
        try:
            # Get an account
            api_response = self.account_api.get_account_by_id(self.budget_id, self.account_id)
            print("The response of AccountsApi->get_account_by_id:\n")
            rich.print(api_response)

            balances = {
                "balance": api_response.data.account.balance / 1000,  # convert from milliunits to units
                "cleared_balance": api_response.data.account.cleared_balance / 1000,
                "uncleared_balance": api_response.data.account.uncleared_balance / 1000,
            }

            logger.info(f"Fetched account balance: {balances}")
            return balances
        
        except Exception as e:
            print("Exception when calling AccountsApi->get_account_by_id: %s\n" % e)
            logger.error("Failed to fetch account balance")
            return {"balance": 0, "cleared_balance": 0, "uncleared_balance": 0}


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


