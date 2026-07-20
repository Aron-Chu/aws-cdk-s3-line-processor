# Contributing

## Purpose

How humans and coding agents make small, reviewable changes without weakening
security or deployment boundaries.

## Who should use this

Contributors and maintainers preparing a pull request.

## What this does not do

Does not grant AWS access or authorize deployment. See
[platform access](docs/platform-access.md).

## Before changing code

1. Read [AGENTS.md](AGENTS.md) and the relevant design or operations section.
2. Confirm the requirement does not silently expand the one-bucket/one-Lambda
   architecture.
3. Create a focused branch or fork from current `main`.
4. Keep secrets, account IDs, SSO URLs, live resource names, and generated
   `cdk.out/` content out of the repository and PR discussion.

## Change and test workflow

1. Implement the smallest complete change.
2. Add focused tests for behavior, IAM, workflow, or documentation contracts.
3. Run:

   ```bash
   make check
   git diff --check
   ```

4. Review the synthesized change and final diff. For an authorized sandbox,
   use `make diff PROFILE=<SSO_PROFILE>` before any local deployment.
5. Open a pull request and complete its security, evidence, deployment, and
   rollback sections.

Use conventional commit subjects. The responsible human contributor authors
the commit; do not add AI co-author trailers.

## Evidence by change type

| Change | Minimum evidence |
| --- | --- |
| Documentation | Documentation tests, full `make check`, rendered-link review |
| Lambda behavior | Focused handler tests, full `make check`, log-safety review |
| CDK or IAM | CDK assertions, full `make check`, synthesized template review |
| GitHub workflow | Workflow tests, least-privilege permission review, full `make check` |
| Architecture or diagram | Design update, source/export alignment, full `make check` |

Tests and synthesis prove the candidate locally. They do not prove that a
deployment or smoke test occurred; record live evidence separately.

## Agent-assisted changes

Agents may inspect, edit, test, and synthesize within the approved task. They
must not approve their own work, disclose secrets, change account or repository
settings, deploy, destroy, or delete retained data without explicit human
authorization. A human reviews the full diff/template impact, IAM and logging
behavior, validation output, deploy/rollback impact, and every live-state claim
before merge.

## Review and merge

- Pull requests run credential-free CI. Do not add AWS credentials to PR jobs.
- Resolve review conversations and keep the branch current with `main`.
- Do not use a documentation-only PR to change runtime or access behavior.
- Merge through the protected branch rules. Repository deployment occurs only
  after the relevant change reaches protected `main`.
- Follow [operations](docs/operations.md) for plan review, execution, and smoke
  testing. A merged PR is not deployment evidence.

## Documentation ownership

Put architecture and behavior in `docs/design.md`, routine commands in
`docs/operations.md`, account prerequisites in `docs/platform-access.md`, and
dated evidence in `docs/test-results.md`. Update the README only when the entry
point or document map changes.
