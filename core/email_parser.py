"""
core/email_parser.py
Parses mobile banking payment confirmation emails from HTML bodies.

Strategy:
  1. Parse HTML with BeautifulSoup
  2. Build a flat key→value map from all <table> label/value row pairs
  3. Look up known field labels (Thai + English) in that map
  4. Fall back to plain-text regex if the body is not HTML

Supports Bangkok Bank HTML email format (Thai + English bilingual).
"""
import re
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class ParsedTransaction:
    amount: int           # YNAB milliunits (THB 85.50 → 85500)
    date: str             # ISO date "YYYY-MM-DD"
    date_display: str     # Human-readable English: "Tuesday, 5 May 2026 at 14:54"
    notes: str            # Transaction memo/notes
    raw_amount: float     # Human-readable float (85.50)
    currency: str         # "THB" | "IDR"
    email_subject: str
    email_id: str


class EmailParser:

    # ---- Thai month → int ----
    THAI_MONTHS = {
        "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4,
        "พฤษภาคม": 5, "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8,
        "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
    }
    EN_MONTHS = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    BE_OFFSET = 543  # Buddhist Era → CE

    # ---- Field label lookups (Thai first, English fallback) ----
    # Each list is tried in order; first match wins.
    AMOUNT_LABELS  = ["จำนวนเงิน (บาท)", "จำนวนเงิน", "amount (baht)", "amount"]
    NOTES_LABELS   = ["บันทึก", "note", "notes", "remark", "message",
                      "keterangan", "berita", "description"]
    DATE_LABELS    = ["วันที่", "date"]

    # ================================================================
    # Public entry point
    # ================================================================
    def parse(self, email_body: str, email_subject: str, email_id: str) -> Optional[ParsedTransaction]:
        try:
            is_html = bool(re.search(r"<\s*html|<\s*table|<\s*td", email_body, re.IGNORECASE))

            if is_html:
                kv = self._extract_kv_from_html(email_body)
                logger.debug(f"Parsed key-value map: {kv}")
                amount, raw_amount, currency = self._amount_from_kv(kv, email_body)
                date_iso, date_display       = self._date_from_kv(kv)
                notes                        = self._notes_from_kv(kv)
            else:
                amount, raw_amount, currency = self._amount_from_text(email_body)
                date_iso, date_display       = self._date_from_text(email_body)
                notes                        = self._notes_from_text(email_body)

            if amount is None:
                logger.warning(f"Could not extract amount from email {email_id}")
                return None

            if date_iso is None:
                date_iso = datetime.now().strftime("%Y-%m-%d")
                date_display = datetime.now().strftime("%A, %-d %B %Y")
                logger.warning(f"No date found in {email_id}, using today")

            return ParsedTransaction(
                amount=amount,
                date=date_iso,
                date_display=date_display or date_iso,
                notes=notes or "",
                raw_amount=raw_amount,
                currency=currency,
                email_subject=email_subject,
                email_id=email_id,
            )
        except Exception as e:
            logger.error(f"Failed to parse email {email_id}: {e}", exc_info=True)
            return None

    # ================================================================
    # HTML parsing — build a flat label → value dict from all tables
    # ================================================================
    def _extract_kv_from_html(self, html: str) -> dict[str, str]:
        """
        Walk every <tr> in the email. If a row has exactly 2–3 <td>s
        and the second-to-last td looks like a label (short, no numbers),
        map label.lower() → value (last td text).

        Bangkok Bank layout:  [spacer td] [label td] [value td]
        """
        soup = BeautifulSoup(html, "html.parser")
        kv: dict[str, str] = {}

        for tr in soup.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            # Need at least 2 real tds
            if len(tds) < 2:
                continue

            # Strip nbsp and whitespace from all cells
            texts = [td.get_text(separator=" ", strip=True).replace("\xa0", "").strip()
                     for td in tds]

            # Drop leading blank/spacer cells
            texts = [t for t in texts if t]

            if len(texts) == 2:
                label, value = texts[0], texts[1]
                kv[label.lower()] = value
            # colspan rows (section headers like "จาก:" / "From:") — skip

        return kv

    def _lookup(self, kv: dict, labels: list[str]) -> Optional[str]:
        """Return first matching value from kv given a priority list of labels."""
        for label in labels:
            if label.lower() in kv:
                return kv[label.lower()]
        return None

    # ================================================================
    # Amount
    # ================================================================
    def _amount_from_kv(self, kv: dict, raw_html: str) -> tuple[Optional[int], float, str]:
        currency = "THB" if ("บาท" in raw_html or "Baht" in raw_html or "THB" in raw_html) else "IDR"
        raw_str = self._lookup(kv, self.AMOUNT_LABELS)
        if raw_str:
            val = self._parse_number(raw_str)
            if val and val > 0:
                return int(val * 1000), val, currency
        return None, 0.0, currency

    def _amount_from_text(self, body: str) -> tuple[Optional[int], float, str]:
        currency = "THB" if ("บาท" in body or "THB" in body or "฿" in body) else "IDR"
        patterns = [
            r"จำนวนเงิน\s*(?:\(บาท\))?\s*([\d,]+\.?\d*)",
            r"(?:THB|฿)\s*([\d,]+\.?\d*)",
            r"(?:Rp\.?\s*|IDR\s*)([\d.,]+)",
            r"[Aa]mount[:\s]+(?:THB|฿|Rp\.?|IDR)?\s*([\d,]+\.?\d*)",
        ]
        for p in patterns:
            m = re.search(p, body)
            if m:
                val = self._parse_number(m.group(1))
                if val and val > 0:
                    return int(val * 1000), val, currency
        return None, 0.0, currency

    def _parse_number(self, s: str) -> Optional[float]:
        try:
            return float(s.strip().replace(",", ""))
        except ValueError:
            return None

    # ================================================================
    # Date
    # ================================================================
    def _date_from_kv(self, kv: dict) -> tuple[Optional[str], Optional[str]]:
        raw = self._lookup(kv, self.DATE_LABELS)
        if not raw:
            return None, None

        # Try English first: "5 May 2026 at 14:54:54 (Thailand time)"
        m = re.search(
            r"(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})"
            r"(?:\s+at\s+(\d{2}:\d{2}))?",
            raw, re.IGNORECASE
        )
        if m:
            d  = int(m.group(1))
            mo = self.EN_MONTHS[m.group(2).lower()[:3]]
            y  = int(m.group(3))
            t  = m.group(4)
            return self._build_date(y, mo, d, t)

        # Thai: "5 พฤษภาคม 2569 เวลา 14:54:54 น."
        pattern = r"(\d{1,2})\s+(" + "|".join(self.THAI_MONTHS.keys()) + r")\s+(\d{4})" \
                  r"(?:.*?(\d{2}:\d{2}))?"
        m = re.search(pattern, raw)
        if m:
            d  = int(m.group(1))
            mo = self.THAI_MONTHS[m.group(2)]
            y  = int(m.group(3)) - self.BE_OFFSET
            t  = m.group(4)
            return self._build_date(y, mo, d, t)

        return None, None

    def _date_from_text(self, body: str) -> tuple[Optional[str], Optional[str]]:
        """Plain-text fallbacks."""
        # ISO
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", body)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return self._build_date(y, mo, d, None)
        # DD/MM/YYYY
        m = re.search(r"(\d{2})[/-](\d{2})[/-](\d{4})", body)
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return self._build_date(y, mo, d, None)
        # Thai
        pattern = r"(\d{1,2})\s+(" + "|".join(self.THAI_MONTHS.keys()) + r")\s+(\d{4})" \
                  r"(?:.*?(\d{2}:\d{2}))?"
        m = re.search(pattern, body)
        if m:
            d  = int(m.group(1))
            mo = self.THAI_MONTHS[m.group(2)]
            y  = int(m.group(3)) - self.BE_OFFSET
            t  = m.group(4)
            return self._build_date(y, mo, d, t)
        return None, None

    def _build_date(self, y: int, mo: int, d: int, time_str: Optional[str]):
        dt = datetime(y, mo, d)
        iso = dt.strftime("%Y-%m-%d")
        display = f"{dt.strftime('%A')}, {d} {dt.strftime('%B')} {y}"
        if time_str:
            display += f" at {time_str}"
        return iso, display

    # ================================================================
    # Notes
    # ================================================================
    def _notes_from_kv(self, kv: dict) -> Optional[str]:
        return self._lookup(kv, self.NOTES_LABELS)

    def _notes_from_text(self, body: str) -> Optional[str]:
        patterns = [
            r"บันทึก\s+(.+?)(?:\n|$)",
            r"[Nn]otes?[:\s]+(.+?)(?:\n|$)",
            r"[Kk]eterangan[:\s]+(.+?)(?:\n|$)",
            r"[Rr]emark[:\s]+(.+?)(?:\n|$)",
        ]
        for p in patterns:
            m = re.search(p, body, re.IGNORECASE)
            if m:
                v = m.group(1).strip()
                if v:
                    return v
        return None