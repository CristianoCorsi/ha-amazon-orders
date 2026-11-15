from datetime import date

from amazon_orders_ha.mapping import parse_delivery_status

TODAY = date(2026, 11, 15)


def test_delivered_same_year():
    assert parse_delivery_status("Delivered 28 October", date(2026, 10, 20), TODAY) == ("delivered", date(2026, 10, 28))


def test_year_rolls_over_when_delivery_before_placed_month():
    # placed 28 Dec, delivered 2 January => next year
    assert parse_delivery_status("Delivered 2 January", date(2025, 12, 28), TODAY) == ("delivered", date(2026, 1, 2))


def test_delivery_equal_to_placed_date_is_same_year():
    assert parse_delivery_status("Delivered 5 March", date(2024, 3, 5), TODAY)[1] == date(2024, 3, 5)


def test_us_style_and_weekday_prefix():
    assert parse_delivery_status("Delivered Monday, October 28", date(2024, 10, 20), TODAY)[1] == date(2024, 10, 28)


def test_explicit_year_is_respected():
    assert parse_delivery_status("Delivered 3 May 2021", date(2021, 5, 1), TODAY)[1] == date(2021, 5, 3)


def test_leap_day():
    assert parse_delivery_status("Delivered 29 February", date(2027, 12, 1), TODAY)[1] == date(2028, 2, 29)


def test_today_and_yesterday():
    assert parse_delivery_status("Delivered today", date(2026, 11, 14), TODAY)[1] == TODAY
    assert parse_delivery_status("Delivered yesterday", date(2026, 11, 10), TODAY)[1] == date(2026, 11, 14)


def test_pending_status_has_no_delivered_date():
    kind, d = parse_delivery_status("Arriving 20 November", date(2026, 11, 14), TODAY)
    assert kind == "pending" and d is None


def test_none_and_garbage():
    assert parse_delivery_status(None, date(2026, 1, 1), TODAY) == ("unknown", None)
    assert parse_delivery_status("Delivered", date(2026, 1, 1), TODAY) == ("delivered", None)
    assert parse_delivery_status("Delivered 31 Smarch", date(2026, 1, 1), TODAY)[1] is None
