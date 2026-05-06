"""S3 persistence for sim checkpoints.

Layout under the configured bucket:
    persistent-storage/{run_id}/checkpoint-{N}.json   one per phase boundary
    persistent-storage/{run_id}/latest.json           pointer to the highest N written

run_id is a UTC timestamp (YYYY-MM-DDTHH-MM-SSZ) generated in sim.py.
The PREFIX constant is duplicated in view.py — keep them in sync.
"""

import json
import os

import boto3

PREFIX = "persistent-storage/"

_client = None


def s3():
    global _client
    if _client is None:
        endpoint = os.environ.get("S3_ENDPOINT_URL") or None
        _client = boto3.client("s3", endpoint_url=endpoint)
    return _client


def bucket() -> str:
    b = os.environ.get("S3_BUCKET")
    if not b:
        raise RuntimeError("S3_BUCKET env var is required")
    return b


def checkpoint_key(run_id: str, n: int) -> str:
    return f"{PREFIX}{run_id}/checkpoint-{n}.json"


def latest_key(run_id: str) -> str:
    return f"{PREFIX}{run_id}/latest.json"


def write_checkpoint(run_id: str, n: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    s3().put_object(
        Bucket=bucket(),
        Key=checkpoint_key(run_id, n),
        Body=body,
        ContentType="application/json",
    )
    pointer = json.dumps({"checkpoint_number": n}).encode("utf-8")
    s3().put_object(
        Bucket=bucket(),
        Key=latest_key(run_id),
        Body=pointer,
        ContentType="application/json",
    )


def load_checkpoint(run_id: str, n: int) -> dict:
    obj = s3().get_object(Bucket=bucket(), Key=checkpoint_key(run_id, n))
    return json.loads(obj["Body"].read())
