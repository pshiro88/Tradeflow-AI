# TradeFlow AI

A B2B trade-operations platform for exporters: issue export invoices, import bank payments, **reconcile them deterministically**, read trade documents with a **local LLM**, check compliance paperwork, and ask questions in plain English.

> **All data is synthetic.** There is no real banking, no real compliance approval and no paid API. Everything, including the AI, runs on your own machine.

![Overview dashboard](screenshots/01-dashboard.png)

## Why it is built this way

Cross-border trade finance fails in boring places: a payment arrives in the wrong currency, a name is spelled differently, a document does not agree with its invoice. This project is built around one rule: **software decides money, the AI only reads and explains.**

| The AI may | The AI may never |
|---|---|
| Read a PDF and propose field values | Create or change an invoice, payment or allocation |
| Reword an answer that was already computed from the database | Write or run SQL, or choose which data to fetch |
| Explain a discrepancy a rule already found | Decide whether a payment matches an invoice |

Every AI output is checked, labelled as AI-generated, and logged. If the model is offline, wrong or slow, the app falls back to the deterministic answer and keeps working.

## Features

| Area | What it does |
|---|---|
| **Invoices** | Create, edit, publish and cancel export invoices. Status (Paid / Overdue / Partially paid / Open) is *derived* from allocations and due date, never typed in. |
| **Payment import** | CSV upload with row-level validation, duplicate detection, an error report you can download, and an import history. |
| **Reconciliation** | A pure rule engine: duplicate check, exact reference, currency check, fuzzy name match (RapidFuzz), amount versus outstanding. Results: Matched, Partial, Unmatched, Mismatch, Duplicate, Manual review. A person approves or rejects the uncertain ones. |
| **Dashboard** | Per-currency KPIs, invoiced-vs-received trend, status and currency charts, ageing, recent transactions. Currencies are never added together. |
| **Documents (AI)** | Upload a PDF, run local extraction, review each field marked *found in document* or *not in document*, then confirm. Nothing financial is created from a document. |
| **Compliance** | A document checklist per invoice, manual reviews with remarks, a document-vs-invoice consistency check and a simulated "ready" status. |
| **AI Copilot** | Eight supported questions (overdue invoices, ageing, unreconciled payments, discrepancies, top outstanding buyers, missing documents, explain an invoice / transaction). |
| **Audit logs** | Admin-only trail of every manual action with before/after values, plus a separate log of every AI request. |
| **Roles** | Admin, Finance and Operations, enforced in the backend; the UI only hides what the API would refuse. |

## Screenshots

| | |
|---|---|
| ![Invoices](screenshots/02-invoices.png) | ![Lifecycle](screenshots/03-invoice-lifecycle.png) |
| ![Payment import](screenshots/04-payment-import.png) | ![Reconciliation review](screenshots/05-reconciliation-review.png) |
| ![Document extraction](screenshots/06-document-extraction.png) | ![Copilot](screenshots/07-copilot.png) |
| ![Compliance](screenshots/08-compliance.png) | ![Audit logs](screenshots/09-audit-logs.png) |

![Discrepancy explanation](screenshots/10-discrepancy-explanation.png)

## Architecture

```mermaid
flowchart LR
  subgraph Browser
    UI["React + TypeScript<br/>TanStack Query"]
  end
  subgraph Backend["FastAPI"]
    API["API routes<br/>(thin, role checks)"] --> SVC["Services<br/>(business rules)"]
    SVC --> REPO["Repositories<br/>(SQL only)"]
    SVC --> ENG["Reconciliation engine<br/>(pure Python)"]
    SVC --> GUARD["AI guardrails"]
    GUARD --> LLM["OllamaService<br/>(only code that calls the model)"]
  end
  UI -- "/api/v1 + JWT" --> API
  REPO --> DB[("PostgreSQL 16<br/>constraints + triggers")]
  LLM --> OLL["Ollama<br/>qwen2.5:3b (local)"]
```

