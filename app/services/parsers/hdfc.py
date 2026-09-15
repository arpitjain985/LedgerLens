"""
HDFC Bank statement adapter.

⚠️ HONEST STATUS: same caveat as sbi.py — built from HDFC's publicly known
column convention (Date / Narration / Chq-Ref No / Value Dt / Withdrawal Amt
/ Deposit Amt / Closing Balance), not yet validated against a real HDFC
statement. Detection is conservative (letterhead text match); column parsing
needs real-file verification. See PROGRESS.md.
"""
from typing import List, Optional

import pdfplumber

from app.services.parsers.base import (
    NormalizedTransaction, DATE_PATTERN, AMOUNT_PATTERN,
    detect_payment_mode, guess_txn_type, extract_reference,
)


class HDFCParser:
    bank_code = "HDFC"
    bank_display_name = "HDFC Bank"

    def matches(self, text_sample: str) -> bool:
        lower = text_sample.lower()
        return "hdfc bank" in lower or "hdfc0" in lower  # HDFC IFSC codes start with HDFC0

    def parse(self, file_path: str) -> List[NormalizedTransaction]:
        transactions: List[NormalizedTransaction] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        txn = self._row_to_transaction(row)
                        if txn:
                            transactions.append(txn)
                if not tables:
                    text = page.extract_text() or ""
                    for line in text.split("\n"):
                        txn = self._row_to_transaction([line])
                        if txn:
                            transactions.append(txn)
        return transactions

    def _row_to_transaction(self, row: List[Optional[str]]) -> "NormalizedTransaction | None":
        row_text = " ".join(c for c in row if c)
        date_match = DATE_PATTERN.search(row_text)
        amounts = AMOUNT_PATTERN.findall(row_text)
        if not date_match or not amounts:
            return None

        # HDFC narration column often contains "Value Dt" as a second date,
        # which is fine — DATE_PATTERN just grabs the first one it finds
        # (transaction date, listed first in HDFC's convention).
        if len(amounts) >= 2:
            amount = float(amounts[-2].replace(",", ""))
            balance = float(amounts[-1].replace(",", ""))
        else:
            amount = float(amounts[-1].replace(",", ""))
            balance = None

        txn_type = guess_txn_type(row_text)

        return NormalizedTransaction(
            date=date_match.group(1),
            description=row_text[:200],
            debit=amount if txn_type == "debit" else None,
            credit=amount if txn_type == "credit" else None,
            amount=amount,
            transaction_type=txn_type,
            balance=balance,
            reference_number=extract_reference(row_text),
            payment_mode=detect_payment_mode(row_text),
        )
