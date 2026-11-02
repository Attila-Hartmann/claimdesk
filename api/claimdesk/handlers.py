"""AWS Lambda entry points (one container image, two functions): the HTTP API and the SQS worker."""

import json

from mangum import Mangum

from claimdesk import service
from claimdesk.main import app

api = Mangum(app, lifespan="off")


def worker(event: dict, _context: object) -> dict:
    """Process uploaded claims queued by the API; a failure leaves the message for retry, then the dead-letter queue."""
    failures = []
    for rec in event["Records"]:
        try:
            service.process(json.loads(rec["body"])["claim_id"])
        except Exception as e:
            print(f"failed {rec['messageId']}: {e}")
            failures.append({"itemIdentifier": rec["messageId"]})
    return {"batchItemFailures": failures}
