from typing import Optional, List
from pydantic import BaseModel


class TransactionOut(BaseModel):
    id: str
    txn_date: Optional[str]
    description: str
    amount: float
    txn_type: Optional[str]
    debit: Optional[float] = None
    credit: Optional[float] = None
    balance: Optional[float] = None
    reference_number: Optional[str] = None
    payment_mode: Optional[str] = None
    vendor: Optional[str] = None
    predicted_ledger_head: Optional[str]
    confidence: Optional[float]
    classification_method: Optional[str]
    classification_reason: Optional[str] = None
    is_anomaly: bool
    anomaly_reason: Optional[str]
    risk_score: Optional[int] = None
    risk_level: Optional[str] = None
    risk_reasons: Optional[str] = None  # JSON-encoded list; caller decodes if needed
    reconciled: bool

    class Config:
        from_attributes = True


class StatementUploadResponse(BaseModel):
    statement_id: str          # empty string until the background job completes
    filename: str
    transactions_found: int    # 0 until the background job completes -- poll job_id
    status: str
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # queued | processing | completed | failed
    progress_percent: int
    progress_message: Optional[str]
    statement_id: Optional[str]
    error_message: Optional[str]


class ClassifyResponse(BaseModel):
    statement_id: str
    classified_count: int
    llm_fallback_count: int
    correction_memory_count: int = 0
    transactions: List[TransactionOut]


class VendorSummary(BaseModel):
    vendor_name: str
    total_payments: float
    transaction_count: int
    average_payment: float
    highest_payment: float
    lowest_payment: float
    first_payment_date: Optional[str]
    last_payment_date: Optional[str]
    is_new_vendor: bool
    risk_score: int


class RecurringTransaction(BaseModel):
    vendor_name: str
    occurrences: int
    average_amount: float
    average_interval_days: int
    frequency_label: str
    last_payment_date: str
    next_expected_date: str


class InvoiceUploadResponse(BaseModel):
    invoice_id: str
    filename: str
    vendor_name: Optional[str]
    customer_name: Optional[str]
    invoice_number: Optional[str]
    invoice_date: Optional[str]
    due_date: Optional[str]
    gstin_vendor: Optional[str]
    gstin_customer: Optional[str]
    taxable_amount: Optional[float]
    cgst: Optional[float]
    sgst: Optional[float]
    igst: Optional[float]
    total_amount: Optional[float]
    extraction_confidence: float
    used_ocr: bool


class GSTSummary(BaseModel):
    invoice_count: int
    total_taxable_value: float
    total_cgst: float
    total_sgst: float
    total_igst: float
    total_gst: float
    total_invoice_value: float
    potential_input_tax_credit: float
    low_confidence_invoice_count: int
    disclaimer: str


class AuditLogEntry(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    action: str
    field_changed: Optional[str]
    previous_value: Optional[str]
    new_value: Optional[str]
    reason: Optional[str]
    changed_by: str
    created_at: Optional[str]


class ExpenseCategory(BaseModel):
    category: str
    amount: float


class DashboardSummary(BaseModel):
    transaction_count: int
    total_credits: float
    total_debits: float
    net_cash_flow: float
    reconciled_count: int
    unmatched_count: int
    suspicious_count: int
    expense_by_category: List[ExpenseCategory]


class ReconcileRequest(BaseModel):
    statement_id: str
    invoice_lines: List[dict]  # [{"ref": "INV-001", "amount": 4500.0, "vendor": "Acme Traders"}, ...]


class TransactionCorrection(BaseModel):
    transaction_id: str
    corrected_ledger_head: str
