# LedgerLens V2 — Build Progress

Source of truth for where the V2 build stands. If a session gets
interrupted, hand this file back and work resumes exactly where it's
marked — not from scratch. **Nothing is marked done unless it was actually
run and verified — no aspirational checkmarks.**

---

## PHASES 1-4 — ✅ CORE DONE
## PHASE 5 — SAAS — ✅ CORE DONE (all 15 routers on real auth, full UI built)

(See prior zips / earlier entries for full detail. Summary: every backend
router requires real JWT auth with proven cross-firm isolation; full
7-page Streamlit UI exposing everything the backend does, including a
correction UI that was previously completely missing.)

---

## PRODUCTION-READINESS WORK — this session

Three of the "Tier 1" gaps identified in the last production-readiness
review are now built and verified: rate limiting, database migrations,
and password reset. All three were actually tested against a live app,
not just written.

### 1. Rate limiting — ✅ DONE, verified live
- `/auth/login`: 5/minute per IP (default, configurable via
  `LOGIN_RATE_LIMIT`). `/auth/register`: 10/hour per IP (`REGISTER_RATE_LIMIT`).
- Verified over real HTTP: 5 rapid login attempts correctly return 401
  (wrong password), the 6th correctly returns 429. Same live-verified
  pattern for registration at the 10-request boundary.
- **A real bug found and fixed**: the rate limiter's in-memory counter is
  a process-wide singleton. Running the full pytest suite (130+ tests,
  many registering their own test users) was tripping the real limit and
  causing unrelated test failures with confusing `KeyError`s (a 429
  response has no `access_token` field, so tests trying to read one from
  a rate-limited response crashed instead of failing cleanly). Fixed with
  an autouse `tests/conftest.py` fixture that resets the limiter before
  every test — each test now gets a clean rate-limit window, matching how
  a real distinct client would experience the app.
- In-memory storage only — fine for one process, won't be shared across
  multiple instances behind a load balancer (documented in
  `app/services/rate_limit.py`, Redis is the noted upgrade path).

### 2. Password reset — ✅ DONE, verified live
- `POST /auth/forgot-password` (email) → `POST /auth/reset-password`
  (token + new password).
- Tokens: single-use, expire after 30 minutes (configurable), stored as a
  SHA-256 hash (never plaintext) in a new `PasswordResetToken` table.
- Same email-enumeration protection already used at login: identical
  response whether or not the email is registered. Verified with a
  dedicated test comparing both response bodies byte-for-byte.
- Verified end-to-end: old password stops working after reset, new
  password works, a token can only be used once (second use correctly
  rejected), an expired token is correctly rejected (tested via a
  directly-backdated token rather than waiting real minutes).
- **Email sending follows the existing zero-cost/local-first pattern**
  (same shape as `LLM_PROVIDER`/`OCR_ENGINE`): defaults to logging the
  reset link (`EMAIL_PROVIDER=console`) rather than requiring a paid email
  service to run at all. Verified live: the logged link appeared correctly
  in the server console. Real SMTP sending is implemented
  (`EMAIL_PROVIDER=smtp`) but — honest gap — has not been tested against a
  real SMTP server/inbox, only code-reviewed; no SMTP credentials were
  available in this sandbox to test against.

### 3. Alembic migrations — ✅ DONE, verified live including the part that actually matters
- Initial migration generated and confirmed to correctly detect and
  create all 10 real tables with their exact indexes.
- **The test that actually proves this works, not just the one-time
  setup**: added a real temporary column to a model, ran
  `alembic revision --autogenerate`, confirmed it detected EXACTLY that
  one change and nothing else, ran `alembic upgrade head` and confirmed
  the column actually appeared in the live database, then ran
  `alembic downgrade -1` and confirmed it was correctly removed. Both
  directions (up and down) proven, not just up.
- **The strongest verification**: built a completely fresh database using
  ONLY `alembic upgrade head` — zero involvement from the app's own
  `Base.metadata.create_all()` — then ran the real live FastAPI app against
  that Alembic-built database and confirmed real register/login/health
  HTTP requests all worked correctly. This proves Alembic's schema is
  100% what the app actually expects at runtime, not just structurally
  similar on paper.
