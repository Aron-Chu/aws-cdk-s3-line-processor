# Repository agent guide

## Purpose

Keep this repository a small, reviewable AWS CDK example: one private S3
bucket directly invokes one Python Lambda that validates one-line JSON files.

## Authority and accountability

- Work only within the user's requested scope.
- A human maintainer owns the final diff, approvals, deployment plan, rollback
  decision, and any cloud or repository-setting mutation.
- Inspect current code and configuration before relying on documentation.
- Prefer conventional code and explicit security controls over abstractions.

## Required behavior

1. Read the relevant canonical document before changing behavior:
   `docs/design.md`, `docs/operations.md`, or `docs/platform-access.md`.
2. Make the smallest change that satisfies the requirement.
3. Add or update focused unit, workflow, CDK assertion, or documentation tests.
4. Run `make check` and `git diff --check`.
5. Report recorded, local, live, and operator-gated evidence separately.

## Prohibited behavior

- Do not create queues, databases, APIs, VPCs, NAT, or unrelated AWS services
  unless the requirement changes.
- Do not add account-level identities, GitHub OIDC providers, CDK bootstrap
  roles, access keys, Organizations resources, or root-account settings to this
  application stack.
- Do not modify live account resources, repository rules, or GitHub environments
  without explicit authorization and current target verification.
- Do not approve or review your own changes, and never satisfy repository or
  deployment approval gates on a human's behalf.
- Do not deploy, destroy, delete retained data, or run a write-capable smoke
  test without explicit authorization and identity checks.
- Never expose or commit account IDs, credentials, SSO URLs, uploaded data,
  private runbooks, live resource names, or generated `cdk.out/` content.
- Do not list an AI system as a commit co-author. The responsible human
  contributor authors the commit.

## Security invariants

- Keep S3 private, TLS-only, owner-enforced, encrypted, versioned, and retained.
- Scope Lambda reads to `incoming/*`; do not grant S3 writes.
- Constrain S3 invocation by source account and bucket ARN.
- Keep logs free of object contents, parsed values, field names, raw bucket/key,
  and ETag.
- Treat malformed input as permanent rejection and AWS/service failures as
  retryable operational errors.
- Keep repository deployment on short-lived OIDC credentials behind protected
  `main` and the `production` deployment-control environment.

## Documentation ownership

- `README.md`: entry point and document index.
- `CONTRIBUTING.md`: human and agent-assisted contribution workflow.
- `SECURITY.md`: private vulnerability reporting.
- `docs/design.md`: behavior, security, networking, and intentional omissions.
- `docs/operations.md`: routine deployment and maintenance.
- `docs/platform-access.md`: account-level and GitHub prerequisites.
- `docs/test-results.md`: dated evidence, never evergreen claims.

Keep the editable architecture source and exported SVG aligned with behavior.
