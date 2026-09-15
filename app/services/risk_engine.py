"""
Financial risk scoring engine (Section 10). Produces a 0-100 score and a
Low/Medium/High/Critical level per transaction, with explainable reasons —
richer than the boolean is_anomaly flag from Phase 1, built from the same
underlying signals plus two new ones (round-number amounts, weekend timing).

Score bands (as specified): 0-30 Low, 31-60 Medium, 61-80 High, 81-100 Critical.

Design note: this does NOT replace app/services/anomaly.py's flag_anomalies()
— that function still drives the is_anomaly/anomaly_reason boolean fields
used by the V1 Excel export and is independently tested. This module adds
the richer numeric view on top, reusing the same duplicate/z-score/high-value
detection so the two never disagree about what counts as unusual.
"""
from collections import defaultdict
from datetime import datetime
from typing import List, Dict

import numpy as np

from app.config import (
    ANOMALY_ZSCORE_THRESHOLD,
    ANOMALY_MIN_GROUP_SIZE,
    ANOMALY_HIGH_VALUE_THRESHOLD,
)

# Points contributed by each risk factor. Additive, capped at 100.
POINTS_DUPLICATE = 40
POINTS_ZSCORE_OUTLIER = 25
POINTS_HIGH_VALUE = 35
POINTS_ROUND_NUMBER = 10
POINTS_WEEKEND = 8
POINTS_NEW_VENDOR = 15

ROUND_NUMBER_THRESHOLD = 10000  # only flag round numbers above this size -- a Rs 100 round payment is unremarkable


def compute_risk(transactions: List[Dict], vendor_first_seen: Dict[str, bool] = None) -> List[Dict]:
    """
    transactions: [{"id", "description", "amount", "predicted_ledger_head",
                     "txn_date", "vendor"}, ...]
    vendor_first_seen: optional {vendor_normalized_name: is_new_vendor} map,
                        supplied by vendor_intelligence.py when available.
                        If not supplied, the new-vendor risk factor is skipped.

    Returns: [{"transaction_id", "risk_score", "risk_level", "risk_reasons": [...]}, ...]
    """
    vendor_first_seen = vendor_first_seen or {}

    duplicate_ids = _find_duplicates(transactions)
    zscore_ids = _find_zscore_outliers(transactions)

    results = []
    for txn in transactions:
        score = 0
        reasons = []

        if txn["id"] in duplicate_ids:
            score += POINTS_DUPLICATE
            reasons.append("Possible duplicate payment (same amount + description as another transaction)")

        if txn["id"] in zscore_ids:
            score += POINTS_ZSCORE_OUTLIER
            reasons.append("Amount is a statistical outlier compared to similar transactions")

        if txn["amount"] >= ANOMALY_HIGH_VALUE_THRESHOLD:
            score += POINTS_HIGH_VALUE
            reasons.append(f"High-value transaction (>= {ANOMALY_HIGH_VALUE_THRESHOLD:,.0f})")

        if _is_round_number(txn["amount"]):
            score += POINTS_ROUND_NUMBER
            reasons.append("Round-number amount, which can indicate a manually entered or estimated figure")

        if _is_weekend(txn.get("txn_date")):
            score += POINTS_WEEKEND
            reasons.append("Transaction dated on a weekend, unusual for routine business payments")

        vendor_key = (txn.get("vendor") or "").strip().lower()
        if vendor_key and vendor_first_seen.get(vendor_key) is True:
            score += POINTS_NEW_VENDOR
            reasons.append("Payment to a vendor not seen in prior transactions")

        score = min(score, 100)
        results.append({
            "transaction_id": txn["id"],
            "risk_score": score,
            "risk_level": _score_to_level(score),
            "risk_reasons": reasons,
        })

    return results


def _score_to_level(score: int) -> str:
    if score <= 30:
        return "Low"
    if score <= 60:
        return "Medium"
    if score <= 80:
        return "High"
    return "Critical"


def _find_duplicates(transactions: List[Dict]) -> set:
    seen = defaultdict(list)
    for txn in transactions:
        key = (round(txn["amount"], 2), txn["description"].strip().lower())
        seen[key].append(txn["id"])
    duplicate_ids = set()
    for ids in seen.values():
        if len(ids) > 1:
            duplicate_ids.update(ids)
    return duplicate_ids


def _find_zscore_outliers(transactions: List[Dict]) -> set:
    by_head = defaultdict(list)
    for txn in transactions:
        head = txn.get("predicted_ledger_head") or "UNCLASSIFIED"
        by_head[head].append(txn)

    outlier_ids = set()
    for txns in by_head.values():
        if len(txns) < ANOMALY_MIN_GROUP_SIZE:
            continue
        amounts = np.array([t["amount"] for t in txns])
        mean, std = amounts.mean(), amounts.std()
        if std == 0:
            continue
        for t in txns:
            z = abs((t["amount"] - mean) / std)
            if z > ANOMALY_ZSCORE_THRESHOLD:
                outlier_ids.add(t["id"])
    return outlier_ids


def _is_round_number(amount: float) -> bool:
    return amount >= ROUND_NUMBER_THRESHOLD and amount % 1000 == 0


def _is_weekend(date_str: str) -> bool:
    if not date_str:
        return False
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.weekday() >= 5  # Saturday=5, Sunday=6
        except ValueError:
            continue
    return False  # unparseable date -- don't guess, just skip this factor
