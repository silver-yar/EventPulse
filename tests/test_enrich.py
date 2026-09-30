"""Unit tests for EventPulse enrichment (ST-11)."""

import pytest

from src.ingest.enrich import (
    COUNTRIES,
    classify_ua,
    derive_event_day,
    enrich_event,
    geo_country,
    normalize_currency,
)

UA_CASES = [
    # (user_agent, device_type, browser, is_bot)
    (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "mobile", "safari", False,
    ),
    (
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "tablet", "safari", False,
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "desktop", "chrome", False,
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
        "desktop", "firefox", False,
    ),
    ("curl/8.0", "other", "curl", True),
    (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "other", "other", True,
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 "
        "Safari/537.36 HeadlessChrome",
        "desktop", "chrome", True,
    ),
    ("", "other", "other", False),
]


@pytest.mark.parametrize("ua, device, browser, is_bot", UA_CASES)
def test_classify_ua(ua, device, browser, is_bot):
    assert classify_ua(ua) == (device, browser, is_bot)


def test_geo_country_is_deterministic_and_in_table():
    assert geo_country("203.0.113.7") == geo_country("203.0.113.7")
    assert geo_country("") == "unknown"
    assert all(geo_country(f"10.0.0.{i}") in COUNTRIES for i in range(30))
    # a handful of inputs should spread across the table (hash-based)
    assert len({geo_country(f"10.0.0.{i}") for i in range(40)}) > 1


def test_derive_event_day():
    assert derive_event_day("2026-09-04T12:00:00Z") == "2026-09-04"
    assert derive_event_day("2026-09-04T14:30:00+02:00") == "2026-09-04"


CURRENCY_CASES = [
    ({"amount_usd": 42.0}, 42.0),
    ({"amount": 100, "currency": "EUR"}, 113.0),
    ({"amount": 10, "currency": "JPY"}, 0.07),
    ({"amount": 50, "currency": "XXX"}, None),
    ({}, None),
    ("not-a-dict", None),
]


@pytest.mark.parametrize("props, expected", CURRENCY_CASES)
def test_normalize_currency(props, expected):
    assert normalize_currency(props) == expected


def test_enrich_event_adds_all_fields():
    rec = {
        "event_id": "e1",
        "event_type": "page_view",
        "user_id": "u1",
        "event_ts": "2026-09-04T12:00:00Z",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "client_ip": "203.0.113.7",
    }
    out = enrich_event(rec)
    assert out is rec  # in place
    assert out["device_type"] == "desktop"
    assert out["browser"] == "chrome"
    assert out["is_bot"] is False
    assert out["event_day"] == "2026-09-04"
    assert out["geo_country"] == geo_country("203.0.113.7")


def test_payload_client_ip_beats_remote_ip():
    rec = {
        "event_id": "e2", "event_type": "page_view", "user_id": "u1",
        "event_ts": "2026-09-01T00:00:00Z", "client_ip": "1.1.1.1",
    }
    assert enrich_event(rec, remote_ip="2.2.2.2")["geo_country"] == geo_country("1.1.1.1")


def test_enrich_adds_normalized_amount():
    rec = {
        "event_id": "e3", "event_type": "purchase", "user_id": "u1",
        "event_ts": "2026-09-01T00:00:00Z",
        "properties": {"amount": 100, "currency": "EUR"},
    }
    assert enrich_event(rec)["properties"]["normalized_amount_usd"] == 113.0


def test_enrich_without_ua_or_ip_still_complete():
    rec = {
        "event_id": "e4", "event_type": "error", "user_id": "u1",
        "event_ts": "2026-09-01T00:00:00Z",
    }
    out = enrich_event(rec)
    assert out["device_type"] == "other"
    assert out["browser"] == "other"
    assert out["is_bot"] is False
    assert out["geo_country"] == "unknown"
    assert out["event_day"] == "2026-09-01"
    assert "normalized_amount_usd" not in out.get("properties", {})