"""
Flags transactions that look unusual relative to the rest of the statement.

MVP approach — three independent rules, any one of which can flag a transaction:

  1. Duplicate detection: same amount + same description appearing more than
     once (classic sign of an accidental double payment).
  2. Z-score outlier *within its own ledger head group*: catches a transaction
     that's unusual relative to similar transactions (e.g. one abnormally
     large rent payment among several normal ones).
  3. Absolute high-value flag, checked *across the whole statement regardless
     of ledger head group*.

Rule 3 exists specifically to cover a real gap in rule 2: a large one-off
transaction that gets misclassified (low confidence) into a small or
unrelated group won't stand out enough within that group's own z-score to
cross the threshold — even though it's obviously large in absolute terms.
Concretely: a stray ₹3,45,000 wire transfer landing in a 4-transaction
"SALES_RECEIPT" group (mean ~₹1.78L) only scored a z-score of ~1.45, well
under the old 2.5 cutoff — a human reviewing the statement would flag it
instantly just by size, so rule 3 catches that case directly instead of
relying on the group statistics alone.

This is intentionally still lightweight — an isolation forest or similar is
a reasonable "advanced version" upgrade, not an MVP requirement.
"""
from collections import defaultdict
from typing import List, Dict

import numpy as np

from app.config import (
    ANOMALY_ZSCORE_THRESHOLD,
    ANOMALY_MIN_GROUP_SIZE,
    ANOMALY_HIGH_VALUE_THRESHOLD,
)


def flag_anomalies(transactions: List[Dict]) -> List[Dict]:
    """
    transactions: [{"id", "description", "amount", "predicted_ledger_head"}, ...]
    Returns: [{"transaction_id", "is_anomaly", "reason"}, ...]
    """
    # --- Rule 1: Duplicate detection ---
    seen = defaultdict(list)
    for txn in transactions:
        key = (round(txn["amount"], 2), txn["description"].strip().lower())
        seen[key].append(txn["id"])

    duplicate_ids = set()
    for key, ids in seen.items():
        if len(ids) > 1:
            duplicate_ids.update(ids)

    # --- Rule 2: Z-score outliers per ledger head ---
    by_head = defaultdict(list)
    for txn in transactions:
        head = txn.get("predicted_ledger_head") or "UNCLASSIFIED"
        by_head[head].append(txn)

    zscore_outlier_ids = set()
    for head, txns in by_head.items():
        if len(txns) < ANOMALY_MIN_GROUP_SIZE:
            continue  # not enough data points for a meaningful z-score
        amounts = np.array([t["amount"] for t in txns])
        mean, std = amounts.mean(), amounts.std()
        if std == 0:
            continue
        for t in txns:
            z = abs((t["amount"] - mean) / std)
            if z > ANOMALY_ZSCORE_THRESHOLD:
                zscore_outlier_ids.add(t["id"])

    # --- Rule 3: Absolute high-value flag, across the whole statement ---
    high_value_ids = {
        t["id"] for t in transactions if t["amount"] >= ANOMALY_HIGH_VALUE_THRESHOLD
    }

    # --- Combine, with duplicate > z-score > high-value in reporting priority ---
    results = []
    for txn in transactions:
        if txn["id"] in duplicate_ids:
            results.append({"transaction_id": txn["id"], "is_anomaly": True,
                             "reason": "Possible duplicate payment (same amount + description)"})
        elif txn["id"] in zscore_outlier_ids:
            results.append({"transaction_id": txn["id"], "is_anomaly": True,
                             "reason": "Unusually large/small amount vs similar transactions"})
        elif txn["id"] in high_value_ids:
            results.append({"transaction_id": txn["id"], "is_anomaly": True,
                             "reason": f"High-value transaction (>= {ANOMALY_HIGH_VALUE_THRESHOLD:,.0f}) — flagged for review regardless of category"})
        else:
            results.append({"transaction_id": txn["id"], "is_anomaly": False, "reason": None})

    return results
