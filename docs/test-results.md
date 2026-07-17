# Live test results

## Deployed smoke (July 17, 2026)

Protected two-stage Deploy of commit `fb2506e`
([run 29614368981](https://github.com/Aron-Chu/aws-cdk-s3-line-processor/actions/runs/29614368981)):
validate → approve plan → prepare change set → approve execute →
`execute-change-set`, then:

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

Nine outcome logs matched the matrix. Region: `us-west-2`. This is live proof of
schema-v2 `object_ref` logging and the prepare/execute Deploy path.

## Historical smoke (July 16, 2026)

Protected deploy of commit `482e89e` (schema-v1 logging). Kept for history only;
do not cite it as proof of schema-v2 or two-stage Deploy.

## Current checkout validation (July 17, 2026)

```bash
TMPDIR=/tmp TMP=/tmp TEMP=/tmp make check
```

Result: lock verification, all pre-commit hooks, 63 tests, 95.72% coverage, and
CDK synthesis passed before the protected Deploy above.

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
