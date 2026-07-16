# Repository agent guide

## Goal

Keep this repository a small, reviewable AWS CDK example: one private S3
bucket directly invokes one Python Lambda that validates one-line JSON files.
Prefer conventional code and explicit security controls over abstractions.

## Boundaries

- Do not add queues, databases, APIs, VPCs, NAT, or unrelated AWS services
  unless the requirement changes.
- Do not create account-level identities, GitHub OIDC providers, CDK bootstrap
  roles, access keys, Organizations resources, or root-account settings here.
- Never commit account IDs, credentials, uploaded data, private runbooks, or
  generated `cdk.out/` content.
- Preserve the retained bucket and bucket policy unless lifecycle requirements
  change explicitly.

## Security invariants

- Keep S3 private, TLS-only, owner-enforced, encrypted, and versioned.
- Scope Lambda reads to `incoming/*`; do not grant S3 writes.
- Constrain S3 invocation permission by source account and bucket ARN.
- Keep logs structured and free of object contents, parsed values, and field
  names.
- Treat malformed input as permanent rejection and AWS/service failures as
  retryable operational errors.
- Keep GitHub deployment on short-lived OIDC credentials behind the protected
  `production` environment.

## SDLC

1. Make the smallest change that satisfies the requirement.
2. Add or update focused unit and CDK assertion tests.
3. Run `pre-commit run --all-files`, `pytest`, and `npx cdk synth`.
4. Review `cdk diff` before any authenticated deployment.
5. Use conventional commits authored only by Aron-Chu; add no co-author
   trailers.
6. Deploy only from protected `main`, approve `production`, then smoke-test.

## Documentation

Keep `README.md` short: overview, architecture diagram, security trust chart,
and deploy/maintain commands only. Keep presentation detail out of the public
repo. Keep `docs/architecture.excalidraw` and `docs/architecture.svg` aligned
with behavior.
