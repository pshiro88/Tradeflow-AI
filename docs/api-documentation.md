# API documentation

Base URL `http://localhost:8000/api/v1`. Interactive docs: <http://localhost:8000/docs> (Swagger) and `/openapi.json`.

Authentication: `POST /auth/login` returns a JWT. Send it as `Authorization: Bearer <token>`.

- Money values are **strings** (`"10000.00"`), never numbers.
- Business-rule errors return `{ "detail": "<message>" }` with a meaningful status (400, 404, 409, 413, 422; 502/503 when the AI model fails or is offline). Request validation errors use FastAPI's standard `detail` list naming the offending fields.
- "Roles" below always include Admin.

## Auth
| Method | Path | Roles | Purpose |
|---|---|---|---|
| POST | `/auth/login` | public | Email and password to access token |
| GET | `/auth/me` | any | Current user |
| POST | `/auth/logout` | any | Ends the session (client discards the token) |

## Invoices
| Method | Path | Roles | Purpose |
|---|---|---|---|
| GET | `/invoices` | any | Search, filter (status, currency, buyer, dates), sort, paginate |
| POST | `/invoices` | Finance | Create a draft or open invoice |
| GET | `/invoices/{id}` | any | Detail with received, outstanding and payment history |
| PUT | `/invoices/{id}` | Finance | Edit (number, currency, parties lock once payments exist) |
| PATCH | `/invoices/{id}/status` | Finance | Publish a draft or cancel an invoice with no payments |
| GET | `/invoices/{id}/lifecycle` | any | Invoiced, documents, payment and readiness steps (counts only) |
| GET | `/invoices/buyers`, `/invoices/exporters` | any | Lookup lists for forms |

## Payments
| Method | Path | Roles | Purpose |
|---|---|---|---|
| POST | `/payments/import` | Finance | Upload a CSV; returns accepted, rejected and duplicate counts with row errors |
| GET | `/payments/imports`, `/payments/imports/{batch_id}` | Finance | Import history and one batch |
| GET | `/payments/imports/{batch_id}/errors.csv` | Finance | Download rejected rows with reasons |
| GET | `/payments`, `/payments/{id}` | Finance | List and detail |

Expected CSV header: `transaction_reference,payment_reference,sender_name,currency,amount,transaction_date,bank_reference`.

## Reconciliation
| Method | Path | Roles | Purpose |
|---|---|---|---|
| POST | `/reconciliation/run` | Finance | Reconcile all pending payments (row-locked, safe to repeat) |
| GET | `/reconciliation` | Finance | Results with filters and pagination |
| GET | `/reconciliation/summary` | Finance | Counts by status |
| GET | `/reconciliation/{id}` | Finance | Decision, explanation and candidate invoices |
| GET | `/reconciliation/{id}/eligible-invoices` | Finance | Invoices a person may allocate to (same currency, balance outstanding) |
| POST | `/reconciliation/{id}/approve` | Finance | Allocate, with optional amount and a note; audited |
| POST | `/reconciliation/{id}/reject` | Finance | Reject the suggestion; audited |

## Dashboard
Roles: Finance. `GET /dashboard/summary`, `/payment-trends`, `/payment-distribution`, `/currency-distribution`, `/recent-transactions`, `/outstanding-invoices`. All values come from SQL aggregates and respect the date, currency, payment-status and buyer filters. Totals are per currency.

## Documents (AI)
| Method | Path | Roles | Purpose |
|---|---|---|---|
| POST | `/documents/upload` | Operations | Upload a PDF (type, optional invoice link); text-layer PDFs only |
| POST | `/documents/{id}/extract` | Operations | Run local extraction; returns validated, grounded fields |
| POST | `/documents/{id}/explain` | Operations | Explain differences from the linked invoice |
| POST | `/documents/{id}/verify` | Operations | Confirm (with edited values) or reject |
| GET | `/documents`, `/documents/{id}`, `/documents/invoice/{invoice_id}` | Operations | List, detail, per invoice |

## Compliance
| Method | Path | Roles | Purpose |
|---|---|---|---|
| GET | `/compliance` | Operations | Overview across issued invoices |
| GET | `/compliance/{invoice_id}` | Operations | Checklist, consistency findings, readiness |
| POST | `/compliance/{invoice_id}/checks` | Operations | Append a manual review with remarks |

## AI Copilot
| Method | Path | Roles | Purpose |
|---|---|---|---|
| POST | `/ai/chat` | any | Ask a question; response says whether the wording was AI-generated or a standard answer |
| POST | `/ai/explain-discrepancy` | Finance | Explain one reconciliation discrepancy |
| GET | `/ai/suggestions` | any | Questions offered for the user's role |
| GET | `/ai/history` | any | The user's recent questions |
| GET | `/ai/status` | any | Whether the local model is reachable |

## Audit logs (Admin only)
`GET /audit-logs` (manual actions, filters for action, user, entity and dates), `GET /audit-logs/ai` (AI requests with model, status and duration), `GET /audit-logs/options` (filter choices).

## Health
`GET /health` and `GET /api/v1/health` return `{"status": "ok"}`.
