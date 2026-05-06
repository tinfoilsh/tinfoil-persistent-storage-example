"""View a sim run by pulling its checkpoints from S3 and plotting the trajectory.

Usage:
    python view.py --bucket my-bucket --run-id <uuid> [--output trajectory.png]

AWS credentials are picked up from the standard boto3 chain (env vars,
~/.aws/credentials, etc). For S3-compatible endpoints (R2, Tigris, MinIO),
set S3_ENDPOINT_URL.
"""

import argparse
import json
import os
import sys

import boto3
import matplotlib.pyplot as plt

PHASE_COLORS = {
    "explore": "#4C72B0",
    "drift": "#DD8452",
    "converge": "#55A467",
    "oscillate": "#C44E52",
}


def s3_client():
    endpoint = os.environ.get("S3_ENDPOINT_URL") or None
    return boto3.client("s3", endpoint_url=endpoint)


def list_checkpoint_numbers(client, bucket: str, run_id: str) -> list[int]:
    paginator = client.get_paginator("list_objects_v2")
    nums = []
    prefix = f"{run_id}/checkpoint-"
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            try:
                n = int(key.rsplit("checkpoint-", 1)[1].split(".json")[0])
                nums.append(n)
            except (ValueError, IndexError):
                continue
    return sorted(nums)


def load_checkpoint(client, bucket: str, run_id: str, n: int) -> dict:
    obj = client.get_object(Bucket=bucket, Key=f"{run_id}/checkpoint-{n}.json")
    return json.loads(obj["Body"].read())


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot a sim run's trajectory from S3.")
    parser.add_argument("--bucket", required=True, help="S3 bucket containing the run")
    parser.add_argument(
        "--run-id", required=True, help="run_id (top-level prefix in the bucket)"
    )
    parser.add_argument("--output", default="trajectory.png", help="output PNG path")
    args = parser.parse_args()

    client = s3_client()
    nums = list_checkpoint_numbers(client, args.bucket, args.run_id)
    if not nums:
        print(
            f"no checkpoints found under {args.bucket}/{args.run_id}/", file=sys.stderr
        )
        return 1
    print(f"found {len(nums)} checkpoint(s): {nums}")

    fig, ax = plt.subplots(figsize=(9, 9))
    seen_phases = set()
    total_points = 0

    for n in nums:
        ckpt = load_checkpoint(client, args.bucket, args.run_id, n)
        phase = ckpt["phase_completed"]
        traj = ckpt["trajectory"]
        if not traj:
            continue
        xs = [row[1] for row in traj]
        ys = [row[2] for row in traj]
        color = PHASE_COLORS.get(phase, "#888888")
        label = phase if phase not in seen_phases else None
        seen_phases.add(phase)
        ax.plot(xs, ys, color=color, linewidth=0.6, alpha=0.85, label=label)
        total_points += len(traj)

    ax.scatter([0], [0], color="black", s=30, zorder=3, label="origin")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(
        f"run_id={args.run_id}\n{total_points} steps across {len(nums)} checkpoint(s)"
    )
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(args.output, dpi=140)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
