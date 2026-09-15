import uuid
from datetime import datetime

from sqlalchemy import Column, String, Float, DateTime, ForeignKey, Boolean, Text, Integer, Index
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Firm(Base):
    """A CA firm / client account. Section 19: a firm can have multiple
    Users with different roles (Section 20 RBAC)."""
    __tablename__ = "firms"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    statements = relationship("Statement", back_populates="firm")
    users = relationship("User", back_populates="firm")


class User(Base):
    """
    A user account (Section 20). Belongs to exactly one Firm for now —
    Section 19's "Firm -> Clients" hierarchy where one CA firm serves many
    client companies is a natural next step on top of this, not built yet
    (see PROGRESS.md). Passwords are stored as bcrypt hashes only, never
    plaintext (see services/auth.py for hashing/verification).
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    firm_id = Column(String, ForeignKey("firms.id"), nullable=False, index=True)
    email = Column(String, nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)

    # Section 20 roles: SUPER_ADMIN | CA_AUDITOR | ACCOUNTANT | REVIEWER | VIEWER
    role = Column(String, nullable=False, default="ACCOUNTANT")

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    firm = relationship("Firm", back_populates="users")


class Statement(Base):
    """One uploaded bank statement (a batch of transactions)."""
    __tablename__ = "statements"

    id = Column(String, primary_key=True, default=gen_uuid)
    firm_id = Column(String, ForeignKey("firms.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    bank_name = Column(String, nullable=True)  # populated from bank_detector's bank_code
    used_ocr = Column(Boolean, default=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="uploaded")  # uploaded -> parsed -> classified -> reconciled

    firm = relationship("Firm", back_populates="statements")
    transactions = relationship("Transaction", back_populates="statement")


class Transaction(Base):
    """A single classified transaction line from a statement."""
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=gen_uuid)
    statement_id = Column(String, ForeignKey("statements.id"), nullable=False, index=True)

    txn_date = Column(String, nullable=True)
    description = Column(Text, nullable=False)
    amount = Column(Float, nullable=False)
    txn_type = Column(String, nullable=True)  # "debit" | "credit"

    # Normalized-schema fields added in V2 (Section 5) — nullable so existing
    # rows/parsers that don't populate them yet don't break.
    debit = Column(Float, nullable=True)
    credit = Column(Float, nullable=True)
    balance = Column(Float, nullable=True)
    reference_number = Column(String, nullable=True)
    payment_mode = Column(String, nullable=True)  # UPI | NEFT | IMPS | CHEQUE | ATM | CASH | CARD
    vendor = Column(String, nullable=True)

    predicted_ledger_head = Column(String, nullable=True, index=True)
    confidence = Column(Float, nullable=True)
    classification_method = Column(String, nullable=True)  # "embedding" | "llm_fallback" | "manual" | "correction_memory"
    classification_reason = Column(Text, nullable=True)  # V2 Section 7 -- human-readable "why"

    is_anomaly = Column(Boolean, default=False, index=True)
    anomaly_reason = Column(String, nullable=True)

    # V2 Section 10 -- numeric risk scoring alongside the boolean anomaly flag.
    # is_anomaly/anomaly_reason stay as-is for backward compat with V1 exports;
    # risk_score/risk_level are the richer V2 view of the same underlying signals.
    risk_score = Column(Integer, nullable=True, index=True)   # 0-100
    risk_level = Column(String, nullable=True)                # Low | Medium | High | Critical
    risk_reasons = Column(Text, nullable=True)                # JSON list of contributing reasons

    reconciled = Column(Boolean, default=False)
    matched_invoice_ref = Column(String, nullable=True)

    # CA correction — this is the proprietary data flywheel mentioned in the report.
    corrected_ledger_head = Column(String, nullable=True)

    statement = relationship("Statement", back_populates="transactions")


class Correction(Base):
    """
    Records every human correction to a predicted ledger head, keyed by a
    normalized version of the transaction description. This is the actual
    data flywheel (Section 8): classify_transaction() checks this table
    BEFORE running the embedding model, so once a CA corrects "PAYMENT TO
    RAJ ELECTRICALS" to VENDOR_PAYMENT once, every future transaction with a
    matching description is classified correctly and instantly — no model
    call needed, and the correction is never silently overwritten.
    """
    __tablename__ = "corrections"

    id = Column(String, primary_key=True, default=gen_uuid)
    firm_id = Column(String, ForeignKey("firms.id"), nullable=False, index=True)
    normalized_description = Column(String, nullable=False, index=True)
    corrected_ledger_head = Column(String, nullable=False)
    original_description = Column(Text, nullable=True)  # kept for audit/debugging, not matched on
    created_at = Column(DateTime, default=datetime.utcnow)


class Vendor(Base):
    """
    Aggregated vendor profile (Section 25), built/updated from transaction
    data rather than entered manually. One row per (firm, normalized vendor
    name). Rebuilt/updated by services/vendor_intelligence.py.
    """
    __tablename__ = "vendors"

    id = Column(String, primary_key=True, default=gen_uuid)
    firm_id = Column(String, ForeignKey("firms.id"), nullable=False, index=True)
    normalized_name = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=False)

    total_payments = Column(Float, default=0)
    transaction_count = Column(Integer, default=0)
    average_payment = Column(Float, default=0)
    highest_payment = Column(Float, default=0)
    lowest_payment = Column(Float, default=0)
    first_payment_date = Column(String, nullable=True)
    last_payment_date = Column(String, nullable=True)

    is_new_vendor = Column(Boolean, default=True)  # only 1 transaction seen so far
    risk_score = Column(Integer, default=0)        # 0-100, see vendor_intelligence.py
    risk_reasons = Column(Text, nullable=True)      # JSON list

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Invoice(Base):
    """
    An uploaded invoice/receipt/bill (Section 6), separate from bank
    statement transactions. Extracted fields include GST breakdown
    (Section 11) where present on the document.
    """
    __tablename__ = "invoices"

    id = Column(String, primary_key=True, default=gen_uuid)
    firm_id = Column(String, ForeignKey("firms.id"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    document_type = Column(String, default="invoice")  # invoice | receipt | credit_note | debit_note | purchase_order
    used_ocr = Column(Boolean, default=False)

    vendor_name = Column(String, nullable=True)
    customer_name = Column(String, nullable=True)
    invoice_number = Column(String, nullable=True, index=True)
    invoice_date = Column(String, nullable=True)
    due_date = Column(String, nullable=True)

    gstin_vendor = Column(String, nullable=True)
    gstin_customer = Column(String, nullable=True)
    taxable_amount = Column(Float, nullable=True)
    cgst = Column(Float, nullable=True)
    sgst = Column(Float, nullable=True)
    igst = Column(Float, nullable=True)
    total_amount = Column(Float, nullable=True)

    extraction_confidence = Column(Float, nullable=True)  # 0-1, see invoice_extraction.py
    raw_text = Column(Text, nullable=True)  # kept for debugging/re-extraction, not shown by default

    uploaded_at = Column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    """
    Audit trail (Section 18) — records important financial-data changes with
    full before/after context. No important change should happen without
    traceability, per the spec: this is written to on classification,
    correction, and reconciliation, not just on manual edits.
    """
    __tablename__ = "audit_log"

    id = Column(String, primary_key=True, default=gen_uuid)
    firm_id = Column(String, ForeignKey("firms.id"), nullable=False, index=True)
    entity_type = Column(String, nullable=False)  # "transaction" | "invoice" | "statement"
    entity_id = Column(String, nullable=False, index=True)

    action = Column(String, nullable=False)  # "classified" | "corrected" | "reconciled" | "created"
    field_changed = Column(String, nullable=True)
    previous_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    changed_by = Column(String, default="system")  # "system" for AI actions, or a user identifier

    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class PasswordResetToken(Base):
    """
    A single-use, expiring password reset token. Stores only a hash of the
    token (same principle as passwords -- if the DB leaks, tokens aren't
    directly usable), keyed by that hash for lookup. The raw token is only
    ever held in memory long enough to email it to the user.
    """
    __tablename__ = "password_reset_tokens"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)


class Invite(Base):
    """
    A pending invitation for someone to join an existing firm as a User
    with a specific role (Section 19/20). Unlike PasswordResetToken, this
    isn't tied to an existing User row -- the User doesn't exist yet until
    the invite is accepted, since the invitee hasn't chosen a password yet.
    Same hashed-token-for-lookup principle as password resets.
    """
    __tablename__ = "invites"

    id = Column(String, primary_key=True, default=gen_uuid)
    firm_id = Column(String, ForeignKey("firms.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)
    invited_by_user_id = Column(String, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, nullable=False, unique=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    accepted = Column(Boolean, default=False)
    accepted_at = Column(DateTime, nullable=True)


class Job(Base):
    """
    Background processing job (Section 4). Created immediately when a
    statement is uploaded; the actual parsing/OCR/classification work happens
    in a background task while the client polls GET /jobs/{id} for progress
    instead of blocking on the original request.

    NOTE on architecture (documented honestly in PROGRESS.md): this uses
    FastAPI's built-in BackgroundTasks + this DB table for status/progress,
    NOT a full Celery/Redis task queue. That's a deliberate zero-cost,
    local-first tradeoff per Section 3 — it gives non-blocking uploads and
    real progress tracking without adding infrastructure a student project
    doesn't need yet. If this needs to scale to many concurrent large files,
    swapping in Celery is the documented upgrade path (same Job table would
    work as the status store either way).
    """
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    job_type = Column(String, nullable=False)  # "statement_upload"
    statement_id = Column(String, ForeignKey("statements.id"), nullable=True, index=True)

    status = Column(String, default="queued")  # queued -> processing -> completed -> failed
    progress_percent = Column(Integer, default=0)
    progress_message = Column(String, nullable=True)

    error_message = Column(String, nullable=True)  # user-friendly message, per Section 23
    error_detail = Column(Text, nullable=True)      # technical detail, for logs only

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
