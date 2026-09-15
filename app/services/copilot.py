"""
"Ask LedgerLens" natural-language financial copilot (Section 13).

Design principle, stated explicitly because it's the whole safety argument
for this feature: intent detection is rule-based (keyword matching, not an
LLM), and every number in every answer comes directly from a database
aggregation via the SAME services already built and tested elsewhere
(dashboard, vendor_intelligence, gst_summary, risk data on Transaction rows)
-- never from an LLM generating a figure. An LLM is used ONLY, optionally,
to smooth the final sentence -- and only ever rephrases numbers already
computed, never invents them. If no LLM is configured (or the call fails),
a plain templated sentence is returned instead -- the answer is always
correct, just less conversational. This satisfies Section 13's explicit
"never hallucinate financial values" and "if data is unavailable, say so"
requirements by construction, not by hoping the model behaves.
"""
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Transaction, Statement
from app.services.dashboard import get_dashboard
from app.services.vendor_intelligence import get_vendor_summary
from app.services.gst_summary import get_gst_summary

AMOUNT_THRESHOLD_PATTERN = re.compile(r"(?:above|over|more than|greater than)\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|crore|k)?", re.IGNORECASE)

MULTIPLIERS = {"k": 1_000, "lakh": 100_000, "crore": 10_000_000}


def answer_question(db: Session, firm_id: str, question: str) -> dict:
    intent, data = _detect_intent_and_fetch(db, firm_id, question)

    if intent == "unknown":
        return {
            "answer": (
                "I couldn't match that to something I can compute from your data yet. "
                "I can currently answer questions about: total spend on suppliers, "
                "suspicious/flagged transactions, which vendor received the most money, "
                "GST paid, unmatched invoices, and expense breakdown by category."
            ),
            "intent": "unknown",
            "data": None,
        }

    return {
        "answer": _phrase_answer(intent, data),
        "intent": intent,
        "data": data,
    }


def _detect_intent_and_fetch(db: Session, firm_id: str, question: str) -> tuple:
    q = question.lower()

    if any(kw in q for kw in ["suspicious", "flagged", "risky", "high risk"]):
        transactions = (
            db.query(Transaction)
            .join(Statement, Transaction.statement_id == Statement.id)
            .filter(Statement.firm_id == firm_id, Transaction.risk_level.in_(["High", "Critical"]))
            .all()
        )
        return "suspicious_transactions", {
            "count": len(transactions),
            "transactions": [_txn_summary(t) for t in transactions],
        }

    if any(kw in q for kw in ["vendor received the most", "top vendor", "biggest vendor", "which vendor"]):
        vendors = get_vendor_summary(db, firm_id)
        top = vendors[0] if vendors else None
        return "top_vendor", {"top_vendor": top}

    if ("supplier" in q or "vendor" in q) and ("spend" in q or "spent" in q):
        vendors = get_vendor_summary(db, firm_id)
        total = sum(v["total_payments"] for v in vendors)
        return "vendor_spend", {"total_spend": round(total, 2), "vendor_count": len(vendors)}

    if "gst" in q:
        summary = get_gst_summary(db, firm_id)
        return "gst_paid", summary

    if "unmatched" in q and "invoice" in q:
        dashboard = get_dashboard(db, firm_id)
        return "unmatched", {"unmatched_count": dashboard["unmatched_count"]}

    if any(kw in q for kw in ["expense", "spending by category", "where did the money go"]):
        dashboard = get_dashboard(db, firm_id)
        return "expenses_by_category", {"categories": dashboard["expense_by_category"]}

    if any(kw in q for kw in ["cash flow", "net position", "credits and debits"]):
        dashboard = get_dashboard(db, firm_id)
        return "cash_flow", dashboard

    return "unknown", None


def _txn_summary(t: Transaction) -> dict:
    return {
        "id": t.id, "date": t.txn_date, "description": t.description, "amount": t.amount,
        "risk_level": t.risk_level, "risk_reasons": t.risk_reasons,
    }


def _phrase_answer(intent: str, data: dict) -> str:
    if intent == "suspicious_transactions":
        if data["count"] == 0:
            return "No transactions are currently flagged as High or Critical risk."
        return f"{data['count']} transaction(s) are flagged as High or Critical risk. See the attached list for details."

    if intent == "top_vendor":
        v = data["top_vendor"]
        if not v:
            return "No vendor data is available yet -- upload and classify a statement first."
        return f"{v['vendor_name']} received the most money: Rs {v['total_payments']:,.2f} across {v['transaction_count']} transaction(s)."

    if intent == "vendor_spend":
        return f"Total spend across {data['vendor_count']} identified vendor(s) is Rs {data['total_spend']:,.2f}."

    if intent == "gst_paid":
        return f"Total GST across {data['invoice_count']} invoice(s) is Rs {data['total_gst']:,.2f} (CGST: Rs {data['total_cgst']:,.2f}, SGST: Rs {data['total_sgst']:,.2f}, IGST: Rs {data['total_igst']:,.2f}). {data['disclaimer']}"

    if intent == "unmatched":
        return f"{data['unmatched_count']} transaction(s) are not yet reconciled against an invoice."

    if intent == "expenses_by_category":
        if not data["categories"]:
            return "No categorized expenses are available yet."
        top = data["categories"][0]
        return f"Your largest expense category is {top['category']} at Rs {top['amount']:,.2f}. See the full breakdown for more."

    if intent == "cash_flow":
        return (
            f"Total credits: Rs {data['total_credits']:,.2f}, total debits: Rs {data['total_debits']:,.2f}, "
            f"net cash flow: Rs {data['net_cash_flow']:,.2f} across {data['transaction_count']} transaction(s)."
        )

    return "I have data but don't have a phrasing rule for this intent yet."
