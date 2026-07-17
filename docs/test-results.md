# Live test results

## Deployed smoke (July 16, 2026)

Protected deploy of commit `482e89e`, then:

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
| Standard log context (`service`, `environment`, `log_schema_version`) | Passed |
| Smoke objects cleaned up | Passed |

Nine outcome logs matched the matrix. Region: `us-west-2`.

This is historical schema-v1 evidence. It predates the schema-v2 pseudonymous
`object_ref` contract and the two-stage prepare/execute deployment workflow; do
not cite it as live proof of those later changes.

## Current checkout validation (July 17, 2026)

```bash
TMPDIR=/tmp TMP=/tmp TEMP=/tmp make check
```

Result: lock verification, all pre-commit hooks, 63 tests, 95.72% coverage, and
CDK synthesis passed. This is local evidence only. The schema-v2 logging change
still requires protected deployment followed by `make smoke` before it can be
claimed as live.

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
