"""EventPulse event enrichment (ST-11).

Pure functions that decorate a validated event record with derived analytics
fields. Deliberately dependency-free (stdlib only):

- user-agent -> device_type / browser / is_bot via explainable keyword rules
- client IP -> geo_country via a deterministic stub mapping (ponytail: swap
  for real GeoIP by replacing geo_country(); pipeline is unaffected)
- event_day derived from the ISO event_ts
- currency -> normalized_amount_usd via a demo-grade static rate table
  (ponytail: static approximate rates; production journal an FX feed)
"""

import hashlib
import logging

logger = logging.getLogger(__name__)

# --------------------------------------------------------------- user agent

BOT_TOKENS = (
    "googlebot", "bingbot", "curl", "wget", "python-urllib", "headless",
    "bot/", "crawler", "slurp", "spider",
)
MOBILE_TOKENS = ("iphone", "android", "mobile", "windows phone")
TABLET_TOKENS = ("ipad", "tablet", "kindle")
DESKTOP_TOKENS = ("mac os x", "windows nt", "linux", "x11")

BROWSER_RULES = (
    ("edge", "edg/"),
    ("opera", "opr/"),
    ("chrome", "chrome/"),
    ("firefox", "firefox/"),
    ("curl", "curl/"),
    ("safari", "safari/"),
)


def classify_ua(user_agent):
    """Return (device_type, browser, is_bot). Absent UA -> ('other', 'other', False)."""
    ua = (user_agent or "").lower()
    if not ua:
        return "other", "other", False
    is_bot = any(token in ua for token in BOT_TOKENS)
    if any(token in ua for token in TABLET_TOKENS):
        device = "tablet"
    elif any(token in ua for token in MOBILE_TOKENS):
        device = "mobile"
    elif any(token in ua for token in DESKTOP_TOKENS):
        device = "desktop"
    else:
        device = "other"
    browser = next((name for name, token in BROWSER_RULES if token in ua), "other")
    return device, browser, is_bot


# ----------------------------------------------------------------- geo stub

# Approximate distribution of countries for the deterministic stub.
COUNTRIES = (
    "US", "GB", "DE", "FR", "NL", "SE", "IN", "BR", "JP", "CA",
    "AU", "ES", "IT", "PL", "MX", "KR", "SG", "NZ", "ZA", "AE",
)


def geo_country(client_ip):
    """Deterministic stub: hash ip -> ISO code. Missing ip -> 'unknown'."""
    if not client_ip:
        return "unknown"
    digest = int(hashlib.md5(client_ip.encode(), usedforsecurity=False).hexdigest(), 16)
    return COUNTRIES[digest % len(COUNTRIES)]


# -------------------------------------------------------------- event day

def derive_event_day(event_ts: str) -> str:
    """YYYY-MM-DD from a validated ISO-8601 timestamp."""
    return event_ts[:10]


# ---------------------------------------------------------------- currency

# Approximate USD per 1 unit. Demo-grade, not live FX.
CURRENCY_RATES = {"EUR": 1.13, "GBP": 1.27, "JPY": 0.0067, "CAD": 0.73, "AUD": 0.65}


def normalize_currency(properties):
    """Return normalized_amount_usd or None.

    amount_usd present -> same value (already normalized).
    amount + currency present -> amount * rate(currency), rounded to 2.
    Unknown currency or missing amount -> None.
    """
    if not isinstance(properties, dict):
        return None
    if isinstance(properties.get("amount_usd"), (int, float)):
        return round(float(properties["amount_usd"]), 2)
    amount = properties.get("amount")
    currency = properties.get("currency")
    if isinstance(amount, (int, float)) and isinstance(currency, str):
        rate = CURRENCY_RATES.get(currency.upper())
        if rate:
            return round(float(amount) * rate, 2)
        logger.warning("unknown currency for normalization: %s", currency)
    return None


# ------------------------------------------------------------------ enrich

def enrich_event(record: dict, remote_ip: str | None = None) -> dict:
    """Add derived analytics fields to a validated event (in place, returns it)."""
    device, browser, is_bot = classify_ua(record.get("user_agent"))
    record["device_type"] = device
    record["browser"] = browser
    record["is_bot"] = is_bot
    # Payload client_ip wins; API Gateway X-Forwarded-For is the fallback.
    record["geo_country"] = geo_country(record.get("client_ip") or remote_ip)
    record["event_day"] = derive_event_day(record["event_ts"])
    normalized = normalize_currency(record.get("properties"))
    if normalized is not None:
        record.setdefault("properties", {})["normalized_amount_usd"] = normalized
    return record