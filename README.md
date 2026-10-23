# mai-platform

One repo for the GPU/ML dev platform.

```
mai-platform/
├── image/                 # base image: Dockerfile (dev + runtime), pyproject.toml, uv.lock, smoke_test.py
├── template/              # Copier project template (rendered into new projects)
├── copier.yml             # template questions
├── renovate.json          # automated dependency PRs (see "Keeping the image current")
├── SECURITY.md            # vulnerability reporting + image signature verification
├── security/              # rulesets + script that applies the repo's GitHub security settings
└── .github/
    ├── workflows/image.yml          # build, smoke-test, push, sign, scan, prune ghcr.io/<owner>/mai-base
    ├── workflows/template.yml       # render template + run its tests inside the runtime image
    └── workflows/workflow-lint.yml  # actionlint + zizmor on every workflow (incl. the template's)
```

## The idea

| Concern | Before | Now |
|---|---|---|
| Python env | conda + unpinned pip ranges (torch 2.5 vs >=2.11 conflict) | **uv** + `uv.lock`: one exact env per commit |
| Image | single fat devel image | `dev` (nvcc, Jupyter, zsh, SkyPilot, Claude Code) and slim `runtime` for jobs |
| Project template | copy a folder | **Copier**: `copier update` pulls template improvements into existing projects |
| Where code runs | local GPU only | Same image + code on local GPU, a cloud dev box, or managed spot jobs via **SkyPilot** |
| Data / checkpoints | host folders | Host mounts locally, object storage (R2/S3/GCS) in the cloud; atomic, resumable checkpoints |

```
               ┌────────── mai-base:dev ──────────┐        ┌──── mai-base:runtime ────┐
 laptop/desktop│ VS Code devcontainer (local GPU) │  cloud │ sky jobs launch (spot,   │
               │ make train / make test           │ ─────▶ │ auto-recover, multi-node)│
               └──────────────────────────────────┘        └──────────┬───────────────┘
                              same uv.lock, same train.py              │
                                                         r2:// | s3:// | gs:// bucket
                                                         data/  checkpoints/<run>/
```

## Setup

1. **Create the repo** `christufa/mai-platform`, push this folder, and tag a first release:
   ```bash
   git init && git add . && git commit -m "Initial mai-platform scaffold"
   git remote add origin https://github.com/christufa/mai-platform.git
   git push -u origin main
   git tag v0.1.0 && git push --tags
   ```
   `image.yml` publishes `ghcr.io/christufa/mai-base:{dev,runtime}` plus `dev-0.1.0` / `runtime-0.1.0`.
2. **Package visibility.** Either make the `mai-base` GHCR package public (simplest for SkyPilot), or keep it private.
   If private, give the template repo and project repos read access under *Package settings → Manage Actions access*,
   and uncomment the `SKYPILOT_DOCKER_*` secrets in `sky/*.yaml`.
3. **Create a project:**
   ```bash
   cd C:\Users\chris\repos
   uvx copier copy --trust gh:christufa/mai-platform my-project
   ```
   Push it to GitHub and add the repo to the Renovate app's repository list so it gets image-release PRs.
