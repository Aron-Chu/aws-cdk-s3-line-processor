# Live test results

## Latest operator smoke (July 16, 2026)

Ran against deployed `S3LineProcessorStack` in `us-west-2` with the
`s3-line-processor-operator` IAM user profile:

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
| Standard log context (`service`, `environment`, `log_schema_version`) | Failed — live logs omit these fields |

Nine outcome logs were observed. Validation behavior matches local unit tests.

The missing log-context fields are present in the current repository handler
(`_serialize_log`) and stack env vars. Sample live messages still use the older
plain `[INFO]\t…\t{json}` shape without those keys, so this is a **stale
deploy**, not a smoke-script false negative. Redeploy from protected `main`
(after merging current changes), then rerun `make smoke`.

## Local tests

```bash
make setup
make test
```

`make test` covers handler, stack assertions, and smoke-script helpers. It does
not call AWS.
