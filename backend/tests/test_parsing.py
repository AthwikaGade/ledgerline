from datetime import date

import pytest

from ledgerline.parsing import parse_amount, parse_date


@pytest.mark.parametrize("printed, expected", [
    ("100819/-", 100819.0),            # dev_016 as Haiku copied it: AP_POLICY 1 lists the "/-" suffix
    ("Rs. 1,00,819/-", 100819.0),
    ("Rs 2,480.00", 2480.0),
    ("Rs.2480", 2480.0),
    ("INR 1,23,456.78", 123456.78),
    ("₹ -0.40", -0.40),
    ("-0.40", -0.40),
])
def test_amount_formats_listed_in_the_policy(printed, expected):
    assert parse_amount(printed) == pytest.approx(expected)


@pytest.mark.parametrize("printed", ["100819/- approx", "Rs 2,480.00 only", "2480 USD", "nan", "inf", "1e5",
                                     "12 BOX", "Rs.", "1,450.00/box", "$50.00"])
def test_anything_else_is_refused_not_guessed(printed):
    """Money stays strict: text after an amount, other currencies' symbols and float() oddities are refused, so the
    document escalates or becomes a processing_error instead of carrying an invented number."""
    with pytest.raises(ValueError):
        parse_amount(printed)


def test_parse_amount_indian_grouping():
    assert parse_amount("1,23,456.00") == 123456.0


def test_parse_amount_rupee_symbol():
    assert parse_amount("₹ 2,480.00") == 2480.0


def test_parse_amount_passes_numbers_through():
    assert parse_amount(1789.2) == 1789.2


def test_parse_amount_empty_is_none():
    assert parse_amount("") is None


def test_parse_date_iso():
    assert parse_date("2026-04-25") == date(2026, 4, 25)


def test_parse_date_with_slashes():
    # Corrected: the starter expected 4 March, which contradicts AP_POLICY 1 ("Indian vendors print dates day
    # first"). Where tests and the policy disagree, the policy wins. 03/04/2026 from an Indian vendor is 3 April.
    assert parse_date("03/04/2026") == date(2026, 4, 3)


def test_parse_date_us_vendor_month_first():
    # AP_POLICY 1: vendors whose country in the vendor master is US print MM/DD/YYYY.
    assert parse_date("03/04/2026", month_first=True) == date(2026, 3, 4)


def test_parse_date_iso_is_never_day_swapped():
    assert parse_date("2026-04-05") == date(2026, 4, 5)
    assert parse_date("2026-04-05", month_first=True) == date(2026, 4, 5)


def test_parse_date_day_first_when_unambiguous():
    assert parse_date("25/04/2026") == date(2026, 4, 25)