4. **Turn on automation and protection** (one-time):
   - Install the [Renovate GitHub App](https://github.com/apps/renovate) on `mai-platform`. Its first PR, "Configure Renovate", confirms the setup; merge it.
   - Run `powershell -ExecutionPolicy Bypass -File security\apply-repo-settings.ps1` (needs `gh` logged in as the owner). See [Security](#security).
5. **Cloud (optional, when you need it):**
   ```bash
   uv tool install "skypilot[aws,gcp,runpod,lambda,kubernetes]"   # or use the one in the dev image
   sky check                                                      # shows which clouds are usable
   ```

## Keeping the image current

| Layer | What happens | Your involvement |
|---|---|---|
| OS packages (openssl, glibc…) | Weekly **no-cache** rebuild (Mon 06:17 UTC): pulls the newest NVIDIA base and runs `apt-get upgrade` | None |
| Python patch releases | Renovate PR (Mondays) → image build + smoke test → **auto-merged** | None, unless CI fails |
| Python minor/major releases | Renovate PR; the Hugging Face libraries come as one grouped PR | Review and merge |
| Whole lockfile refresh | Renovate "Refresh uv.lock" PR, 1st of each month | Review and merge |
| torch / torchvision / triton | Listed on the Renovate **Dependency Dashboard** issue; a PR opens only when you tick it | Deliberate: tick, merge, cut a release |
| CUDA / Ubuntu / Python | Edit `env:` in `image.yml` (+ defaults in `Dockerfile`) | Manual, with a release |
| GitHub Actions | Pinned to commit SHAs by Renovate; minor/patch updates auto-merge | None |
| **Projects** using the image | Each project pins a release (`dev-0.1.0`) and has its own `renovate.json`. When you tag a new mai-base release, every project gets one PR that bumps the devcontainer, SkyPilot files and CI together | Merge in each project when ready |

Safety nets on every build:
- `image/smoke_test.py` runs **inside** `docker build`. It checks that every package is installed at its locked version, that the key libraries import, and that torch's CUDA major version matches the base image's. If it fails, nothing is pushed.
- A Grype vulnerability scan of each pushed image appears under **Security → Code scanning** (fixed, high+ only; it reports and never blocks).
- A cleanup job prunes untagged manifests, old `-sha-` tags (>30 days) and dated tags (>90 days). Release and rolling tags are never deleted. Cosign signatures and attestations are handled safely.

**Tags and pinning.** `dev`/`runtime` always point at the newest build of main. `dev-2026.10.14`-style dated tags let you roll back to any recent weekly build. `dev-0.2.0` release tags never change. New projects pin the latest release by default (`image_version` in Copier, currently `0.1.0`; bump that default in `copier.yml` when you cut releases). Cut a release whenever a set of updates is worth adopting: `git tag v0.2.0 && git push --tags`.

## Security

`security/apply-repo-settings.ps1` applies everything below and is safe to re-run; edit the JSON in `security/` and re-run to change it.

| Area | Setting |
|---|---|
| `main` (rulesets `main-integrity` + `main-changes`) | Nobody, including you, can force-push or delete `main`. Everyone else changes it only via squash-merged PRs that pass `image-gate`, `template-gate`, `workflow-lint`, with linear, signed history. You (repo admin) bypass `main-changes`, so you can push directly |
| Release tags (`protect-release-tags`) | `v*` tags can't be moved or deleted, so `dev-0.1.0` always means the same thing |
| Workflows | No token permissions by default (each job requests its own); actions SHA-pinned and allow-listed (`security/selected-actions.json`); fork PRs need your approval to run; fork PRs never push, sign or write the build cache |
| Linting | `workflow-lint` runs actionlint + zizmor on every PR |
| Scanning | Secret scanning + push protection, Dependabot alerts (Renovate opens the fixes), CodeQL, Grype scan of each image |
| Reporting | Private vulnerability reporting ([SECURITY.md](SECURITY.md)) |

The required checks are *gate* jobs that always report, even when a PR doesn't touch the image or template (those jobs are skipped, and the gate still passes). That's what makes it safe to require them with path-filtered workflows.

You can push straight to `main`. For a change you want CI to check first, use a PR: `git switch -c my-change` → commit → `git push -u origin my-change` → `gh pr create --fill` → `gh pr merge --auto --squash` (merges itself once checks pass).

## Day-to-day

| Task | Command |
|---|---|
| Bump a library in the image | edit `image/pyproject.toml` → `cd image && uv lock` → PR |
| Upgrade everything | `cd image && uv lock --upgrade` → PR (CI builds it before merge) |
| Release the image | `git tag v0.2.0 && git push --tags` |
| Build locally | `docker build --target dev -t mai-base:dev image/` |
| Pull template changes into a project | `uvx copier update` (in the project) |

## Version pins

CUDA / Ubuntu / Python live in `env:` in `.github/workflows/image.yml`, with matching defaults in `image/Dockerfile`.
PyTorch wheels from PyPI bundle their own CUDA 13 runtime libraries, so the base image's CUDA version only needs to be
≥ what torch was built against (and your driver must support it — check `nvidia-smi`).

## Migrating from the old repos

- `environment.yml` and `requirements.txt` → `image/pyproject.toml` (duplicates removed, conflicting torch pins resolved to 2.14.1).
- `entrypoint.sh` is gone: no conda activation is needed, since `/opt/venv/bin` is on `PATH`.
- The interpreter path changed from `/opt/conda/envs/ds/bin/python` to `/opt/venv/bin/python`.
- `C:\data` and `C:\Users\chris\dev\.cache` mounts are kept as template defaults (`host_data_dir`, `host_cache_dir`).
- The old repos can be archived once a project has been moved over.
