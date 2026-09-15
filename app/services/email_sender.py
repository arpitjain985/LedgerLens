"""
Email sending, following the same zero-cost/local-first abstraction
pattern as the LLM provider and OCR engine elsewhere in this app
(Section 3): a real email provider is OPTIONAL, never mandatory to run.

Default ("console"): logs the link instead of sending a real email. This
is genuinely useful for local development/testing (you can complete the
reset/invite flow yourself by reading the link from the server log), but
is NOT sufficient for any real deployment with real users -- see the SMTP
path below for that, and PROGRESS.md for what's still needed to wire in a
real provider (e.g. SendGrid, AWS SES, Postmark) if SMTP isn't your
preference.
"""
import logging
import smtplib
from email.mime.text import MIMEText

from app.config import (
    EMAIL_PROVIDER, SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
    SMTP_FROM_ADDRESS, FRONTEND_BASE_URL,
)

logger = logging.getLogger(__name__)


def send_password_reset_email(to_email: str, raw_token: str) -> None:
    # NOTE: streamlit_app.py is a single-page app (sidebar nav, not real
    # multi-page routing) -- there is no /reset-password sub-path. The link
    # must point at the root URL with a query parameter the app reads via
    # st.query_params to show the right form. A previous version of this
    # link pointed at a path that genuinely didn't exist -- fixed here.
    link = f"{FRONTEND_BASE_URL}/?reset_token={raw_token}"
    body = (
        f"Someone requested a password reset for your LedgerLens account.\n\n"
        f"Reset your password here: {link}\n\n"
        f"If you didn't request this, you can safely ignore this email."
    )
    _send(to_email, "Reset your LedgerLens password", body, link, log_label="Password reset link")


def send_invite_email(to_email: str, raw_token: str, firm_name: str, role: str) -> None:
    # Same fix as above -- root URL + query param, not a nonexistent path.
    link = f"{FRONTEND_BASE_URL}/?invite_token={raw_token}"
    body = (
        f"You've been invited to join {firm_name} on LedgerLens as a {role}.\n\n"
        f"Accept your invite here: {link}\n\n"
        f"This invite will expire -- if it's no longer valid, ask whoever invited you to send a new one."
    )
    _send(to_email, f"You're invited to join {firm_name} on LedgerLens", body, link, log_label="Invite link")


def _send(to_email: str, subject: str, body: str, link: str, log_label: str) -> None:
    if EMAIL_PROVIDER == "smtp":
        _send_via_smtp(to_email, subject, body)
    else:
        _send_via_console(to_email, link, log_label)


def _send_via_console(to_email: str, link: str, log_label: str) -> None:
    logger.warning(
        "EMAIL_PROVIDER=console (dev mode, no real email sent). "
        "%s for %s: %s",
        log_label, to_email, link,
    )


def _send_via_smtp(to_email: str, subject: str, body: str) -> None:
    if not SMTP_HOST or not SMTP_USERNAME or not SMTP_PASSWORD:
        logger.error(
            "EMAIL_PROVIDER=smtp but SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD "
            "are not fully configured -- falling back to console logging "
            "so the flow doesn't silently fail."
        )
        _send_via_console(to_email, "(see body)", subject)
        return

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = SMTP_FROM_ADDRESS
    message["To"] = to_email

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_ADDRESS, [to_email], message.as_string())
    except Exception as e:
        # Never let an email-sending failure surface as a 500 to the user --
        # both /forgot-password and /users/invite already return a
        # generic success message regardless, so this failure is logged
        # for operator visibility, not raised to the caller.
        logger.error("Failed to send email via SMTP: %s", e)
