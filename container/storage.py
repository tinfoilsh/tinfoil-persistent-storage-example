"""S3 persistence for sim checkpoints.

Layout under the configured bucket:
    {run_id}/checkpoint-{N}.json   one per phase boundary
    {run_id}/latest.json           pointer to the highest N written
"""

import json
import os

import boto3

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
    return f"{run_id}/checkpoint-{n}.json"


def latest_key(run_id: str) -> str:
    return f"{run_id}/latest.json"


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


def list_checkpoints(run_id: str) -> list[int]:
    paginator = s3().get_paginator("list_objects_v2")
    nums = []
    prefix = f"{run_id}/checkpoint-"
    for page in paginator.paginate(Bucket=bucket(), Prefix=prefix):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            try:
                n = int(key.rsplit("checkpoint-", 1)[1].split(".json")[0])
                nums.append(n)
            except (ValueError, IndexError):
                continue
    return sorted(nums)
