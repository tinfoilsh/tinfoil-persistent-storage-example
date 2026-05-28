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

import boto3
from botocore.config import Config

PREFIX = "persistent-storage/"

SIDECAR_ENDPOINT = "http://localhost:9000"

# placeholder — sidecar ignores this
BUCKET = "mock"

_client = None


def s3():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=SIDECAR_ENDPOINT,
            region_name="us-east-2",
            config=Config(s3={"addressing_style": "path"}),
            aws_access_key_id="tinfoil-sidecar",
            aws_secret_access_key="tinfoil-sidecar",
        )
    return _client


def checkpoint_key(run_id: str, n: int) -> str:
    return f"{PREFIX}{run_id}/checkpoint-{n}.json"


def phase_blob_key(run_id: str, n: int) -> str:
    return f"{PREFIX}{run_id}/phase-{n}.bin"


def latest_key(run_id: str) -> str:
    return f"{PREFIX}{run_id}/latest.json"


def write_checkpoint(run_id: str, n: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    s3().put_object(
        Bucket=BUCKET,
        Key=checkpoint_key(run_id, n),
        Body=body,
        ContentType="application/json",
    )
    pointer = json.dumps({"checkpoint_number": n}).encode("utf-8")
    s3().put_object(
        Bucket=BUCKET,
        Key=latest_key(run_id),
        Body=pointer,
        ContentType="application/json",
    )


def load_checkpoint(run_id: str, n: int) -> dict:
    obj = s3().get_object(Bucket=BUCKET, Key=checkpoint_key(run_id, n))
    return json.loads(obj["Body"].read())


def start_multipart(key: str, content_type: str = "application/octet-stream") -> str:
    resp = s3().create_multipart_upload(
        Bucket=BUCKET, Key=key, ContentType=content_type
    )
    return resp["UploadId"]


def upload_part(key: str, upload_id: str, part_number: int, body: bytes) -> dict:
    resp = s3().upload_part(
        Bucket=BUCKET,
        Key=key,
        UploadId=upload_id,
        PartNumber=part_number,
        Body=body,
    )
    return {"PartNumber": part_number, "ETag": resp["ETag"]}


def complete_multipart(key: str, upload_id: str, parts: list[dict]) -> None:
    s3().complete_multipart_upload(
        Bucket=BUCKET,
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": parts},
    )


def abort_multipart(key: str, upload_id: str) -> None:
    s3().abort_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload_id)
