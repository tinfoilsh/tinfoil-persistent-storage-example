"""S3 persistence for sim checkpoints.

Layout under the configured bucket:
    persistent-storage/{run_id}/checkpoint-{N}.json   per phase: rng + traj + meta
    persistent-storage/{run_id}/phase-{N}.bin         per phase: streamed activations
    persistent-storage/{run_id}/latest.json           pointer to the highest N written

Each phase produces one JSON checkpoint (small, single PUT) AND one .bin object
(large, streamed via multipart upload as the sim runs).

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


def phase_blob_key(run_id: str, n: int) -> str:
    return f"{PREFIX}{run_id}/phase-{n}.bin"


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


def start_multipart(key: str, content_type: str = "application/octet-stream") -> str:
    resp = s3().create_multipart_upload(
        Bucket=bucket(), Key=key, ContentType=content_type
    )
    return resp["UploadId"]


def upload_part(key: str, upload_id: str, part_number: int, body: bytes) -> dict:
    resp = s3().upload_part(
        Bucket=bucket(),
        Key=key,
        UploadId=upload_id,
        PartNumber=part_number,
        Body=body,
    )
    return {"PartNumber": part_number, "ETag": resp["ETag"]}


def complete_multipart(key: str, upload_id: str, parts: list[dict]) -> None:
    s3().complete_multipart_upload(
        Bucket=bucket(),
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )


def abort_multipart(key: str, upload_id: str) -> None:
    s3().abort_multipart_upload(Bucket=bucket(), Key=key, UploadId=upload_id)
