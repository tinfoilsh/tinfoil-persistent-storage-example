# Simple persistent storage example

Tinfoil containers are ephemeral. This example shows how to checkpoint long-running work to S3

The workload is a mock 4-phase random walk (explore → drift → converge → oscillate) that writes a checkpoint to S3 at every phase boundary. Restartable from any checkpoint.

## Quick start

Follow **[guide.md](./guide.md)** for the full walkthrough — aws setup, local docker run, then deploying the same image to a Tinfoil enclave.

The short version:

1. `cp .env.example .env` and fill in your AWS keys + bucket name.
2. `docker build -t sim . && docker run --rm -p 8080:8080 --env-file .env sim`
3. `python status.py` in another terminal — colored per-phase progress bar.
4. `python view.py --bucket $S3_BUCKET --latest` once it's done — writes `trajectory.png`.

## Layout

```
container/
  sim.py           random walk + checkpointing loop
  storage.py       boto3 wrapper (write/load)
  server.py        /health + /status
  requirements.txt
view.py            local — pulls all checkpoints from s3, plots trajectory.png
status.py          local — colored per-phase progress bar
Dockerfile         python:3.13-slim, runs sim.py
tinfoil-config.yml cpus 2 / mem 8192, AWS creds as secrets, exposes /health + /status
guide.md           full walkthrough (local docker → tinfoil deploy)
```

Checkpoints land at `s3://$S3_BUCKET/persistent-storage/{run_id}/checkpoint-{N}.json` plus a `latest.json` pointer. `run_id` is a UTC timestamp (`YYYY-MM-DDTHH-MM-SSZ`).

To resume: pass `--resume-from RUN_ID:N` as a CLI arg. Sim loads checkpoint N, restores the numpy rng state, and picks up at the start of phase N+1. Because the rng is restored, the resumed run is byte-identical to an uninterrupted one.

```bash
docker run --rm -p 8080:8080 --env-file .env sim --resume-from 2026-05-06T04-43-46Z:2
```

## Check s3 works

Fill in `.env` (copy from `.env.example`) and run a round-trip — should print `hi`.

```bash
set -a && source .env && set +a
echo hi | aws s3 cp - s3://$S3_BUCKET/_smoke && aws s3 cp s3://$S3_BUCKET/_smoke - && aws s3 rm s3://$S3_BUCKET/_smoke
```

If that errors, your creds, region, or bucket name are off. Fix that before running the container.

## Future work

Currently this example uses a simple S3 storage.

There are two more possible options if the storage needs to be encrypted:

1. **Tinfoil buckets** (beta) — manages the encryption for you. [github](https://github.com/tinfoilsh/tinfoil-buckets)
2. **Custom s3 + caller-owned encryption** — more work, but specific control over how things are stored
