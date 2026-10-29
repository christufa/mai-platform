# Security policy

## Reporting a vulnerability

Please **don't open a public issue**. Use GitHub's private reporting instead:
**Security → Report a vulnerability** on this repository. You'll get a response
within a week.

In scope: the `mai-base` images (`ghcr.io/christufa/mai-base`), their build
workflows, and the project template in `template/`.

## Verifying the images

Every published image is signed with [cosign](https://github.com/sigstore/cosign)
(keyless, via GitHub Actions OIDC) and carries an SBOM and build provenance.

```bash
cosign verify ghcr.io/christufa/mai-base:runtime-0.2.1 \
  --certificate-identity-regexp '^https://github\.com/christufa/mai-platform/\.github/workflows/image\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## How this repo is protected

- `main` can't be force-pushed or deleted by anyone. Apart from the owner,
  it only changes through pull requests that pass `image-gate`,
  `template-gate` and `workflow-lint`; history is linear and signed.
- Release tags (`v*`) can't be moved or deleted once pushed.
- Workflows run with no token permissions by default; each job requests only
  what it needs. Fork PRs never push, sign or write the build cache.
- All actions are pinned to commit SHAs and checked by zizmor and actionlint.
- Secret scanning with push protection, Dependabot alerts and CodeQL are on.

The settings live in [`security/`](security/) and are applied with
`security/apply-repo-settings.ps1`.
