# Guide: persistent storage on tinfoil

End-to-end walkthrough — clone, run locally, then deploy the same code into a Tinfoil enclave so it survives container restarts via S3.

The workload is a 4-phase mock random walk that checkpoints to S3 at every phase boundary. Restartable from any checkpoint. Trajectory is renderable from the checkpoints. Same docker image runs locally and on Tinfoil.

## 0. what you'll need

- an AWS account + a bucket
- a tinfoil org with the **containers** product enabled
- `docker`, `aws`, `tinfoil`, `gh` clis on your laptop
- python 3.10+

## 1. set up s3

Make a bucket and an IAM user scoped to it.

```bash
export BUCKET=my-tinfoil-sim-bucket   # whatever
export AWS_REGION=us-east-2
aws s3 mb s3://$BUCKET --region $AWS_REGION
```

In the AWS console: **IAM → Users → Create user** (no console access). Attach `AmazonS3FullAccess` for the demo (or scope to just this bucket if you want — the README has the policy json). Open the user → **Security credentials → Create access key → CLI**. Save the access key + secret somewhere safe — the page only shows them once.

Sanity check:
```bash
aws configure   # paste access key + secret + us-east-2
echo hi | aws s3 cp - s3://$BUCKET/_smoke && aws s3 cp s3://$BUCKET/_smoke - && aws s3 rm s3://$BUCKET/_smoke
# should print "hi"
```

## 2. configure .env

```bash
cp .env.example .env
$EDITOR .env       # paste your bucket, region, keys
```

`.env` is gitignored. Don't commit it.

## 3. run it locally in docker

```bash
docker build -t sim .
docker run --rm -p 8080:8080 --env-file .env sim
```

First log line: `started fresh run_id=2026-05-06T...Z`. Container will run for ~3:20 (4 phases × 2,500 steps × 20ms/step), writing one checkpoint per phase to s3.

## 4. watch the progress bar

In another terminal:

```bash
pip install -r requirements.txt
python status.py
```

You'll see a colored per-phase progress bar:

```
== Starting Mock ML ==
Storing in 2026-05-06T...Z

Phase 1: explore
[████████████████████] 100% (2500/2500)
✓ Completed phase explore. Saved to 2026-05-06T...Z/checkpoint-1.json

Phase 2: drift
[████████░░░░░░░░░░░░] 42% (1041/2500)
...
```

`status.py` exits when the sim reports `done`. The container then auto-exits ~5 seconds later (`--rm` removes it).

## 5. view the trajectory

List runs in s3:
```bash
python view.py --bucket $BUCKET
# table of run_ids + checkpoint counts
```

Plot the most recent:
```bash
python view.py --bucket $BUCKET --latest
open trajectory.png
```

You'll see four visibly distinct regimes — explore (wide noise cloud), drift (linear), converge (pulled to origin), oscillate (loops).

## 6. try a resume

Kick off a new run, kill it after a couple checkpoints, then resume:

```bash
docker run --rm -p 8080:8080 --env-file .env sim
# wait until checkpoint 2 lands, then Ctrl+C
# copy the run_id from the logs
```

Resume from checkpoint 2 — it'll run only phases 3 and 4:

```bash
docker run --rm -p 8080:8080 --env-file .env sim --resume-from <run_id>:2
```

The rng state is restored from the checkpoint, so the resumed run is byte-identical to what an uninterrupted run would have produced. Verify with `view.py` — same trajectory.

## 7. deploy to a tinfoil container

Now run the same image inside an enclave.

```bash
tinfoil login
tinfoil whoami    # confirm

# push your aws creds as org secrets — names must match tinfoil-config.yml
printf '%s' "$AWS_ACCESS_KEY_ID"     | tinfoil secret create AWS_ACCESS_KEY_ID --value-file -
printf '%s' "$AWS_SECRET_ACCESS_KEY" | tinfoil secret create AWS_SECRET_ACCESS_KEY --value-file -

# edit tinfoil-config.yml — set your bucket + region in the env: block
git commit -am "tinfoil-config: set bucket"

# tag a release — this triggers two github actions:
#   tinfoil-build.yml   — builds image, pushes to ghcr, pins digest, creates the tag
#   tinfoil-release.yml — measures the image and publishes attestation
gh workflow run tinfoil-build.yml -f version=v0.1.0 --ref $(git branch --show-current)
gh run watch  # wait for both jobs to go green

git pull   # fetch the digest-pin commit the action pushed
```

Create the container:
```bash
tinfoil container create persistent-storage-sim \
  --repo <owner>/<repo> \
  --tag v0.1.0 \
  --secret AWS_ACCESS_KEY_ID \
  --secret AWS_SECRET_ACCESS_KEY
```

Wait for it to come up:
```bash
tinfoil container get persistent-storage-sim
# Status: deploying  →  active   (a few minutes)
```

## 8. watch the enclave run

The CVM starts the container immediately, so by the time it's `active` the sim is already running.

```bash
DOMAIN=persistent-storage-sim.tinfoil.containers.tinfoil.dev
curl -s https://$DOMAIN/status | jq
python status.py --url https://$DOMAIN/status
```

After the bar finishes, the in-enclave sim exits, the container stops. The s3 data persists — that's the point.

## 9. plot the enclave's trajectory

Same view.py, no changes:
```bash
python view.py --bucket $BUCKET --latest
open trajectory.png
```

The trajectory is identical to a local run with the same seed — no enclave-specific behavior.

## 10. resume an enclave run

There's no `docker run` to append `--resume-from` to. You set it in `tinfoil-config.yml` and redeploy:

```yaml
containers:
  - name: "sim"
    image: "..."
    command: ["--resume-from", "2026-05-06T05-17-19Z:2"]
```

```bash
git commit -am "resume from ckpt 2"
gh workflow run tinfoil-build.yml -f version=v0.1.1 --ref $(git branch --show-current)
gh run watch
git pull
tinfoil container relaunch persistent-storage-sim --tag v0.1.1
```

## 11. cleanup

```bash
tinfoil container stop   persistent-storage-sim   # pauses, keeps state
tinfoil container delete persistent-storage-sim   # destroys
aws s3 rm --recursive s3://$BUCKET/persistent-storage/   # nuke runs
```

Done. Same code, same checkpoints, same plots — just running in an attestable enclave instead of your laptop.
