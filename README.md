# Simple persistent storage example

Tinfoil containers are ephemeral. This example shows how to checkpoint long-running work to S3 so a Tinfoil-deployed container can be restarted from a known point.

The workload is a mock 4-phase random walk (explore → drift → converge → oscillate) that writes a checkpoint to S3 at every phase boundary. Restartable from any checkpoint.

## Quick start

Follow **[guide.md](./guide.md)** for the full walkthrough — aws setup, tinfoil secrets, tag, deploy.

The short version (assuming aws + tinfoil are already set up):

1. Edit `tinfoil-config.yml` — set `S3_BUCKET` and `AWS_REGION`.
2. Push aws creds to your tinfoil org once — `tinfoil secret create AWS_ACCESS_KEY_ID --value-file -` and same for the secret key.
3. Tag a release — `gh workflow run tinfoil-build.yml -f version=v0.1.0 --ref $(git branch --show-current)`. Wait for the actions, then `git pull`.
4. Create the container — `tinfoil container create persistent-storage-sim --repo <owner>/<repo> --tag v0.1.0 --secret AWS_ACCESS_KEY_ID --secret AWS_SECRET_ACCESS_KEY`.
5. Watch — `python status.py --url https://<domain>/status`.
6. Plot — `python view.py --bucket $S3_BUCKET --latest`.

## Layout

```
container/
  sim.py           random walk + checkpointing loop
  storage.py       boto3 wrapper (write/load)
  server.py        /health + /status
  requirements.txt
view.py            local — pulls all checkpoints from s3, plots trajectory.png
status.py          local — colored per-phase progress bar
Dockerfile         python:3.13-slim — built by the tinfoil-build.yml github action
tinfoil-config.yml cpus 2 / mem 8192, AWS creds as secrets, exposes /health + /status
guide.md           full walkthrough
```

Checkpoints land at `s3://$S3_BUCKET/persistent-storage/{run_id}/checkpoint-{N}.json` plus a `latest.json` pointer. `run_id` is a UTC timestamp (`YYYY-MM-DDTHH-MM-SSZ`).

To resume: set `command: ["--resume-from", "<run_id>:N"]` in `tinfoil-config.yml`, tag a new release, then `tinfoil container relaunch ... --tag v0.1.1`. Sim loads checkpoint N, restores the numpy rng state, and picks up at the start of phase N+1. Because the rng is restored, the resumed run is byte-identical to an uninterrupted one.

## Check s3 works

`.env` (copy from `.env.example`) is handy throughout — sourcing it gives you `$S3_BUCKET`, `$AWS_REGION`, and your aws creds. Useful for both the aws CLI and for `tinfoil secret create` later.

```bash
cp .env.example .env
$EDITOR .env
set -a && source .env && set +a

# round-trip should print `hi`
echo hi | aws s3 cp - s3://$S3_BUCKET/_smoke && aws s3 cp s3://$S3_BUCKET/_smoke - && aws s3 rm s3://$S3_BUCKET/_smoke
```

If that errors, your aws creds or bucket name are off. Fix that before deploying.

## Future work

Currently this example uses a simple S3 storage.

There are two more possible options if the storage needs to be encrypted:

1. **Tinfoil buckets** (beta) — manages the encryption for you. [github](https://github.com/tinfoilsh/tinfoil-buckets)
2. **Custom s3 + caller-owned encryption** — more work, but specific control over how things are stored
