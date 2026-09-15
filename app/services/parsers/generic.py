"""
Generic fallback parser. This is the exact parsing logic from LedgerLens V1
(tested and confirmed working against real synthetic statements) — wrapped
to match the new BankParser interface. This is the parser used whenever a
statement's bank isn't recognized by a dedicated adapter, and is the one
you can currently trust most, since it's the one that's actually been run
against real data.
"""
from typing import List

import pdfplumber

from app.services.parsers.base import (
    NormalizedTransaction, DATE_PATTERN, AMOUNT_PATTERN,
    detect_payment_mode, guess_txn_type, extract_reference,
)


class GenericParser:
    bank_code = "GENERIC"
    bank_display_name = "Generic / Unrecognized Format"

    def matches(self, text_sample: str) -> bool:
        # Always matches — this is the catch-all fallback, tried last.
        return True

    def parse(self, file_path: str) -> List[NormalizedTransaction]:
        transactions: List[NormalizedTransaction] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        transactions.extend(self._rows_from_table(table))
                else:
                    text = page.extract_text() or ""
                    transactions.extend(self._rows_from_text(text))
        return transactions

    def _rows_from_table(self, table: List[List[str]]) -> List[NormalizedTransaction]:
        rows = []
        for row in table:
            if not row or len(row) < 3:
                continue
            row_text = " ".join(c for c in row if c)
            txn = self._row_to_transaction(row_text)
            if txn:
                rows.append(txn)
        return rows

    def _rows_from_text(self, text: str) -> List[NormalizedTransaction]:
        rows = []
        for line in text.split("\n"):
            txn = self._row_to_transaction(line)
            if txn:
                rows.append(txn)
        return rows

    def _row_to_transaction(self, text: str) -> "NormalizedTransaction | None":
        date_match = DATE_PATTERN.search(text)
        amounts = AMOUNT_PATTERN.findall(text)
        if not date_match or not amounts:
            return None

        amount = float(amounts[-2].replace(",", "")) if len(amounts) >= 2 else float(amounts[-1].replace(",", ""))
        txn_type = guess_txn_type(text)

        return NormalizedTransaction(
            date=date_match.group(1),
            description=text[:200],
            debit=amount if txn_type == "debit" else None,
            credit=amount if txn_type == "credit" else None,
            amount=amount,
            transaction_type=txn_type,
            reference_number=extract_reference(text),
            payment_mode=detect_payment_mode(text),
        )
