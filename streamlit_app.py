"""
LedgerLens - Streamlit V2 frontend, full multi-page version.

Run the FastAPI backend first (uvicorn app.main:app --reload), then run this
with: streamlit run streamlit_app.py

This exposes every backend feature built across Phases 1-5 via a sidebar
navigation: Statements (upload/classify/correct/export), Dashboard,
Vendors, GST & Invoices, Recurring Payments, Ask LedgerLens, and Audit Log.
Previously only the Statements flow was wired up here -- everything else
existed and worked at the API level but had no UI at all.
"""
import json
import time

import pandas as pd
import requests
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(page_title="LedgerLens", page_icon="\U0001F4D2", layout="wide")

# --- Health check banner ---
try:
    health = requests.get(f"{API_BASE}/health", timeout=3).json()
    if health["overall_status"] != "ok":
        with st.expander("\u26A0\uFE0F Some backend subsystems need attention", expanded=False):
            for name, check in health["checks"].items():
                icon = {"ok": "\u2705", "optional": "\u2139\uFE0F", "error": "\u274C"}.get(check["status"], "?")
                st.write(f"{icon} **{name}**: {check['detail']}")
except requests.exceptions.RequestException:
    st.error("Can't reach the LedgerLens backend. Make sure `uvicorn app.main:app --reload` is running.")
    st.stop()

