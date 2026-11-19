"""Invoice status rules (BRD FR-009).

DRAFT and CANCELLED are manual states and are never overridden. For every other invoice the
status is derived, in this order of precedence:

    1. PAID            received >= total
    2. OVERDUE         due date has passed and a balance remains (even if partly paid)
    3. PARTIALLY_PAID  some money received, balance remains, not yet due
    4. OPEN            nothing received, not yet due

The same rule exists as a SQL expression in `InvoiceRepository.status_expression`, so that lists,
filters and dashboards stay correct as time passes without a write. A test keeps the two in sync.
"""

from datetime import date
from decimal import Decimal

from app.models.enums import InvoiceStatus

MANUAL_STATES = frozenset({InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED})


def derive_status(
    stored_status: InvoiceStatus,
    total_amount: Decimal,
    amount_received: Decimal,
    due_date: date,
    today: date,
) -> InvoiceStatus:
    if stored_status in MANUAL_STATES:
        return stored_status
    if amount_received >= total_amount:
        return InvoiceStatus.PAID
    if due_date < today:
        return InvoiceStatus.OVERDUE
    if amount_received > 0:
        return InvoiceStatus.PARTIALLY_PAID
    return InvoiceStatus.OPEN
