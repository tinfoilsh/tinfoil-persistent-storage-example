# Guide: persistent storage on tinfoil

End-to-end walkthrough — clone, deploy to a Tinfoil enclave, watch it checkpoint to S3 across runs.

The workload is a 4-phase mock random walk that checkpoints to S3 at every phase boundary. Restartable from any checkpoint. Trajectory is renderable from the checkpoints.

## 0. what you'll need

- an AWS account + a bucket
- a tinfoil org with the **containers** product enabled
- an SSH keypair (e.g. `~/.ssh/id_ed25519` — `ssh-keygen -t ed25519` if you don't have one). Used for SSHing into the debug container.
- `aws`, `tinfoil`, `gh`, `openssl` clis on your laptop
- python 3.10+

`.env` (copy from `.env.example`) is handy throughout — drops `$S3_BUCKET`, `$AWS_REGION`, the aws creds, and `$ENCRYPTION_KEY` into your shell so you can paste commands as-is:

```bash
cp .env.example .env
$EDITOR .env
set -a && source .env && set +a
```

## 1. set up s3

Make a bucket and an IAM user scoped to it.

```bash
export S3_BUCKET=my-tinfoil-sim-bucket   # whatever
export AWS_REGION=us-east-2
aws s3 mb s3://$S3_BUCKET --region $AWS_REGION
```

In the AWS console: **IAM → Users → Create user** (no console access). Attach `AmazonS3FullAccess` for the demo. Open the user → **Security credentials → Create access key → CLI**. Save the access key + secret somewhere safe — only shown once.

Sanity check from your laptop:

```bash
aws configure   # paste access key + secret + us-east-2
echo hi | aws s3 cp - s3://$S3_BUCKET/_smoke && aws s3 cp s3://$S3_BUCKET/_smoke - && aws s3 rm s3://$S3_BUCKET/_smoke
# should print "hi"
```

## 2. push secrets + ssh key to tinfoil

The sidecar (next section) needs three secrets: the bucket creds and an AES-256 master key. Generate the key once and put it in `.env` so the sidecar (inside the CVM) and `view.py` (on your laptop) share the same value:

```bash
echo "ENCRYPTION_KEY=$(openssl rand -base64 32)" >> .env
set -a && source .env && set +a
```

Tinfoil injects org-level secrets at boot. Names must match the `secrets:` list in `tinfoil-config.yml`.

```bash
tinfoil login
tinfoil whoami    # confirm

printf '%s' "$AWS_ACCESS_KEY_ID"     | tinfoil secret create AWS_ACCESS_KEY_ID     --value-file -
printf '%s' "$AWS_SECRET_ACCESS_KEY" | tinfoil secret create AWS_SECRET_ACCESS_KEY --value-file -
printf '%s' "$ENCRYPTION_KEY"        | tinfoil secret create ENCRYPTION_KEY        --value-file -
```

(Use `tinfoil secret set <name> --value-file -` instead of `create` if they already exist.)

Register your SSH public key — debug containers (next steps) authorize SSH using org-level keys:

```bash
tinfoil ssh-key list                                                       # see what's already registered
tinfoil ssh-key create laptop --public-key-file ~/.ssh/id_ed25519.pub
```

Pick any name (`laptop` here); you'll reference it at deploy time with `--ssh-key laptop`.

## 3. configure tinfoil-config.yml

Two containers run side-by-side in the same CVM:

- **`sim`** — the workload. Talks S3 to `http://localhost:9000` with dummy creds.
- **`buckets`** — [tinfoil-buckets-sidecar](https://github.com/tinfoilsh/tinfoil-buckets-sidecar). Local S3-compatible proxy that AES-256-GCM-encrypts every PUT (and decrypts every GET) using `ENCRYPTION_KEY`, then forwards to the real bucket with the AWS creds. Only ciphertext ever leaves the enclave.

So `sim` writes plaintext to the sidecar, the sidecar writes ciphertext to S3, and on your laptop `view.py` reads ciphertext back and decrypts with the same key.

Open `tinfoil-config.yml` and, under the `buckets` block, set:

- `BUCKET` → your bucket name
- `AWS_REGION` → bucket's region

`sim`'s `image:` gets rewritten by the github action on tag — leave the `@sha256:...` placeholder alone. The sidecar's pinned digest is fine as-is.

```bash
git commit -am "tinfoil-config: set bucket"
```

## 4. tag a release

Triggers two github actions:

- `tinfoil-build.yml` — builds the docker image, pushes to ghcr, pins the digest in `tinfoil-config.yml`, creates the tag
- `tinfoil-release.yml` — measures the image and publishes attestation

```bash
gh workflow run tinfoil-build.yml -f version=v0.1.0 --ref $(git branch --show-current)
gh run watch    # wait for both jobs to go green
git pull        # fetch the digest-pin commit the action pushed
```

## 5. create the container (debug mode)

Deploy in debug mode while you're iterating — you get SSH access + container logs, which makes it easy to inspect the enclave when something goes wrong. (Section 9 covers switching to prod once your iteration loop is settled.)

```bash
tinfoil container create persistent-storage-sim \
  --repo <owner>/<repo> \
  --tag v0.1.0 \
  --debug \
  --ssh-key laptop \
  --secret AWS_ACCESS_KEY_ID \
  --secret AWS_SECRET_ACCESS_KEY \
  --secret ENCRYPTION_KEY
```

Wait for it to come up:

```bash
tinfoil container get persistent-storage-sim
# Status: deploying  →  active   (a few minutes)
```

The CVM starts the container immediately, so by the time it's `active` the sim is already running.

## 6. watch it run

Copy the `Domain:` line from `tinfoil container get persistent-storage-sim` — debug containers live under `persistent-storage-sim.debug.<org>.containers.tinfoil.dev` (note the `.debug.`).

```bash
DOMAIN=<paste from tinfoil container get>

curl -s https://$DOMAIN/status | jq

pip install -r requirements.txt
python status.py --url https://$DOMAIN/status
```

You'll see a colored per-phase progress bar:

```
== Starting Mock ML ==
Storing in 2026-05-06T05-17-19Z

Phase 1: explore
[████████████████████] 100% (2500/2500)
✓ Completed phase explore. Saved to 2026-05-06T05-17-19Z/checkpoint-1.json

Phase 2: drift
[████████░░░░░░░░░░░░] 42% (1041/2500)
...
```

After the bar finishes, the in-enclave sim exits, the container stops. The s3 data persists — that's the point.

Because you deployed with `--debug`, you can shell in any time to look at logs or poke around — `tinfoil container get` prints the SSH command (`ssh -p <port> root@console.tinfoil.sh`).

## 7. plot the trajectory

```bash
# view.py decrypts with $ENCRYPTION_KEY — make sure .env is sourced
set -a && source .env && set +a

python view.py --bucket $S3_BUCKET           # list runs in the bucket
python view.py --bucket $S3_BUCKET --latest  # plot most recent → trajectory.png
open trajectory.png
```

You'll see four visibly distinct regimes — explore (wide noise cloud), drift (linear), converge (pulled to origin), oscillate (loops).

## 8. resume from a checkpoint

Set the arg in `tinfoil-config.yml` and redeploy under a new tag:

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

The new run reuses the saved numpy rng state — resumed checkpoints are byte-identical to what an uninterrupted run would have produced.

## 9. promote to prod

Debug mode is for iteration and testing. When you're ready for the real security guarantees — attestation (verified enclave), no SSH, no docker logs — switch to production:

```bash
tinfoil container relaunch persistent-storage-sim --debug false
```

The domain moves from `<name>.debug.<org>.containers.tinfoil.dev` back to `<name>.<org>.containers.tinfoil.dev`. Production containers pass attestation, so callers using `tinfoil proxy` or `SecureClient` will accept them.

## 10. cleanup

```bash
tinfoil container stop   persistent-storage-sim   # pauses, keeps state
tinfoil container delete persistent-storage-sim   # destroys
aws s3 rm --recursive s3://$S3_BUCKET/persistent-storage/   # nuke runs
```