- `env.py` correctly imports all real models and pulls `DATABASE_URL` from
  the app's own config (not a separately hardcoded value that could drift
  out of sync).
- Honest note on coexistence: the app's startup still calls
  `Base.metadata.create_all()` for zero-config local dev convenience; this
  is safe alongside Alembic (create_all only creates missing tables, never
  touches Alembic's own version tracking) but a real production deployment
  should rely on `alembic upgrade head` as the actual source of truth for
  schema state, not both mechanisms casually coexisting forever.

### 4. Invite-teammate flow — ✅ DONE, verified live end-to-end
- `POST /users/invite` (requires CA_AUDITOR role+), `POST /auth/accept-invite`
  (public -- the invitee has no account until this call creates one),
  `GET /users` (list a firm's team), `GET /users/invites/pending`
  (requires CA_AUDITOR+).
- New `Invite` model: single-use, 7-day-expiring, hashed token (same
  SHA-256-for-lookup principle as password reset tokens).
- **This was the gap that made the whole RBAC system built in Phase 5
  somewhat theoretical** -- until now, `tests/test_rbac.py` had to insert
  lower-privilege users directly into the database to test role
  enforcement at all, because there was no real way to create one. That
  workaround is still used for some tests (documented in the test file),
  but a genuine invite flow now exists as an alternative.
- **Two real permission checks, both verified, not just assumed:**
  1. A role below CA_AUDITOR can't call `/users/invite` at all (403).
  2. A CA_AUDITOR who meets that floor still can't invite someone to
     SUPER_ADMIN -- you can't grant a role more privileged than your own,
     verified with a dedicated test distinct from check #1.
- **Verified live, the full real-world sequence**: registered an owner,
  invited a teammate as ACCOUNTANT, read the invite link from the
  console-mode email log (same pattern as password reset), accepted the
  invite, confirmed the new teammate could log in **independently with
  their own password**, and confirmed `/users` showed both team members
  with the correct roles. Not a mocked flow -- an actual second account
  that works.
- Invite tokens are single-use (verified) and reject reuse of an email
  that already has an account, checked both at invite-creation time and
  again at accept time (in case a second account was created via a
  different path in between).
- Streamlit UI: new "Team" page — view team members, send invites (role
  dropdown), view pending invites. Verified every field the page reads
  against real live API responses.

### Test count
138 tests passing: 122 at the end of the previous session + 3
rate-limiting + 6 password-reset + 7 invite-flow tests this session.
Alembic itself isn't unit-tested in the pytest suite (migration tooling is
verified via the manual live-database tests described above, which is the
right kind of test for this — pytest isn't well-suited to testing schema
migration side effects against a real DB file).

---

## Remaining Tier 1/2 production-readiness gaps (from the last review, still true)
- [ ] Real Postgres/Docker end-to-end test — still not possible in this
      sandbox (Postgres server package 404s from the sandbox mirror,
      Docker isn't installed here). Alembic against SQLite is now proven;
      the same commands against a real Postgres instance need confirming
      on a real machine.
- [ ] SMTP email sending is implemented but untested against a real inbox.
- [ ] No MFA.
- [ ] No file storage migration off local disk (still `uploaded_files/` on
      the app server, won't survive a redeploy or scale past one instance).
- [ ] No pagination on list endpoints.
- [ ] No CI/CD wiring (tests exist and pass, aren't run automatically on push).
- [ ] DPDP Act compliance decisions (data retention/deletion flow, privacy
      policy) not addressed at the product level.
- [ ] SBI/HDFC/ICICI parser column logic still unverified against a real
      bank statement.

---

## How to resume this build in a new session

1. Share this file (or say "continue LedgerLens V2").
2. Known environment quirks (not code issues): background processes die
   the instant a single tool call ends here (live tests must launch AND
   exercise the server in one atomic command); huggingface.co and the
   Groq/OpenAI API endpoints are unreachable; the `postgresql-16` apt
   package 404s from this sandbox's mirror; Docker isn't installed here;
   no real SMTP server available to test email sending against.
3. **Packaging reminder**: run the final confirming pytest pass BEFORE
   cleaning `uploaded_files/`, not after.
