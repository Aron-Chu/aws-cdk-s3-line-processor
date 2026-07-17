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

## Fresh local setup (July 16, 2026)

Clean-room install with a new custom venv (not the repo `.venv`):

```bash
make setup VENV=/tmp/s3lp-fresh-venv
make lock-check VENV=/tmp/s3lp-fresh-venv
```

Result: seeded uv venv created, hash-pinned install from `requirements.lock` succeeded,
imports resolved, and lock-check passed.

## Local unit tests

```bash
make setup
make test
```

Handler, stack assertions, and smoke helpers. No AWS calls.
