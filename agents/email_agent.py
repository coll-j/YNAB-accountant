"""
agents/email_agent.py
Polls Gmail for payment confirmation emails and triggers transaction recording.

Setup:
  1. Go to Google Cloud Console → Enable Gmail API
  2. Create OAuth 2.0 credentials → download as credentials/gmail_oauth.json
  3. Run `python -c "from agents.email_agent import EmailAgent; EmailAgent.authorize()"` once
     to generate the token file interactively.
"""
import base64
import logging
import os
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class EmailAgent:
    def __init__(self, credentials_file: str, token_file: str, trigger_keyword: str):
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self.trigger_keyword = trigger_keyword.lower()
        self._service = self._build_service()

    @staticmethod
    def authorize(credentials_file: str = "credentials/gmail_oauth.json",
                  token_file: str = "credentials/gmail_token.json"):
        """Run this once manually to authorize Gmail access."""
        flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
        creds = flow.run_local_server(port=0)
        Path(token_file).write_text(creds.to_json())
        print(f"Token saved to {token_file}")

    def _build_service(self):
        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.token_file.write_text(creds.to_json())
            else:
                raise RuntimeError(
                    "Gmail not authorized. Run EmailAgent.authorize() first."
                )
        return build("gmail", "v1", credentials=creds)

    def fetch_new_payment_emails(self, since_history_id: Optional[str] = None) -> list[dict]:
        """
        Returns a list of unread emails whose subject contains the trigger keyword.
        Each item: {id, subject, body, date}
        """
        query = f'subject:"{self.trigger_keyword}" is:unread'
        results = self._service.users().messages().list(
            userId="me", q=query
        ).execute()

        messages = results.get("messages", [])
        parsed = []
        for msg_ref in messages:
            detail = self._get_message_detail(msg_ref["id"])
            if detail:
                parsed.append(detail)
        return parsed

    def _get_message_detail(self, msg_id: str) -> Optional[dict]:
        try:
            msg = self._service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            subject = headers.get("Subject", "")
            date = headers.get("Date", "")

            body = self._extract_body(msg["payload"])
            return {
                "id": msg_id,
                "subject": subject,
                "body": body,
                "date": date,
            }
        except Exception as e:
            logger.error(f"Failed to fetch email {msg_id}: {e}")
            return None

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract plain text body from email payload."""
        body = ""
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    data = part["body"].get("data", "")
                    body += base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                elif "parts" in part:
                    body += self._extract_body(part)
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        return body

    def mark_as_read(self, msg_id: str):
        """Mark an email as read after processing."""
        try:
            self._service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
        except Exception as e:
            logger.warning(f"Could not mark email {msg_id} as read: {e}")
