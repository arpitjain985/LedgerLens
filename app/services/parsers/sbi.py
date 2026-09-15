"""
SBI (State Bank of India) statement adapter.

⚠️ HONEST STATUS: this is built from SBI's publicly documented statement
column conventions (Txn Date / Value Date / Description / Ref No / Debit /
Credit / Balance), NOT validated against a real SBI statement yet — I don't
have one to test against. Detection (matches()) is a safe, conservative
check on the bank's letterhead text, so a real SBI statement should at least
get routed here instead of silently falling through — but the *column
parsing* itself needs verification against a real file before you trust its
output blindly. Treat this as "should work, unverified" per PROGRESS.md.

If it breaks on a real statement: the fix is almost always adjusting how
_row_to_transaction splits columns, not the detection logic.
"""
from typing import List, Optional

import pdfplumber

from app.services.parsers.base import (
    NormalizedTransaction, DATE_PATTERN, AMOUNT_PATTERN,
    detect_payment_mode, guess_txn_type, extract_reference,
)


class SBIParser:
    bank_code = "SBI"
    bank_display_name = "State Bank of India"

    def matches(self, text_sample: str) -> bool:
        lower = text_sample.lower()
        return "state bank of india" in lower or "sbi" in lower.replace(" ", "")

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

        # SBI statements typically list Debit and Credit as separate columns,
        # with Balance as the last amount. If we see 3 amounts, assume
        # [debit_or_blank, credit_or_blank, balance] in some order — since we
        # can't reliably tell which without real column positions, fall back
        # to "last non-balance amount = transaction amount" like the generic
        # parser, but keep the reference/payment-mode extraction SBI-aware.
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
