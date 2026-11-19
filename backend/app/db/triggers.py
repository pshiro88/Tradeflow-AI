"""Database-level guards for money integrity (PostgreSQL triggers).

The application already validates allocations, but financial invariants are also enforced here so that
no bug, script or concurrent request can break them:

  1. An allocation's currency must equal both the payment's and the invoice's currency.
  2. The sum of allocations can never exceed the payment amount.
  3. The sum of allocations can never exceed the invoice total.
  4. Allocations are append-only: UPDATE and DELETE are rejected (TRUNCATE is used for demo resets).

The limit trigger locks the payment and then the invoice row (always in that order) so concurrent
allocations are serialised and cannot slip past the totals together.

Used by the Alembic migration and by the test-suite schema setup (which builds tables with create_all).
"""

from sqlalchemy.engine import Connection

INSTALL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE OR REPLACE FUNCTION enforce_allocation_limits() RETURNS trigger AS $$
    DECLARE
        pay_amount numeric;
        pay_currency varchar;
        inv_total numeric;
        inv_currency varchar;
        pay_allocated numeric;
        inv_allocated numeric;
    BEGIN
        SELECT amount, currency INTO pay_amount, pay_currency
          FROM payments WHERE id = NEW.payment_id FOR UPDATE;
        SELECT total_amount, currency INTO inv_total, inv_currency
          FROM invoices WHERE id = NEW.invoice_id FOR UPDATE;

        IF NEW.currency <> pay_currency OR NEW.currency <> inv_currency THEN
            RAISE EXCEPTION 'Allocation currency must match both the payment and the invoice'
                USING ERRCODE = 'check_violation';
        END IF;

        SELECT COALESCE(SUM(allocated_amount), 0) INTO pay_allocated
          FROM payment_allocations WHERE payment_id = NEW.payment_id;
        SELECT COALESCE(SUM(allocated_amount), 0) INTO inv_allocated
          FROM payment_allocations WHERE invoice_id = NEW.invoice_id;

        IF pay_allocated + NEW.allocated_amount > pay_amount THEN
            RAISE EXCEPTION 'Allocation would exceed the payment amount'
                USING ERRCODE = 'check_violation';
        END IF;
        IF inv_allocated + NEW.allocated_amount > inv_total THEN
            RAISE EXCEPTION 'Allocation would exceed the invoice amount'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_allocation_limits ON payment_allocations",
    """
    CREATE TRIGGER trg_allocation_limits
        BEFORE INSERT ON payment_allocations
        FOR EACH ROW EXECUTE FUNCTION enforce_allocation_limits()
    """,
    """
    CREATE OR REPLACE FUNCTION forbid_allocation_changes() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'Payment allocations are append-only and cannot be changed or deleted'
            USING ERRCODE = 'integrity_constraint_violation';
    END;
    $$ LANGUAGE plpgsql
    """,
    "DROP TRIGGER IF EXISTS trg_allocation_immutable ON payment_allocations",
    """
    CREATE TRIGGER trg_allocation_immutable
        BEFORE UPDATE OR DELETE ON payment_allocations
        FOR EACH ROW EXECUTE FUNCTION forbid_allocation_changes()
    """,
)

UNINSTALL_STATEMENTS: tuple[str, ...] = (
    "DROP TRIGGER IF EXISTS trg_allocation_immutable ON payment_allocations",
    "DROP TRIGGER IF EXISTS trg_allocation_limits ON payment_allocations",
    "DROP FUNCTION IF EXISTS forbid_allocation_changes()",
    "DROP FUNCTION IF EXISTS enforce_allocation_limits()",
)


def install_triggers(connection: Connection) -> None:
    for statement in INSTALL_STATEMENTS:
        connection.exec_driver_sql(statement)


def uninstall_triggers(connection: Connection) -> None:
    for statement in UNINSTALL_STATEMENTS:
        connection.exec_driver_sql(statement)
