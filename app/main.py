from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.database import Base, engine
from app.config import ALLOWED_ORIGINS
from app.exceptions import LedgerLensError
from app.services.rate_limit import limiter
from app.routers import upload, classify, reconcile, export, jobs, health, vendors, recurring, invoices, gst, audit, dashboard, ai_platform, auth, ledger_heads, users

# Creates tables on startup if they don't exist yet.
# Fine for MVP/SQLite; use Alembic migrations once you move to Postgres/Supabase (Phase 5).
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="LedgerLens API",
    description="Turns messy bank statements + invoices into CA-ready workpapers.",
    version="0.6.0",
)

app.state.limiter = limiter
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # Section 22: no longer "*" -- see config.py
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """
    Section 22: returns a clean 429 with a clear message instead of
    slowapi's default response shape, so it's consistent with every other
    error in this API (see ledgerlens_error_handler below).
    """
    return JSONResponse(
        status_code=429,
        content={"error": "Too many attempts. Please wait a moment and try again."},
    )


@app.exception_handler(LedgerLensError)
async def ledgerlens_error_handler(request: Request, exc: LedgerLensError):
    """
    Central handler for all custom exceptions (Section 23) -- every route
    that raises a LedgerLensError subclass gets a consistent, user-friendly
    response without needing its own try/except boilerplate.
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.user_message},
    )


app.include_router(upload.router)
app.include_router(classify.router)
app.include_router(reconcile.router)
app.include_router(export.router)
app.include_router(jobs.router)
app.include_router(health.router)
app.include_router(vendors.router)
app.include_router(recurring.router)
app.include_router(invoices.router)
app.include_router(gst.router)
app.include_router(audit.router)
app.include_router(dashboard.router)
app.include_router(ai_platform.router)
app.include_router(auth.router)
app.include_router(ledger_heads.router)
app.include_router(users.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "LedgerLens API", "version": "0.6.0", "docs": "/docs", "health": "/health"}
