# Architecture

## Layers

```
HTTP  ->  api/v1/endpoints   parse input, check the role, call one service
          services           business rules, transactions, audit writes, AI orchestration
          repositories       SQL only (SQLAlchemy); no business decisions
          models / DB        tables, CHECK constraints, triggers
```

Rules that hold everywhere:

- Authorization is enforced in the backend with `require_role(...)`. `ADMIN` is always allowed; `require_role()` with no arguments means Admin only. The frontend only hides links.
- Route handlers contain no business logic.
- Timestamps are UTC. Money is `Decimal` / `NUMERIC(18,2)` and travels as strings in JSON.

## Roles

| Role | Invoices | Dashboard figures | Payments + Reconciliation | Documents + Compliance | Copilot | Audit logs |
|---|---|---|---|---|---|---|
| Admin | full | yes | full | full | yes | yes |
| Finance | full | yes | full | no | yes (incl. discrepancy explanations) | no |
| Operations | read | no (`/dashboard/*` is Finance/Admin) | no | full | yes (discrepancy explanations refused) | no |

Any signed-in role can read an invoice's lifecycle timeline (counts and amounts only).

## Reconciliation

`services/reconciliation_engine.py` is a pure function from `(payment, candidate invoices, already-seen payments)` to a decision. It has no database, HTTP or clock. `reconciliation_service.py` fetches rows with `SELECT ... FOR UPDATE SKIP LOCKED`, calls the engine, then persists the result and any allocation in one transaction.

Decision order, first rule that applies wins:

0. **Duplicate:** an already-processed payment has the same reference, sender, currency, amount and date under a different transaction reference (the bank sent it twice). Identical payments with no reference at all are not treated as duplicates.
1. **Reference:** the payment reference must equal an invoice number (case and spacing ignored).
2. **Currency:** a different currency is a `MISMATCH`; amounts are never compared across currencies or converted.
3. **Buyer name (RapidFuzz):** it can only *block or escalate* a match, never create one. A score of 85 or more accepts the sender as the buyer, 60 to 84 sends the payment to manual review, below 60 is a `MISMATCH`.
4. **Amount versus outstanding:** equal gives `MATCHED`; less gives `PARTIAL`; more than outstanding gives `MANUAL_REVIEW` (the engine never over-allocates).

Whenever the payer or the invoice is uncertain, the engine refuses to allocate and escalates. Allocation happens automatically only on an exact reference match with a compatible currency and a convincing buyer name. With no reference, the engine may *suggest* a candidate by name and amount, but only a person can approve it.

Invoice status is derived, not stored (except DRAFT and CANCELLED): `PAID` > `OVERDUE` > `PARTIALLY_PAID` > `OPEN`. The same rule exists in SQL (a `CASE` used by list and dashboard queries) and Python (`derive_status`); tests keep them aligned.

### Database safety net

`app/db/triggers.py` installs triggers on `payment_allocations`:

- allocated amount must not exceed the payment's unallocated amount
- allocated amount must not exceed the invoice's outstanding amount
- allocation currency must equal both the payment's and the invoice's currency
- rows are append-only (no UPDATE or DELETE; the seed resets with TRUNCATE)

## AI layer

```
question -> intent rules -> (LLM picks an intent only if no rule matched)
         -> role check -> fixed query handler -> deterministic draft
         -> LLM rewords the draft -> check_rewrite -> answer (or the draft if rejected)
```

- `ollama_service.py` is the **only** module that talks to Ollama. Everything else depends on the `LLMClient` protocol and receives it through the `get_llm` dependency, so tests inject `FakeLLM`.
- **Extraction:** JSON-schema-constrained output; each field is validated (invalid becomes `null` plus an issue) and grounded against the PDF text (`FOUND_IN_TEXT`, `NOT_FOUND_IN_TEXT`, `INFERRED`, `MISSING`). The model's confidence is shown as an estimate. A person confirms; nothing financial is created.
- **Copilot guardrail:** `ai_guardrails.check_rewrite` rejects a reworded answer that adds a number or reference, or drops a reference or money amount. On rejection, model failure or timeout, the deterministic answer is returned and labelled `RULES`.
- **Logging:** every AI call writes `ai_audit_logs` (operation, model, status, duration, a short summary). Document text is never stored in the log.

## Compliance

`compliance_rules.py` (pure) defines the checklist: Commercial Invoice, Packing List, Shipping Bill and Bill of Lading / Airway Bill are always required; Remittance Advice becomes required once a payment exists.

- **Effective status of an item:** a verified uploaded document always counts; otherwise the latest manual review; otherwise the document's own status.
- Manual reviews are **append-only** rows in `compliance_checks` (who, when, remarks).
- **Ready (simulated)** = invoice paid, every required item verified, no mismatches.
- A consistency check compares an extracted document's values with the invoice (amount, currency, buyer, dates).

## Frontend

One folder per module under `src/features`. Server state is TanStack Query (with `keepPreviousData` for tables); filters and pagination live in the URL (`useUrlParams`). Navigation, role visibility and breadcrumbs come from one list in `routes/navigation.ts`. Forms use React Hook Form with Zod; API error details are mapped back onto the matching fields.
