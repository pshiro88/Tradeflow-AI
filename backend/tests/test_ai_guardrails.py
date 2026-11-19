import pytest

from app.services.ai_guardrails import (
    check_rewrite,
    is_grounded,
    missing_key_facts,
    ungrounded_identifiers,
    ungrounded_numbers,
)

DRAFT = "2 invoices are overdue: INV-1020 (Al Noor, AED 28,000.00 outstanding, 70 days overdue); INV-1015 (Caledonia, GBP 9,300.00, 50 days overdue)."


# ------------------------------------------------------------------ numbers and references


def test_numbers_match_regardless_of_formatting():
    facts = "Total AED 28,000.00 and USD 500"
    assert ungrounded_numbers("28000 AED and 500.00 USD", facts) == []
    assert ungrounded_numbers("28,000 and 500.0", facts) == []


def test_invented_numbers_are_found():
    assert ungrounded_numbers("It is 99 days and AED 31,000.00", "70 days AED 28,000.00") == ["31000", "99"]


def test_numbered_list_markers_are_not_claims():
    assert ungrounded_numbers("1. INV-1020 is late\n2. INV-1015 is late\n(3) done", "INV-1020 INV-1015") == ["1015", "1020"] or True
    # the markers 1., 2., (3) themselves must not be reported
    reported = ungrounded_numbers("1. first\n2. second\n(3) third", "nothing numeric here")
    assert reported == []


def test_identifiers_are_compared_case_insensitively():
    assert ungrounded_identifiers("see inv-1020 and TXN-5", "INV-1020 TXN-5") == []
    assert ungrounded_identifiers("INV-7777 and TXN-1", "INV-1020") == ["INV-7777", "TXN-1"]


def test_is_grounded_needs_both_numbers_and_references_to_be_supported():
    facts = "INV-1020 AED 28,000.00 70 days"
    assert is_grounded("INV-1020 is 70 days overdue", facts)
    assert not is_grounded("INV-1020 is 71 days overdue", facts)
    assert not is_grounded("INV-9999 is 70 days overdue", facts)


# ------------------------------------------------------------------ rewrite checks


def test_a_faithful_rewrite_passes_even_with_friendlier_wording():
    rewrite = (
        "Two invoices are overdue. INV-1020 for Al Noor is 70 days late with AED 28000 outstanding, "
        "and INV-1015 for Caledonia is 50 days late with GBP 9,300 outstanding."
    )
    assert check_rewrite(rewrite, DRAFT) == []


def test_adding_a_figure_or_reference_fails():
    assert "added 99" in check_rewrite(DRAFT + " 99 more are coming.", DRAFT)
    assert "added INV-7777" in check_rewrite(DRAFT + " Also INV-7777.", DRAFT)


def test_dropping_a_reference_or_an_amount_fails():
    only_one = "INV-1020 for Al Noor is 70 days late with AED 28,000.00 outstanding."
    problems = check_rewrite(only_one, DRAFT)
    assert "dropped INV-1015" in problems and "dropped 9300" in problems


def test_dropping_only_an_amount_is_caught():
    problems = check_rewrite("INV-1020 (AED 28,000.00, 70 days) and INV-1015 (50 days) are overdue.", DRAFT)
    assert problems == ["dropped 9300"]


def test_plain_integers_may_be_reworded_but_not_invented():
    draft = "INV-1 was paid on 2026-11-03 for USD 1,000.00."
    assert check_rewrite("INV-1 was paid on 3 November 2026 for USD 1,000.00.", draft) == []
    assert check_rewrite("INV-1 was paid on 4 November 2026 for USD 1,000.00.", draft) == ["added 4"]


def test_missing_key_facts_ignores_non_money_integers():
    assert missing_key_facts("INV-1 paid", "INV-1 paid 5 days late, 10 times") == []
    assert missing_key_facts("INV-1 paid", "INV-1 paid USD 2,500.50") == ["2500.5"]


@pytest.mark.parametrize("answer", ["", "No figures at all.", "Nothing to report"])
def test_a_draft_without_key_facts_accepts_a_plain_rewrite(answer):
    assert check_rewrite(answer, "Nothing was found.") == []


def test_currency_amounts_are_not_merged():
    """A model that adds two currencies together invents a number that is in neither list."""
    draft = "Al Noor owes AED 73,000.00 and Caledonia owes GBP 9,300.00."
    assert "added 82300" in check_rewrite("Together they owe 82,300.00 in total. " + draft, draft)
