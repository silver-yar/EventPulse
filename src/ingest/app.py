"""EventPulse ingest handler.

Writes one gzipped JSON line per event to events/YYYY/MM/DD/ in the events
bucket (Tier A). Field-level validation (ST-8): missing/bad fields rejected
with structured 400s. Event timestamp defaults to now if absent; partition
comes from the ISO event_ts. Enrichment in ST-11, idempotency in ST-12.
"""

import datetime
import gzip
import json
import logging
import os
import uuid

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Allowed event_type values; analytics dimensions stay clean (ST-8).
EVENT_TYPES = {"page_view", "add_to_cart", "purchase", "error"}


def validate_event(record: dict) -> dict:
    """Collect field-level problems; empty dict means the record is valid."""
    errors: dict = {}

    def problem(field: str, message: str) -> None:
        errors.setdefault(field, []).append(message)

    event_id = record.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        problem("event_id", "must be a non-empty string")

    if record.get("event_type") not in EVENT_TYPES:
        problem("event_type", f"must be one of {sorted(EVENT_TYPES)}")

    event_ts = record.get("event_ts")
    if event_ts is not None:
        if not isinstance(event_ts, str):
            problem("event_ts", "must be a string")
        else:
            try:
                datetime.datetime.fromisoformat(event_ts)
            except ValueError:
                problem("event_ts", "must be an ISO-8601 timestamp")

    user_id = record.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        problem("user_id", "must be a non-empty string")

    session_id = record.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        problem("session_id", "must be a string")

    properties = record.get("properties")
    if properties is not None and not isinstance(properties, dict):
        problem("properties", "must be an object")

    return errors


def _bucket() -> str:
    # Read per call: keeps imports side-effect free for tests/CI collection.
    return os.environ["EVENTS_BUCKET"]


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    raw = event.get("body")
    try:
        record = raw if isinstance(raw, dict) else json.loads(raw or "")
        if not isinstance(record, dict):
            raise ValueError("body must be a JSON object")
    except (TypeError, ValueError, json.JSONDecodeError):
        return _response(400, {"error": "invalid_json"})

    errors = validate_event(record)
    if errors:
        logger.warning(
            json.dumps(
                {
                    "message": "event rejected",
                    "event_id": record.get("event_id"),
                    "errors": errors,
                    "request_id": getattr(context, "aws_request_id", None),
                }
            )
        )
        return _response(400, {"error": "validation_failed", "details": errors})

    record.setdefault("event_ts", _utc_now().isoformat())

    # events/YYYY/MM/DD/<uuid>.json.gz — partition derived from ISO event_ts.
    key = (
        f"events/{record['event_ts'][0:4]}/{record['event_ts'][5:7]}/"
        f"{record['event_ts'][8:10]}/{uuid.uuid4()}.json.gz"
    )
    body = gzip.compress((json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8"))

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=_bucket(),
        Key=key,
        Body=body,
        ContentType="application/json",
        ContentEncoding="gzip",
    )

    logger.info(
        json.dumps(
            {
                "message": "event stored",
                "event_id": record.get("event_id"),
                "key": key,
                "size_bytes": len(body),
            }
        )
    )
    return _response(200, {"status": "ok", "key": key})