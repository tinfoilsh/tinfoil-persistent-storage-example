# Deploying this to a Tinfoil container

End-to-end checklist for actually running the sim inside a Tinfoil enclave instead of locally in Docker.

## prereqs

- a tinfoil org with the **containers** product enabled
- an admin api key from the dashboard (Settings → API Keys → Admin keys)
- the `tinfoil` cli
- this repo pushed to a public GitHub repo (currently `tinfoilsh/tinfoil-persistent-storage-example`)
- AWS access key + secret for the IAM user that owns the bucket — these go into the Tinfoil secret store, not into `.env`

## install + login

```bash
curl -fsSL https://github.com/tinfoilsh/tinfoil-cli/raw/main/install.sh | sh
tinfoil login                # prompts for the admin api key
tinfoil whoami               # confirm
```

## one-off setup: org secrets

The two AWS keys live as org-level secrets on Tinfoil and get injected into the container at boot. The names must match the `secrets:` list in `tinfoil-config.yml`.

```bash
echo -n "$AWS_ACCESS_KEY_ID"     | tinfoil secret create AWS_ACCESS_KEY_ID --value-file -
echo -n "$AWS_SECRET_ACCESS_KEY" | tinfoil secret create AWS_SECRET_ACCESS_KEY --value-file -
tinfoil secret list              # confirm both are present
```

(If they already exist, use `tinfoil secret set <name> --value-file -` instead.)

## edit `tinfoil-config.yml` for your bucket

Open `tinfoil-config.yml` and update:

- `S3_BUCKET` → your bucket name (e.g. `tinfoil-demo-579421472636-us-east-2-an`)
- `AWS_REGION` → the bucket's region (e.g. `us-east-2`)

The image `ghcr.io/OWNER/REPO:placeholder` line will be rewritten by the release workflow when you tag — you don't need to touch the `@sha256:...` part.

## tag a release

This triggers two workflows in `.github/workflows/`:

1. `tinfoil-build.yml` — builds the docker image, pushes to `ghcr.io/<owner>/<repo>`, and rewrites the digest in `tinfoil-config.yml`.
2. `tinfoil-release.yml` — fires after the digest is pinned and prepares the deployment.

```bash
git push origin main
git tag v0.1.0 && git push origin v0.1.0
```

Wait for the build action to finish — `gh run watch` or check the Actions tab. The pinned `tinfoil-config.yml` lives on the `v0.1.0` tag.

## create the container

```bash
tinfoil container create persistent-storage-sim \
  --repo tinfoilsh/tinfoil-persistent-storage-example \
  --tag v0.1.0 \
  --secret AWS_ACCESS_KEY_ID \
  --secret AWS_SECRET_ACCESS_KEY
```

Then poll for it to come up:

```bash
tinfoil container get persistent-storage-sim
# wait until status="active"
```

## hit it

Tinfoil exposes the container at `https://persistent-storage-sim.<your-org>.containers.tinfoil.dev` (the dashboard shows the exact URL). You can also use `tinfoil container connect` to proxy locally with attestation:

```bash
tinfoil container connect persistent-storage-sim -p 8080
# in another terminal
curl https://localhost:8080/status
python status.py            # works the same as local
```

## resume from a checkpoint

For Tinfoil-managed containers there's no `docker run` to append args to — you have to set `command:` in `tinfoil-config.yml`, push a new tag, and `relaunch`:

```yaml
containers:
  - name: "sim"
    image: "..."
    command: ["--resume-from", "2026-05-06T04-43-46Z:2"]
```

```bash
git commit -am "resume from ckpt 2"
git tag v0.1.1 && git push --tags
tinfoil container relaunch persistent-storage-sim --tag v0.1.1
```

## teardown

```bash
tinfoil container stop persistent-storage-sim    # pauses, keeps state
tinfoil container delete persistent-storage-sim  # destroys
```

S3 data persists either way — that's the whole point.

## debugging

If the container never reaches `active`, check `tinfoil container update status <name>` for the failure detail. For SSH access into a debug instance:

```bash
tinfoil ssh-key create laptop --public-key-file ~/.ssh/id_ed25519.pub
tinfoil container create persistent-storage-sim-dbg \
  --repo tinfoilsh/tinfoil-persistent-storage-example \
  --tag v0.1.0 \
  --secret AWS_ACCESS_KEY_ID --secret AWS_SECRET_ACCESS_KEY \
  --debug
# attestation is disabled in debug mode
```
