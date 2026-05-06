# Simple persistent storage example

Tinfoil containers are ephemeral.

simple s3 storage.

# Quick start

Mock sim runs a multi-phase random walk for funsies

run sim docker

watch progress w/ status

when it's done, use view

# OLD === TODO: clean up

## Want to show a few different implementations:

1. Simple s3 storage
2. Encrypted storage with tinfoil buckets (beta)
3. Custom s3 storage w/ custom encryption - more work but can be very specific about how you want to store things. Recommended for anything more than blobs (or if tinfoil buckets isn't working)

## Use case

Spin up a container, run some mock evals/code, can be a math calculator or something. Periodically get results & update the container with them. Can do append only or can do overwriting, shouldn't actually matter.

So we'll have a container folder. This will have some sort of long running code function, maybe a random walk simulator, then we can store results from it periodically. We'll also have a script to view how it's stored? or at least a script at the end to look at the data.

We'll want to be able to restart the container from a checkpoint. Some sort of arg like 'try and restartr from step 3'.

This is goig to serve as an example for some model training like stuff, so we can make the mock more similar to this (but random & have graphs eg walking - but have distinct phases)

We'll write everything in python.

## Where we are now

Built the simple s3 version. The mock is a 2D random walk with 4 phases (explore -> drift -> converge -> oscillate), each with different dynamics so the trajectory has visible regime shifts when plotted. End of each phase = one checkpoint written to s3.

```
container/
  sim.py           random walk + checkpointing loop
  storage.py       boto3 wrapper (write/load/list)
  server.py        /health + /status (so you can poke at a running sim)
  requirements.txt
view.py            local script — pulls all checkpoints from s3, plots trajectory.png
Dockerfile         python:3.13-slim, runs sim.py
tinfoil-config.yml cpus 2 / mem 8192, AWS creds as secrets, exposes /health + /status
```

Checkpoints land at `s3://$S3_BUCKET/persistent-storage/{run_id}/checkpoint-{N}.json` plus a `latest.json` pointer. `run_id` is a UTC timestamp (`YYYY-MM-DDTHH-MM-SSZ`). Each checkpoint stores the run_id, phase completed, step count, current position, the numpy rng state, and the trajectory points from that phase.

To resume: pass `--resume-from RUN_ID:N` as a CLI arg. Sim loads checkpoint N, restores rng state, and picks up at the start of phase N+1. Because the rng is restored, the resumed run is identical to the original — handy for verifying nothing got corrupted.

```bash
docker run --rm -p 8080:8080 --env-file .env sim --resume-from 2026-05-06T04-43-46Z:2
```

Next: wire up the tinfoil-buckets backend, then the custom-encryption one. Both will reuse `sim.py` and just swap out `storage.py`.

## Run it locally

Takes ~3 min with the default `STEP_DELAY_MS=20` pacing (set to 0 in `.env` to flat-out finish in seconds).

1. `cp .env.example .env` and fill in your AWS keys + bucket name.
2. Build the image — `docker build -t sim .`
3. Run it — `docker run --rm -p 8080:8080 --env-file .env sim`. First log line prints the `run_id` — copy it.
4. In another terminal, watch live progress — `python status.py`. Exits when sim is done.
5. Plot the trajectory — `pip install -r requirements.txt && python view.py --bucket $S3_BUCKET --run-id <run_id>`. Writes `trajectory.png`.

To resume from a checkpoint instead of starting fresh: uncomment `RUN_ID=<previous>` and `RESUME_FROM_CHECKPOINT=2` in `.env`, run step 3 again. You'll see `resumed run_id=... next phase=converge`.

## Check s3 works

Fill in `.env` (copy from `.env.example`) and run a round-trip — should print `hi`.

```bash
set -a && source .env && set +a
echo hi | aws s3 cp - s3://$S3_BUCKET/_smoke && aws s3 cp s3://$S3_BUCKET/_smoke - && aws s3 rm s3://$S3_BUCKET/_smoke
```

If that errors, your creds, region, or bucket name are off. Fix that before running the container.
