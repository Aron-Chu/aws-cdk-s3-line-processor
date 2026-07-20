# Verification evidence

## Purpose

Dated evidence for an exact commit or named working-tree candidate, not an
evergreen status page.

## Evidence rule

This file is a historical record, not an automatically current status page.
Before citing a result, compare its commit with current `main` and distinguish:

| Evidence | Meaning |
| --- | --- |
| Local | Executed against a checkout; no AWS proof |
| Workflow | Recorded by GitHub Actions for an exact commit |
| Live read-only | Observed from AWS without changing resources |
| Operator action | A write-capable deploy, smoke, rollback, or cleanup performed by an authorized human |

## Current smoke posture (July 19, 2026)

The smoke commands require a temporary assumed-role profile. Identity Center is
the preferred workforce path; this Sandbox may use role assumption until it is
available. No current live 9/9 smoke is recorded. Local proof remains
`make check`; direct IAM-user/root sessions are rejected by design.

## Assumed-role smoke support (July 19, 2026)

Commit `37af6ae` landed on protected `main` through
[PR #37](https://github.com/Aron-Chu/aws-cdk-s3-line-processor/pull/37)
(`feat: support temporary assumed-role smoke profiles`).

Local validation for that merge recorded 130 tests with 96.89% application
coverage. Protected Deploy
[run 29711577630](https://github.com/Aron-Chu/aws-cdk-s3-line-processor/actions/runs/29711577630)
completed `validate` and `plan` for `37af6ae`, prepared an empty change set, and
skipped execute. No application CloudFormation resources changed. No
assumed-role 9/9 smoke is recorded yet; the private Smoke Operator role remains
a platform prerequisite outside this repository.

## Merged documentation and GitOps update (July 19, 2026)

Commit `7c6e4af` landed on protected `main` through
[PR #31](https://github.com/Aron-Chu/aws-cdk-s3-line-processor/pull/31)
(`chore: make repository reviewer-ready`).

Local validation for that merge recorded:

- 86 tests with 96.89% application coverage;
- pre-commit hooks, including private-key and hardcoded-secret checks;
- CDK synthesis; and
- `git diff --check` clean.

Protected Deploy
[run 29700704742](https://github.com/Aron-Chu/aws-cdk-s3-line-processor/actions/runs/29700704742)
completed `validate` and `plan` for `7c6e4af`, prepared an empty change set, and
skipped execute. No application CloudFormation resources changed.

## Latest resource-changing deploy (July 18, 2026)

Commit `4b36758` was deployed through the protected workflow in
[run 29626162618](https://github.com/Aron-Chu/aws-cdk-s3-line-processor/actions/runs/29626162618).
The exact sequence completed successfully:

```text
validate -> approve plan -> prepare change set -> approve execution
  -> verify immutable evidence -> execute change set -> wait for stack
```

A manual run of the unchanged commit,
[run 29627750709](https://github.com/Aron-Chu/aws-cdk-s3-line-processor/actions/runs/29627750709),
prepared an empty change set and skipped execution. This is recorded evidence
for the no-change path.

## Live read-only observation (July 19, 2026)

Read-only CloudFormation and CloudWatch queries observed:

- stack status `UPDATE_COMPLETE` for `S3LineProcessorStack`;
- the expected bucket and function output keys;
- nine schema-v2 application records from the post-deploy smoke window;
- expected `processed` and rejection reason-code outcomes; and
- only approved metadata keys, with no raw bucket/key, payload, field name, or
  ETag fields.

This observation did not upload or delete objects and is not a replacement for
a newly authorized `make smoke` run. The stack reported termination protection
disabled and drift status `NOT_CHECKED`; those current operating tradeoffs are
documented in [the design](design.md) and [operations](operations.md). The later
`7c6e4af` empty-plan Deploy did not change that live posture.

## Reproduce local evidence

```bash
make setup
make check
```

Use [operations](operations.md) for authorized live deployment and smoke
procedures. Record their exact commit, workflow URL, actor-owned evidence, and
date here without exposing account IDs or live resource names.
