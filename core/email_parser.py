"""
core/email_parser.py
Parses mobile banking payment confirmation emails.

Adapt the regex patterns to match your bank's email format.
The parser supports common formats — you may need to tweak
the patterns for your specific bank (BCA, Mandiri, BNI, etc.)
"""
import re
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ParsedTransaction:
    amount: int           # in milliunits (YNAB format: IDR 50,000 → 50000000)
    date: str             # ISO date string: "2026-05-04"
    notes: str            # raw notes / transaction description from email
    raw_amount: float     # human-readable amount
    currency: str         # e.g. "IDR"
    email_subject: str
    email_id: str


class EmailParser:
    """
    Parses payment confirmation emails from Indonesian/Thai mobile banking.
    Patterns below cover common formats — adjust regexes as needed.
    """

    # ---- Amount patterns ----
    AMOUNT_PATTERNS = [
        # "Rp 50.000,00" or "Rp50,000.00" or "IDR 50,000"
        r"(?:Rp\.?\s*|IDR\s*)([\d.,]+)",
        # "THB 1,500.00" or "฿1,500"
        r"(?:THB\s*|฿\s*)([\d.,]+)",
        # Generic: "Amount: 50,000"
        r"[Aa]mount[:\s]+(?:Rp\.?\s*|IDR\s*|THB\s*|฿\s*)?([\d.,]+)",
        # "Total: 50000"
        r"[Tt]otal[:\s]+([\d.,]+)",
    ]

    # ---- Date patterns ----
    DATE_PATTERNS = [
        # "04/05/2026" or "04-05-2026"
        r"(\d{2})[/-](\d{2})[/-](\d{4})",
        # "2026-05-04"
        r"(\d{4})-(\d{2})-(\d{2})",
        # "04 May 2026" or "May 04, 2026"
        r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})",
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})",
    ]

    MONTH_MAP = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    # ---- Notes patterns ----
    NOTES_PATTERNS = [
        r"[Nn]otes?[:\s]+(.+?)(?:\n|$)",
        r"[Kk]eterangan[:\s]+(.+?)(?:\n|$)",       # Indonesian
        r"[Bb]erita[:\s]+(.+?)(?:\n|$)",            # Indonesian "berita transfer"
        r"[Dd]escription[:\s]+(.+?)(?:\n|$)",
        r"[Rr]emark[:\s]+(.+?)(?:\n|$)",
        r"[Pp]urpose[:\s]+(.+?)(?:\n|$)",
        r"[Mm]essage[:\s]+(.+?)(?:\n|$)",
    ]

    def parse(self, email_body: str, email_subject: str, email_id: str) -> Optional[ParsedTransaction]:
        """Parse a payment confirmation email into a structured transaction."""
        try:
            amount, raw_amount, currency = self._extract_amount(email_body)
            date = self._extract_date(email_body)
            notes = self._extract_notes(email_body)

            if amount is None:
                logger.warning(f"Could not extract amount from email {email_id}")
                return None

            if date is None:
                # Fall back to today
                date = datetime.now().strftime("%Y-%m-%d")
                logger.warning(f"Could not extract date from email {email_id}, using today")

            return ParsedTransaction(
                amount=amount,
                date=date,
                notes=notes or "",
                raw_amount=raw_amount,
                currency=currency,
                email_subject=email_subject,
                email_id=email_id,
            )
        except Exception as e:
            logger.error(f"Failed to parse email {email_id}: {e}")
            return None

    def _extract_amount(self, body: str) -> tuple[Optional[int], float, str]:
        """Returns (milliunits, raw_amount, currency)."""
        currency = "IDR"  # default
        if "THB" in body or "฿" in body:
            currency = "THB"

        for pattern in self.AMOUNT_PATTERNS:
            match = re.search(pattern, body)
            if match:
                raw_str = match.group(1)
                raw_amount = self._parse_number(raw_str)
                if raw_amount and raw_amount > 0:
                    # YNAB uses milliunits: multiply by 1000
                    milliunits = int(raw_amount * 1000)
                    return milliunits, raw_amount, currency

        return None, 0.0, currency

    def _parse_number(self, s: str) -> Optional[float]:
        """Handle both 50.000,00 (European) and 50,000.00 (US) formats."""
        s = s.strip()
        # European format: last separator is comma
        if re.search(r",\d{2}$", s):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
        try:
            return float(s)
        except ValueError:
            return None

    def _extract_date(self, body: str) -> Optional[str]:
        """Returns ISO date string YYYY-MM-DD."""
        # Try YYYY-MM-DD first (unambiguous)
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", body)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

        # DD/MM/YYYY or DD-MM-YYYY
        m = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", body)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

        # "04 May 2026"
        m = re.search(
            r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})",
            body, re.IGNORECASE
        )
        if m:
            day = int(m.group(1))
            month = self.MONTH_MAP[m.group(2).lower()[:3]]
            year = int(m.group(3))
            return f"{year}-{month:02d}-{day:02d}"

        # "May 04, 2026"
        m = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})",
            body, re.IGNORECASE
        )
        if m:
            month = self.MONTH_MAP[m.group(1).lower()[:3]]
            day = int(m.group(2))
            year = int(m.group(3))
            return f"{year}-{month:02d}-{day:02d}"

        return None

    def _extract_notes(self, body: str) -> Optional[str]:
        """Extract transaction notes/description from email body."""
        for pattern in self.NOTES_PATTERNS:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                notes = match.group(1).strip()
                if notes:
                    return notes
        return None