New to the project? Start with [docs/application-flow.md](docs/application-flow.md): logins, the business flow and a guided walkthrough. More detail is in [docs/architecture.md](docs/architecture.md), [docs/database-schema.md](docs/database-schema.md) and [docs/api-documentation.md](docs/api-documentation.md).

**Tech stack**

- **Frontend:** React 19, TypeScript (strict), Vite, Tailwind CSS v4, shadcn/ui, React Router, TanStack Query, React Hook Form + Zod, Recharts
- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, PostgreSQL 16, PyJWT + Argon2, RapidFuzz, PyMuPDF
- **AI:** Ollama with `qwen2.5:3b`, called only from `backend/app/services/ollama_service.py`

## Quick start

You need:

- **Python 3.12 or newer** (developed on 3.13)
- **Node.js 20.19+ or 22.12+** (Vite 8 refuses older versions; developed on 24)
- **Docker Desktop**, running, for PostgreSQL
- optionally **[Ollama](https://ollama.com)** for the AI features (about 2 GB model download, about 4 GB free RAM)

Commands below are for Windows (PowerShell or Git Bash). On macOS or Linux, replace `.venv/Scripts/` with `.venv/bin/`. Run each numbered step from the repository root in its own terminal where noted.

```bash
# 1. Database: PostgreSQL on host port 5433 (--wait returns once it is healthy)
docker compose up -d --wait db

# 2. Backend (terminal 1)
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env
#    Now edit .env and replace JWT_SECRET_KEY. To generate a value:
#    .venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(48))"
.venv/Scripts/alembic upgrade head                           # create the tables and DB safety triggers
.venv/Scripts/python -m app.db.seed                          # demo users + data, already reconciled
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# 3. Frontend (terminal 2, from the repository root)
cd frontend
npm install
npm run dev                                                  # http://localhost:5173

# 4. AI, optional (terminal 3)
ollama pull qwen2.5:3b
ollama serve                                                 # skip if the Ollama desktop app is already running
```

`requirements.lock.txt` pins the exact versions this project was tested with. Use `pip install -r requirements.lock.txt` instead of `requirements.txt` if you want an identical install; the unpinned file also works today.

Check that it is up: <http://localhost:8000/health> should show `{"status":"ok","database":"connected"}`. Then open <http://localhost:5173> and sign in with a demo account. The login page has one-click buttons.

| Role | Email | Password | Sees |
|---|---|---|---|
| Admin | `admin@example.com` | `Demo@12345` | Everything, including Audit Logs |
| Finance | `finance@example.com` | `Demo@12345` | Invoices, Payments, Reconciliation, Copilot |
| Operations | `operations@example.com` | `Demo@12345` | Invoices, Documents, Compliance, Copilot |

The seed command wipes the database and recreates the demo state, so it is also the reset button. Run it again whenever you want a clean start. It also regenerates `sample_data/` (a payment CSV, an invoice listing, four extra payment "packs" for demos in `sample_data/payment_packs/`, and four sample PDFs) so the files always agree with the dates in the database.

### Environment variables (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://tradeflow:...@localhost:5433/tradeflow` | PostgreSQL connection |
| `JWT_SECRET_KEY` | an insecure dev placeholder | Signs login tokens. **Always set a long random value**; the placeholder is public. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Token lifetime |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed browser origins |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama server |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Model used for extraction and wording |
| `OLLAMA_TIMEOUT_SECONDS` | `120` | Per-request model timeout |
| `UPLOAD_DIR` / `MAX_UPLOAD_MB` | `uploads` / `10` | Document storage and size limit |

## A five-minute demo

1. **Admin or Finance, Overview:** four currencies, each shown separately, never converted.
2. **Finance, Reconciliation:** open TXN-1019. GBP 6,000 was paid against a GBP 5,200 invoice; the engine refuses to over-allocate and explains why. Approve it with a note.
3. **Finance, Reconciliation:** TXN-1008 (EUR) against a USD invoice is flagged as a currency mismatch, not matched.
4. **Operations, Documents:** upload `sample_data/documents/INV-1024_commercial_invoice.pdf`, run extraction, and see every field marked *found in document*. Then upload `INV-1018_commercial_invoice_amount_differs.pdf` and see the amount difference flagged.
5. **Operations, Compliance:** record reviews until INV-1010 reads "ready (simulated)".
6. **Finance, AI Copilot:** ask "Which invoices are overdue?" The figures come from SQL; the model only rewords. Stop Ollama and ask again: you still get a correct answer, labelled as a standard answer.
7. **Admin, Audit Logs:** see every manual action with before/after values, and every AI request with model and duration.

## How the guarantees are enforced

- **Money is exact.** `Decimal` in Python, `NUMERIC(18,2)` in PostgreSQL, strings in JSON, never floats, never summed across currencies.
- **The database defends itself.** Triggers reject an allocation larger than the payment or the invoice, in a different currency, or any edit to an existing allocation (append-only). A bug in the app cannot corrupt the ledger.
- **Reconciliation is concurrency-safe.** Runs lock rows with `SKIP LOCKED`; two runs cannot allocate the same payment.
- **The engine is pure.** No database, HTTP or clock inside the matching logic, so it is unit-tested directly.
- **LLM output is untrusted.** JSON-schema-constrained, validated field by field, grounded against the PDF text, and confidence is labelled as an estimate.
- **Copilot answers are guarded.** Intent rules first (the model is only a fallback classifier), fixed query handlers, a deterministic draft, and a check that rejects a reworded answer that adds a number or reference, or drops one.

## Tests

The tests need the Docker database from step 1 to be running; they create and use a separate `tradeflow_test` database, so your demo data is never touched.

```bash
cd backend
.venv/Scripts/python -m pytest -q              # 974 passed, 6 skipped (no model needed: tests use a fake LLM)
RUN_OLLAMA_TESTS=1 .venv/Scripts/python -m pytest tests/test_ollama_live.py -s   # optional, real model, ~4 min on CPU
cd ../frontend && npm run build                # type-check + production build
```

The suite covers the reconciliation engine, import rules, DB triggers and concurrency, role access on every endpoint, AI guardrails, the copilot, compliance rules and audit logging. Each step was also exercised in a real browser (Playwright against Edge) with the real model; those scripts are not part of this repository.

## Project layout

```
backend/app/
  api/v1/endpoints/   thin route handlers
  services/           business rules, AI layer, reconciliation engine
  repositories/       all SQL
  models/ schemas/    SQLAlchemy models, Pydantic schemas
  db/                 migrations helpers, triggers, seed data
frontend/src/
  features/           one folder per module (invoices, payments, reconciliation, ...)
  components/         shared UI and charts
  routes/             navigation and role guards
docs/                 architecture, schema, API
sample_data/          generated CSVs and PDFs for the demo
```

## Known limitations

- **Synthetic only.** No real bank, SWIFT or customs integration. "Ready" in compliance is a simulation, not legal or regulatory approval.
- **PDFs with a text layer only.** Scanned images are rejected rather than guessed at; there is no OCR.
- **A 3B local model is slow on CPU** (extraction takes roughly a minute) and is only as accurate as its grounding checks allow. That is why every extracted field is checked against the document text and confirmed by a person.
- **No currency conversion.** Each currency is reported separately by design.
- **Auth is demo-grade.** Access tokens live in `localStorage` with no refresh tokens, no password reset and no rate limiting, and the app starts with a public placeholder signing key if `JWT_SECRET_KEY` is not set. Fine for a local demo, not for production.
- **Fixed copilot vocabulary.** It answers eight kinds of question; anything else gets a polite "I can't answer that" rather than a guess.
- **Single instance.** No background workers, email or notifications.

## Future enhancements

OCR for scanned documents, an FX-rate table for a converted portfolio view, bank-statement formats beyond CSV (MT940, camt.053), email/webhook notifications for overdue invoices, refresh tokens with httpOnly cookies, and a larger model behind the same `LLMClient` interface.
