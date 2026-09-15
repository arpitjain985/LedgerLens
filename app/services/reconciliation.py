"""
Matches invoice line items to bank transactions.

MVP approach: amount match (within a small tolerance for bank charges/rounding)
+ fuzzy text match on vendor name vs transaction description. This is
deliberately simple and explainable — a CA reviewing the output needs to be
able to see *why* something matched, not just trust a black box.
"""
from typing import List, Dict
from rapidfuzz import fuzz

AMOUNT_TOLERANCE = 1.0  # rupees — allows for minor rounding differences
VENDOR_MATCH_THRESHOLD = 60  # rapidfuzz partial_ratio score out of 100


def reconcile(transactions: List[Dict], invoice_lines: List[Dict]) -> List[Dict]:
    """
    transactions: [{"id", "description", "amount", "txn_type"}, ...]
    invoice_lines: [{"ref", "amount", "vendor"}, ...]

    Returns a list of match results: [{"transaction_id", "invoice_ref", "match_score"}, ...]
    """
    matches = []
    used_invoice_refs = set()

    for txn in transactions:
        best_match = None
        best_score = 0

        for invoice in invoice_lines:
            if invoice["ref"] in used_invoice_refs:
                continue

            amount_diff = abs(txn["amount"] - invoice["amount"])
            if amount_diff > AMOUNT_TOLERANCE:
                continue

            vendor_score = fuzz.partial_ratio(
                invoice.get("vendor", "").lower(),
                txn["description"].lower(),
            )
            if vendor_score >= VENDOR_MATCH_THRESHOLD and vendor_score > best_score:
                best_match = invoice
                best_score = vendor_score

        if best_match:
            used_invoice_refs.add(best_match["ref"])
            matches.append({
                "transaction_id": txn["id"],
                "invoice_ref": best_match["ref"],
                "match_score": best_score,
            })

    return matches
