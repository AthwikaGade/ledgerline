from datetime import date

from ledgerline.parsing import parse_amount, parse_date


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
