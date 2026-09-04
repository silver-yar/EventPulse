"""Tests for the EventPulse ingest stub handler.

Table-driven baseline: validation tests grow here in ST-8, enrichment in ST-11.
"""

import json
from types import SimpleNamespace

import pytest

from src.ingest.app import lambda_handler

TEST_CASES = [
    # event, context
    ({}, SimpleNamespace(aws_request_id="req-1")),
    ({"body": '{"event_type": "page_view"}'}, SimpleNamespace(aws_request_id="req-2")),
    ({}, SimpleNamespace()),  # context without aws_request_id must not blow up
]


@pytest.mark.parametrize(("event", "context"), TEST_CASES)
def test_stub_returns_ok(event, context):
    result = lambda_handler(event, context)

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["status"] == "ok"
    assert "message" in body