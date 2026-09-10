"""Tests for the EventPulse ingest handler (Tier A S3 writer, ST-7)."""

import gzip
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from unittest.mock import Mock, patch

from src.ingest.app import lambda_handler

BUCKET = "eventpulse-events-us-east-1-123456789012-dev"

SAMPLE_EVENT = json.dumps(
    {
        "event_id": "evt-1",
        "event_type": "page_view",
        "user_id": "u_1",
        "session_id": "s_1",
        "event_ts": "2026-09-04T12:00:00Z",
        "properties": {"url": "/products/42"},
    }
)


def make_event(body):
    return {"body": json.dumps(body) if not isinstance(body, str) else body}


@contextmanager
def captured_put():
    """Yield a fake S3 client while the handler's boto3.client is patched."""
    fake = Mock()
    with patch("src.ingest.app.boto3.client", return_value=fake):
        yield fake


@pytest.fixture(autouse=True)
def bucket_env(monkeypatch):
    monkeypatch.setenv("EVENTS_BUCKET", BUCKET)


def test_valid_event_lands_gzip_object_under_date_prefix():
    with captured_put() as fake:
        result = lambda_handler({"body": SAMPLE_EVENT}, SimpleNamespace())

        assert result["statusCode"] == 200
        put = fake.put_object
        put.assert_called_once()
        kwargs = put.call_args.kwargs
        assert kwargs["Bucket"] == BUCKET
        assert kwargs["Key"].startswith("events/2026/09/04/") and kwargs["Key"].endswith(".json.gz")
        assert kwargs["ContentEncoding"] == "gzip"
        # decompressed content is the original event, one JSON line
        stored = json.loads(gzip.decompress(kwargs["Body"]).decode("utf-8"))
        assert stored == json.loads(SAMPLE_EVENT)


def test_missing_event_ts_is_set_to_now():
    with captured_put() as fake:
        result = lambda_handler(make_event({"event_id": "evt-2"}), SimpleNamespace())

        assert result["statusCode"] == 200
        key = fake.put_object.call_args.kwargs["Key"]
        stored = json.loads(
            gzip.decompress(fake.put_object.call_args.kwargs["Body"]).decode("utf-8")
        )
        assert key.startswith(
            f"events/{stored['event_ts'][0:4]}/{stored['event_ts'][5:7]}/{stored['event_ts'][8:10]}/"
        )
        assert stored["event_id"] == "evt-2"
        assert stored["event_ts"]


def test_invalid_json_returns_400_and_writes_nothing():
    with captured_put() as fake:
        for bad in ("not json{", "[]"):
            result = lambda_handler({"body": bad}, SimpleNamespace())
            assert result["statusCode"] == 400, bad
        fake.put_object.assert_not_called()