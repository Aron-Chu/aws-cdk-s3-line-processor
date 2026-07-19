# Verification evidence

## Purpose

Record dated evidence tied to an exact deployed commit or an explicitly named
working-tree candidate.

## Evidence rule

This file is a historical record, not an automatically current status page.
Before citing a result, compare its commit with current `main` and distinguish:

| Evidence | Meaning |
| --- | --- |
| Local | Executed against a checkout; no AWS proof |
| Workflow | Recorded by GitHub Actions for an exact commit |
| Live read-only | Observed from AWS without changing resources |
| Operator action | A write-capable deploy, smoke, rollback, or cleanup performed by an authorized human |

## Documentation candidate (July 19, 2026)

Candidate: uncommitted documentation/test changes based on commit `4b36758`.

```bash
TMPDIR=/tmp TMP=/tmp TEMP=/tmp \
  .venv/bin/pytest tests/test_docs.py -vv --no-cov

TMPDIR=/tmp TMP=/tmp TEMP=/tmp make check
git diff --check
```

Result:

- 8 focused documentation tests passed.
- All pre-commit hooks passed, including private-key and hardcoded-secret checks.
- All 86 tests passed with 96.89% application coverage.
- CDK synthesis passed.
- No AWS or GitHub resource was changed by validation.

Because this candidate is not committed, these results must be replaced or
supplemented with the final commit and CI run before being treated as merged
evidence.

## Latest deployed commit (July 18, 2026)

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
documented in [the design](design.md) and [operations](operations.md).

## Reproduce local evidence

```bash
make setup
TMPDIR=/tmp TMP=/tmp TEMP=/tmp make check
```

Use [operations](operations.md) for authorized live deployment and smoke
procedures. Record their exact commit, workflow URL, actor-owned evidence, and
date here without exposing account IDs or live resource names.
