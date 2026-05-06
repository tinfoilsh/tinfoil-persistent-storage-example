"""View runs stored under persistent-storage/ in the S3 bucket.

Two modes:
    python view.py --bucket <bucket>                    list all runs
    python view.py --bucket <bucket> --run-id <ts>      plot one run's trajectory
    python view.py --bucket <bucket> --latest           plot the most recent run

Credentials come from the standard boto3 chain (env, ~/.aws/credentials).
PREFIX must stay in sync with container/storage.py.
"""

import argparse
import json
import os
import sys

import boto3
import matplotlib.pyplot as plt
from rich.console import Console
from rich.table import Table

PREFIX = "persistent-storage/"

PHASE_COLORS = {
    "explore": "#4C72B0",
    "drift": "#DD8452",
    "converge": "#55A467",
    "oscillate": "#C44E52",
}

console = Console()


def s3_client():
    endpoint = os.environ.get("S3_ENDPOINT_URL") or None
    return boto3.client("s3", endpoint_url=endpoint)


def list_runs(client, bucket: str) -> list[dict]:
    """Return [{"run_id", "checkpoints": [int...]}, ...] sorted by run_id ascending."""
    paginator = client.get_paginator("list_objects_v2")
    runs: dict[str, list[int]] = {}
    for page in paginator.paginate(Bucket=bucket, Prefix=PREFIX):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            rest = key[len(PREFIX):]
            parts = rest.split("/", 1)
            if len(parts) != 2:
                continue
            run_id, fname = parts
            if not fname.startswith("checkpoint-"):
                continue
            try:
                n = int(fname[len("checkpoint-"):].split(".json")[0])
            except ValueError:
                continue
            runs.setdefault(run_id, []).append(n)
    return [
        {"run_id": rid, "checkpoints": sorted(ns)}
        for rid, ns in sorted(runs.items())
    ]


def load_checkpoint(client, bucket: str, run_id: str, n: int) -> dict:
    obj = client.get_object(Bucket=bucket, Key=f"{PREFIX}{run_id}/checkpoint-{n}.json")
    return json.loads(obj["Body"].read())


def render_listing(runs: list[dict]) -> None:
    if not runs:
        console.print(f"[yellow]no runs found under {PREFIX}[/]")
        return
    table = Table(title="Runs", title_style="bold cyan", header_style="bold magenta")
    table.add_column("run_id", style="yellow")
    table.add_column("checkpoints", justify="right", style="green")
    table.add_column("checkpoint numbers", style="dim")
    for r in runs:
        ns = r["checkpoints"]
        table.add_row(r["run_id"], str(len(ns)), ", ".join(str(n) for n in ns))
    console.print(table)
    console.print(
        f"\nTo plot one: [cyan]python view.py --bucket <bucket> --run-id <run_id>[/]"
    )
    console.print(
        f"Or for the latest: [cyan]python view.py --bucket <bucket> --latest[/]"
    )


def plot_run(client, bucket: str, run_id: str, output: str) -> int:
    nums = sorted(
        set(
            n
            for r in list_runs(client, bucket)
            if r["run_id"] == run_id
            for n in r["checkpoints"]
        )
    )
    if not nums:
        console.print(
            f"[red]no checkpoints found under {PREFIX}{run_id}/[/]", style="red"
        )
        return 1
    console.print(f"found [green]{len(nums)}[/] checkpoint(s) for [yellow]{run_id}[/]")

    fig, ax = plt.subplots(figsize=(9, 9))
    seen_phases = set()
    total_points = 0
    for n in nums:
        ckpt = load_checkpoint(client, bucket, run_id, n)
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
    ax.set_title(f"run_id={run_id}\n{total_points} steps across {len(nums)} checkpoint(s)")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output, dpi=140)
    console.print(f"[bold green]wrote {output}[/]")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List or plot runs stored under persistent-storage/ in S3."
    )
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--latest", action="store_true", help="plot the most recent run"
    )
    parser.add_argument("--output", default="trajectory.png")
    args = parser.parse_args()

    client = s3_client()

    if args.run_id and args.latest:
        console.print("[red]--run-id and --latest are mutually exclusive[/]")
        return 2

    if args.latest:
        runs = list_runs(client, args.bucket)
        if not runs:
            console.print(f"[red]no runs found under {PREFIX}[/]")
            return 1
        run_id = runs[-1]["run_id"]
        console.print(f"[dim]latest run: {run_id}[/]")
        return plot_run(client, args.bucket, run_id, args.output)

    if args.run_id:
        return plot_run(client, args.bucket, args.run_id, args.output)

    # default: list mode
    runs = list_runs(client, args.bucket)
    render_listing(runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
