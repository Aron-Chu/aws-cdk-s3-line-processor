# Live test results

## Deployed smoke (July 17, 2026)

One protected Deploy workflow for commit `ac27e07`
([run 29622217666](https://github.com/Aron-Chu/aws-cdk-s3-line-processor/actions/runs/29622217666)):
validate → approve plan preparation → prepare change set → approve exact
plan execution → `execute-change-set`, then:

```bash
make smoke PROFILE=s3-line-processor-operator
```

| Check | Result |
| --- | --- |
| Valid JSON → `processed` | Passed |
| Invalid JSON → `invalid_json` | Passed |
| Multiline → `multiline_input` | Passed |
| Empty → `empty_input` | Passed |
| JSON array → `non_object_json` | Passed |
| Invalid UTF-8 → `invalid_utf8` | Passed |
| Over 1 MiB → `object_too_large` | Passed |
| `incoming/*.txt` → no invocation | Passed |
| Rapid overwrite → each version handled | Passed |
| Payload field names/values absent from logs | Passed |
| Raw bucket name / object key absent from logs | Passed |
| Standard log context (`service`, `environment`, `log_schema_version=2`) | Passed |
| Smoke objects cleaned up | Passed |

Nine outcome logs matched the matrix. The smoke also confirmed that S3 ETags
were absent from logs. Region: `us-west-2`. This is live proof of schema-v2
`object_ref` logging and the exact prepare/execute Deploy path.

Manual Deploy of the same unchanged commit
([run 29622647315](https://github.com/Aron-Chu/aws-cdk-s3-line-processor/actions/runs/29622647315))
prepared an empty CloudFormation plan and skipped the execute job. This proves
the no-change path does not request a second approval or mutate the stack.

## Historical smoke (July 16, 2026)

Protected deploy of commit `482e89e` (schema-v1 logging). Kept for history only;
do not cite it as proof of schema-v2 or the current Deploy workflow.

## Current checkout validation (July 17, 2026)

```bash
TMPDIR=/tmp TMP=/tmp TEMP=/tmp make check
```

Result for the current branch: lock verification, all pre-commit hooks, 69
tests, 95.74% coverage, and CDK synthesis passed. All 100 CDK feature flags are
pinned to their reviewed recommended values; a synth comparison confirmed the
flags do not change any application resource.

## Fresh local setup (July 16, 2026)

Clean-room install and full validation with a new absolute venv:

```bash
make setup VENV=/tmp/s3lp-fresh-venv
TMPDIR=/tmp make check VENV=/tmp/s3lp-fresh-venv
```

Result: seeded uv venv and hash-pinned install succeeded; lock verification,
pre-commit, 61 tests (96.23% coverage), and CDK synth passed.

## Local unit tests

```bash
make setup
make test
```

Handler, stack assertions, and smoke helpers. No AWS calls.
