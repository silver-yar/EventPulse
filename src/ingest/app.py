"""EventPulse ingest handler (stub).

Real logic lands incrementally: request validation in ST-8, enrichment in
ST-11, idempotency in ST-12, S3/Firehose writes in ST-7/ST-15.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    logger.info(
        json.dumps(
            {
                "message": "stub invoked",
                "request_id": getattr(context, "aws_request_id", None),
            }
        )
    )
    return {
        "statusCode": 200,
        "body": json.dumps({"status": "ok", "message": "EventPulse ingest stub"}),
    }