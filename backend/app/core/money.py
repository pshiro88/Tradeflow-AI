from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_money(value: Decimal | int | str) -> Decimal:
    """Normalise to exactly 2 decimal places (half-up). All money crossing a module boundary goes through this."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
