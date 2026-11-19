# TradeFlow AI: Project Rules

B2B fintech demo: export invoices, payment CSV import, deterministic reconciliation, local-LLM document extraction and a data-grounded copilot. Full spec: `../brd.txt`. Build order and checkpoints: `../IMPLEMENTATION_PLAN.md`.

All data is synthetic. No real banking, no paid APIs.

## Stack
- Frontend: React 19 + TypeScript (strict), Vite, Tailwind v4, shadcn/ui, React Router, TanStack Query, Axios, React Hook Form + Zod, Recharts
- Backend: Python 3.12+ (3.13 in use), FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, PostgreSQL, pytest + httpx
- AI: Ollama (`qwen2.5:3b`), called only from `backend/app/services/ollama_service.py`

## Non-negotiable rules
1. Money is `Decimal` in Python and `NUMERIC(18,2)` in Postgres. Never `float`. Store the currency code with every amount.
2. Never compare amounts across different currencies.
3. The LLM never writes or changes financial records and never makes financial decisions. It only extracts, explains and phrases answers.
4. The copilot uses predefined query handlers. The LLM never generates or executes SQL.
5. Validate all LLM output with Pydantic. Unknown fields are `null`, never invented.
6. Authorization is enforced in the backend (`require_role`). Frontend route guards are only UX.
7. Layering: API route handlers (thin) -> services (business logic) -> repositories (DB access). No business logic in route handlers.
8. The reconciliation matching logic is pure Python with no DB or HTTP calls inside it, so it is unit-testable.
9. Allocations run in a DB transaction. Never over-allocate, never overwrite an existing allocation. Manual actions write an `audit_logs` row.
10. Dashboard values come from SQL aggregates, never hardcoded. Replace mocks once the real API exists.
11. Secrets go in `.env` (never committed). Keep `.env.example` current. Don't log document contents.
12. Timestamps are stored in UTC.

## Workflow
- Work one module at a time, in the order in `IMPLEMENTATION_PLAN.md`.
- After each module: run backend tests, run `npm run build`, verify the API from the UI, and fix errors before moving on.
- If something can't be finished, document it as a known limitation in the README. Don't fake it.
- Keep docs (`docs/`, README) updated as the app changes.

## Commands (fill in as they are created)
- Database (Docker, host port 5433): `docker compose up -d db`
- Migrations: `cd backend && .venv/Scripts/alembic upgrade head` (new: `alembic revision --autogenerate -m "msg"`)
- Backend: `cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000`
- Frontend: `cd frontend && npm run dev` (Vite on :5173, proxies `/api` to :8000)
- Frontend build check: `cd frontend && npm run build`
- Backend tests: `cd backend && .venv/Scripts/python -m pytest`
- Seed/reset demo data (wipes the DB, seeds, then reconciles): `cd backend && .venv/Scripts/python -m app.db.seed` (`--no-reconcile` leaves payments PENDING)

Notes: enums are stored as VARCHAR + CHECK (`enum_type` helper in `app/db/base.py`), not native PG enums.
`reconciliation_results` and `import_batches` tables were added beyond BRD section 8 because the API needs them.
DB triggers (`app/db/triggers.py`) enforce: allocation <= payment, allocation <= invoice, currencies match, allocations append-only (reset uses TRUNCATE).
The reconciliation engine (`services/reconciliation_engine.py`) is PURE: no DB/HTTP/clock; `reconciliation_service.py` does locking + persistence.

## AI layer (Step 8)
- `services/ollama_service.py` is the ONLY code that talks to Ollama. Everything else depends on the `LLMClient` protocol (`get_llm` dependency), so tests inject `tests/fakes.py::FakeLLM`. The suite needs no live model.
- Live-model tests are skipped by default: `RUN_OLLAMA_TESTS=1 python -m pytest tests/test_ollama_live.py -s` (about 4 minutes on CPU).
- The model never queries data, calculates, or decides. Copilot handlers (`copilot_handlers.py`) run fixed queries and build a deterministic answer. The model may only REWORD that draft.
- `ai_guardrails.check_rewrite` rejects a rewrite that ADDS a number/reference or DROPS a reference or money amount. On rejection, Ollama failure, or timeout, the deterministic answer is returned (`generated_by: "RULES"`). Every AI answer is labelled in the UI.
- Extraction JSON schema: `invoice_amount` is `number|null` on purpose. A string-typed amount made qwen2.5:3b return null every time (measured 0/4 vs 4/4). See `document_extraction.output_schema`.
- Extracted values are validated field by field (invalid -> null + issue) and grounded against the PDF text (`FOUND_IN_TEXT` / `NOT_FOUND_IN_TEXT`). The model's own confidence is an estimate, never proof. A person confirms; nothing financial is ever created from a document.
- Every AI call is logged to `ai_audit_logs` (short summaries only, never document text).
- The seed command also regenerates `sample_data/` CSVs and PDFs from the same dates, so uploads always agree with the database.