# --- Session state defaults ---
for key, default in [
    ("access_token", None), ("firm_id", None), ("user_email", None),
    ("statement_id", None), ("transactions", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {st.session_state.access_token}"}


def api_get(path: str, **kwargs):
    return requests.get(f"{API_BASE}{path}", headers=auth_headers(), **kwargs)


def api_post(path: str, **kwargs):
    return requests.post(f"{API_BASE}{path}", headers=auth_headers(), **kwargs)


# ============================================================
# Invite-accept / password-reset flows, reached via a query-param link in
# an email (e.g. http://localhost:8501/?reset_token=...). This app is a
# single-page Streamlit app (sidebar nav, not real multi-page routing), so
# these are NOT separate pages/URLs -- they're detected via st.query_params
# and rendered instead of the normal login gate while the token is present.
# A previous version of this pointed the email links at paths like
# /accept-invite and /reset-password that simply didn't exist -- fixed here
# by having the email links carry a query param on the root URL instead.
# ============================================================
query_params = st.query_params
invite_token = query_params.get("invite_token")
reset_token = query_params.get("reset_token")

if invite_token:
    st.title("\U0001F4D2 LedgerLens")
    st.subheader("Accept your invite")
    with st.form("accept_invite_form"):
        full_name = st.text_input("Your name")
        new_password = st.text_input("Choose a password", type="password")
        accept_submitted = st.form_submit_button("Accept invite & create account")
    if accept_submitted:
        resp = requests.post(f"{API_BASE}/auth/accept-invite", json={
            "token": invite_token, "password": new_password, "full_name": full_name,
        })
        if resp.ok:
            data = resp.json()
            st.session_state.access_token = data["access_token"]
            st.session_state.firm_id = data["firm_id"]
            st.session_state.user_email = full_name or "you"
            st.query_params.clear()
            st.success("Invite accepted — you're logged in.")
            st.rerun()
        else:
            st.error(resp.json().get("error", "Could not accept this invite."))
    st.stop()

if reset_token:
    st.title("\U0001F4D2 LedgerLens")
    st.subheader("Set a new password")
    with st.form("reset_password_form"):
        new_password = st.text_input("New password", type="password")
        confirm_password = st.text_input("Confirm new password", type="password")
        reset_submitted = st.form_submit_button("Reset password")
    if reset_submitted:
        if new_password != confirm_password:
            st.error("Passwords don't match.")
        else:
            resp = requests.post(f"{API_BASE}/auth/reset-password", json={
                "token": reset_token, "new_password": new_password,
            })
            if resp.ok:
                st.query_params.clear()
                st.success("Password reset. Refresh this page and log in with your new password.")
            else:
                st.error(resp.json().get("error", "Could not reset your password."))
    st.stop()

# ============================================================
# Login / Register / Forgot password gate -- nothing below this runs
# until authenticated
# ============================================================
if not st.session_state.access_token:
    st.title("\U0001F4D2 LedgerLens")
    st.caption("Log in or create an account to continue.")
    login_tab, register_tab, forgot_tab = st.tabs(["Log in", "Create account", "Forgot password?"])

    with login_tab:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in")
        if submitted:
            resp = requests.post(f"{API_BASE}/auth/login", json={"email": email, "password": password})
            if resp.ok:
                data = resp.json()
                st.session_state.access_token = data["access_token"]
                st.session_state.firm_id = data["firm_id"]
                st.session_state.user_email = email
                st.rerun()
            else:
                st.error(resp.json().get("error", "Login failed."))

    with register_tab:
        with st.form("register_form"):
            reg_email = st.text_input("Email", key="reg_email")
            reg_password = st.text_input("Password", type="password", key="reg_password")
            reg_firm_name = st.text_input("Firm / business name")
            reg_submitted = st.form_submit_button("Create account")
        if reg_submitted:
            resp = requests.post(f"{API_BASE}/auth/register", json={
                "email": reg_email, "password": reg_password, "firm_name": reg_firm_name,
            })
            if resp.ok:
                data = resp.json()
                st.session_state.access_token = data["access_token"]
                st.session_state.firm_id = data["firm_id"]
                st.session_state.user_email = reg_email
                st.success("Account created — you're logged in.")
                st.rerun()
            else:
                st.error(resp.json().get("error", "Registration failed."))

    with forgot_tab:
        st.caption(
            "Enter your email and we'll send a reset link. By default (dev mode) "
            "the link is logged to the backend server's console instead of actually "
            "emailed — check the terminal running `uvicorn` for it."
        )
        with st.form("forgot_password_form"):
            forgot_email = st.text_input("Email", key="forgot_email")
            forgot_submitted = st.form_submit_button("Send reset link")
        if forgot_submitted:
            resp = requests.post(f"{API_BASE}/auth/forgot-password", json={"email": forgot_email})
            if resp.ok:
                st.success(resp.json().get("message", "If an account exists for that email, a reset link has been sent."))
            else:
                st.error(resp.json().get("error", "Something went wrong."))

    st.stop()

# ============================================================
# Logged in: sidebar navigation
# ============================================================
with st.sidebar:
    st.write(f"Logged in as **{st.session_state.user_email}**")
    if st.button("Log out"):
        for key in ("access_token", "firm_id", "user_email", "statement_id", "transactions"):
            st.session_state[key] = None
        st.rerun()
    st.divider()
    page = st.radio("Navigate", [
        "\U0001F4C4 Statements", "\U0001F4CA Dashboard", "\U0001F3E2 Vendors",
        "\U0001F9FE GST & Invoices", "\U0001F501 Recurring Payments",
        "\U0001F4AC Ask LedgerLens", "\U0001F4CB Audit Log", "\U0001F465 Team",
    ])

st.title("\U0001F4D2 LedgerLens")

# ============================================================
# PAGE: Statements (upload, classify, correct, export)
# ============================================================
if page.endswith("Statements"):
    st.caption("Upload a bank statement -> get a classified, reconciled, CA-ready workpaper.")

    st.header("1. Upload bank statement")
    uploaded_file = st.file_uploader("PDF bank statement", type=["pdf"])

    if uploaded_file and st.button("Upload & Parse"):
        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
        resp = api_post("/statements/upload", files=files)

        if resp.status_code == 401:
            st.error("Your session has expired. Please log out and log back in.")
        elif not resp.ok:
            st.error(f"Upload failed: {resp.json().get('error', resp.text)}")
        else:
            job_id = resp.json()["job_id"]
            progress_bar = st.progress(0, text="Queued...")
            for _ in range(120):
                job = requests.get(f"{API_BASE}/jobs/{job_id}").json()
                progress_bar.progress(job["progress_percent"] / 100, text=job.get("progress_message") or job["status"])
                if job["status"] == "completed":
                    st.session_state.statement_id = job["statement_id"]
                    st.session_state.transactions = None  # reset review table for the new statement
                    st.success("Statement parsed successfully.")
                    break
                elif job["status"] == "failed":
                    st.error(f"Processing failed: {job.get('error_message', 'Unknown error')}")
                    break
                time.sleep(0.5)
            else:
                st.warning("Still processing -- this is taking longer than expected. Try refreshing in a moment.")

    if st.session_state.statement_id:
        st.header("2. Classify transactions")
        if st.button("Run classification"):
            with st.spinner("Classifying (embeddings, with LLM fallback for ambiguous cases)..."):
                resp = api_post(f"/statements/{st.session_state.statement_id}/classify")
            if resp.ok:
                data = resp.json()
                st.session_state.transactions = data["transactions"]
                st.success(
                    f"Classified {data['classified_count']} transactions "
                    f"({data['llm_fallback_count']} needed LLM fallback, "
                    f"{data.get('correction_memory_count', 0)} from correction memory)."
                )
            else:
                st.error(f"Classification failed: {resp.json().get('error', resp.text)}")

    if st.session_state.transactions:
        st.header("3. Review results")
        df = pd.DataFrame(st.session_state.transactions)

        def highlight_anomaly(row):
            return ["background-color: #ffc7ce" if row["is_anomaly"] else "" for _ in row]

        display_cols = [
            "txn_date", "description", "amount", "txn_type", "payment_mode", "vendor",
            "predicted_ledger_head", "confidence", "classification_method",
            "is_anomaly", "anomaly_reason", "risk_level",
        ]
        display_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(df[display_cols].style.apply(highlight_anomaly, axis=1), use_container_width=True)

        anomaly_count = int(df["is_anomaly"].sum())
        if anomaly_count:
            st.warning(f"\u26A0\uFE0F {anomaly_count} transaction(s) flagged for review.")

        # --- Correction UI -- this previously had NO UI at all despite the
        # backend correction flywheel (Section 8) being fully built and tested.
        st.subheader("Correct a prediction")
        st.caption("Corrections are remembered — future similarly-worded transactions from the same vendor will be classified automatically.")
        ledger_heads_resp = requests.get(f"{API_BASE}/ledger-heads")
        ledger_head_options = {h["label"]: h["code"] for h in ledger_heads_resp.json()} if ledger_heads_resp.ok else {}

        txn_options = {f"{t['description'][:60]} (Rs {t['amount']:,.2f})": t["id"] for t in st.session_state.transactions}
        col1, col2, col3 = st.columns([3, 2, 1])
        with col1:
            selected_txn_label = st.selectbox("Transaction", list(txn_options.keys()))
        with col2:
            selected_head_label = st.selectbox("Correct ledger head", list(ledger_head_options.keys()))
        with col3:
            st.write("")
            st.write("")
            if st.button("Submit correction"):
                txn_id = txn_options[selected_txn_label]
                head_code = ledger_head_options[selected_head_label]
                resp = api_post(
                    f"/statements/{st.session_state.statement_id}/correct",
                    json={"transaction_id": txn_id, "corrected_ledger_head": head_code},
                )
                if resp.ok:
                    st.success("Correction saved. Re-run classification to see it applied.")
                else:
                    st.error(resp.json().get("error", "Correction failed."))

        st.header("4. Export workpaper")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Generate Excel workpaper (this statement)"):
                resp = api_get(f"/statements/{st.session_state.statement_id}/export")
                if resp.status_code == 401:
                    st.error("Your session has expired. Please log out and log back in.")
                elif resp.ok:
                    st.download_button(
                        "\u2B07\uFE0F Download Workpaper.xlsx", data=resp.content,
                        file_name="LedgerLens_Workpaper.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                else:
                    st.error(f"Export failed: {resp.text}")
        with col2:
            if st.button("Generate full CA workpaper package (all statements, ZIP)"):
                resp = api_get("/statements/workpaper-package/full")
                if resp.status_code == 403:
                    st.error("Your role doesn't have permission for this (requires CA_AUDITOR or higher).")
                elif resp.ok:
                    st.download_button(
                        "\u2B07\uFE0F Download Workpaper_Package.zip", data=resp.content,
                        file_name="LedgerLens_Workpaper_Package.zip", mime="application/zip",
                    )
                else:
                    st.error(f"Export failed: {resp.text}")

# ============================================================
# PAGE: Dashboard
# ============================================================
elif page.endswith("Dashboard"):
    resp = api_get("/dashboard")
    if not resp.ok:
        st.error(resp.json().get("error", "Could not load dashboard."))
    else:
        d = resp.json()
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Credits", f"Rs {d['total_credits']:,.2f}")
        col2.metric("Total Debits", f"Rs {d['total_debits']:,.2f}")
        col3.metric("Net Cash Flow", f"Rs {d['net_cash_flow']:,.2f}")

        col4, col5, col6 = st.columns(3)
        col4.metric("Transactions", d["transaction_count"])
        col5.metric("Reconciled", d["reconciled_count"])
        col6.metric("Unmatched", d["unmatched_count"])

        if d["suspicious_count"]:
            st.warning(f"\u26A0\uFE0F {d['suspicious_count']} transaction(s) flagged High/Critical risk.")

        if d["expense_by_category"]:
            st.subheader("Expenses by category")
            cat_df = pd.DataFrame(d["expense_by_category"])
            st.bar_chart(cat_df.set_index("category"))
        else:
            st.info("No categorized expenses yet — upload and classify a statement first.")

# ============================================================
# PAGE: Vendors
# ============================================================
elif page.endswith("Vendors"):
    resp = api_get("/vendors")
    if not resp.ok:
        st.error(resp.json().get("error", "Could not load vendors."))
    else:
        vendors = resp.json()
        if not vendors:
            st.info("No vendor data yet — upload and classify a statement first.")
        else:
            df = pd.DataFrame(vendors)
            st.dataframe(df, use_container_width=True)

# ============================================================
# PAGE: GST & Invoices
# ============================================================
elif page.endswith("GST & Invoices"):
    st.header("Upload an invoice or receipt")
    invoice_file = st.file_uploader("PDF invoice/receipt", type=["pdf"], key="invoice_uploader")
    if invoice_file and st.button("Upload & Extract"):
        files = {"file": (invoice_file.name, invoice_file.getvalue(), "application/pdf")}
        resp = api_post("/invoices/upload", files=files)
        if resp.ok:
            data = resp.json()
            st.success(f"Extracted with {data['extraction_confidence']*100:.0f}% field confidence.")
            st.json(data)
        else:
            st.error(resp.json().get("error", "Invoice upload failed."))

    st.header("GST Summary")
    resp = api_get("/gst-summary")
    if resp.ok:
        s = resp.json()
        col1, col2, col3 = st.columns(3)
        col1.metric("Invoices", s["invoice_count"])
        col2.metric("Total GST", f"Rs {s['total_gst']:,.2f}")
        col3.metric("Total Invoice Value", f"Rs {s['total_invoice_value']:,.2f}")
        st.caption(s["disclaimer"])
    else:
        st.error(resp.json().get("error", "Could not load GST summary."))

    st.header("All Invoices")
    inv_resp = api_get("/invoices")
    if inv_resp.ok:
        invoices = inv_resp.json()
        if invoices:
            st.dataframe(pd.DataFrame(invoices), use_container_width=True)
        else:
            st.info("No invoices uploaded yet.")

# ============================================================
# PAGE: Recurring Payments
# ============================================================
elif page.endswith("Recurring Payments"):
    resp = api_get("/recurring-transactions")
    if not resp.ok:
        st.error(resp.json().get("error", "Could not load recurring transactions."))
    else:
        recurring = resp.json()
        if not recurring:
            st.info("No recurring patterns detected yet — this needs at least 2 similar payments to the same vendor across your uploaded statements.")
        else:
            st.dataframe(pd.DataFrame(recurring), use_container_width=True)

# ============================================================
# PAGE: Ask LedgerLens
# ============================================================
elif page.endswith("Ask LedgerLens"):
    st.caption(
        "Ask questions about your data. Every number in the answer comes directly "
        "from your actual records — never guessed or invented."
    )
    ask_tab, search_tab = st.tabs(["Ask a question", "Search transactions"])

    with ask_tab:
        question = st.text_input(
            "Your question",
            placeholder="e.g. How much GST did we pay? / Which vendor received the most money?",
        )
        if st.button("Ask") and question:
            resp = api_post("/ai/ask", json={"question": question})
            if resp.ok:
                data = resp.json()
                st.write(data["answer"])
                if data.get("data"):
                    with st.expander("Underlying data"):
                        st.json(data["data"])
            else:
                st.error(resp.json().get("error", "Question failed."))

    with search_tab:
        query = st.text_input(
            "Search query",
            placeholder="e.g. Show payments above Rs 1 lakh to new vendors",
        )
        if st.button("Search") and query:
            resp = api_post("/ai/search", json={"query": query})
            if resp.ok:
                data = resp.json()
                st.caption(f"Filters applied: {', '.join(data['filters_applied']) or 'none'} — {data['result_count']} result(s)")
                if data["transactions"]:
                    st.dataframe(pd.DataFrame(data["transactions"]), use_container_width=True)
            else:
                st.error(resp.json().get("error", "Search failed."))

# ============================================================
# PAGE: Audit Log
# ============================================================
elif page.endswith("Audit Log"):
    resp = api_get("/audit-log")
    if not resp.ok:
        st.error(resp.json().get("error", "Could not load audit log."))
    else:
        entries = resp.json()
        if not entries:
            st.info("No audit entries yet — corrections and invoice uploads are logged here.")
        else:
            st.dataframe(pd.DataFrame(entries), use_container_width=True)

# ============================================================
# PAGE: Team
# ============================================================
elif page.endswith("Team"):
    st.header("Team members")
    resp = api_get("/users")
    if resp.ok:
        st.dataframe(pd.DataFrame(resp.json()), use_container_width=True)
    else:
        st.error(resp.json().get("error", "Could not load team members."))

    st.header("Invite a teammate")
    st.caption("Requires CA Auditor role or higher. You also can't invite someone to a role more privileged than your own.")
    with st.form("invite_form"):
        invite_email = st.text_input("Email")
        invite_role = st.selectbox("Role", ["VIEWER", "REVIEWER", "ACCOUNTANT", "CA_AUDITOR", "SUPER_ADMIN"])
        invite_submitted = st.form_submit_button("Send invite")
    if invite_submitted:
        resp = api_post("/users/invite", json={"email": invite_email, "role": invite_role})
        if resp.ok:
            st.success(resp.json()["message"])
        else:
            st.error(resp.json().get("error", "Invite failed."))

    st.header("Pending invites")
    pending_resp = api_get("/users/invites/pending")
    if pending_resp.ok:
        pending = pending_resp.json()
        if pending:
            st.dataframe(pd.DataFrame(pending), use_container_width=True)
        else:
            st.info("No pending invites.")
    else:
        st.caption("(Pending invites view requires CA Auditor role or higher.)")
