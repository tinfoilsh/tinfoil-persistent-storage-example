# Tinfoil Public Containers Template

A GitHub template for [Tinfoil Containers](https://docs.tinfoil.sh/containers/overview) where the image is **built from this repo** on every tagged release. Use this when your container's source lives alongside its deployment config.

This only works for **public repos**.

If you need to deploy a private image, use the [tinfoil-containers-template](https://github.com/tinfoilsh/tinfoil-containers-template) instead.

## What's inside

- `main.go` — a tiny Go HTTP server that responds with `Hello from a Tinfoil Container!`
- `Dockerfile` — multi-stage build, statically linked, no extras
- `tinfoil-config.yml` — the enclave config; the digest is rewritten by CI
- `.github/workflows/tinfoil-build.yml` — builds the image, updates `tinfoil-config.yml`, pushes the version tag
- `.github/workflows/tinfoil-release.yml` — measures the pinned image and publishes the attestation

## Use it

1. Click **[Use this template](https://github.com/tinfoilsh/tinfoil-public-containers-template/generate)** → **Create a new repository** (must be public).
2. In your new repo, edit `tinfoil-config.yml` and replace `OWNER/REPO` with your GitHub path (e.g. `ghcr.io/your-org/your-repo`). Commit.
3. In the **Actions** tab, run the **Tinfoil Container Build** workflow and pass a version like `v0.0.1`.
4. The workflow:
   - Builds and pushes the image to `ghcr.io/<owner>/<repo>`
   - Updates `tinfoil-config.yml` with the new digest via a self-merging PR
   - Creates the version tag
   - Triggers the release workflow, which measures the image and publishes the attestation
5. Go to the [Tinfoil Dashboard](https://dash.tinfoil.sh) → **Containers** → **Deploy**, select your repo and tag, and deploy.

Once running, your container is reachable at `https://<container-name>.<org>.containers.tinfoil.dev`.

## Updating

Make changes, commit, then re-run **Tinfoil Container Build** with a fresh version (e.g. `v0.0.2`). Click **Update** in the dashboard once the tag exists.

## Documentation

[docs.tinfoil.sh/containers](https://docs.tinfoil.sh/containers/overview)
