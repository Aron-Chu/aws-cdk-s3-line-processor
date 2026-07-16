# Live test results

Verified against the deployed `S3LineProcessorStack` in `us-west-2` on
July 16, 2026.

| Case | Expected | Result |
| --- | --- | --- |
| Valid JSON object | `processed` | Passed |
| Invalid JSON | `invalid_json` | Passed |
| Multiple JSON lines | `multiline_input` | Passed |
| Empty file | `empty_input` | Passed |
| JSON array | `non_object_json` | Passed |
| Invalid UTF-8 | `invalid_utf8` | Passed |
| File over 1 MiB | `object_too_large` | Passed |
| `incoming/*.txt` | No invocation | Passed |
| Rapid overwrite | Each S3 version handled separately | Passed |

Nine expected Lambda logs were observed. No test payload field names or values
appeared in CloudWatch Logs.

Reproduce with an approved operator profile:

```bash
python scripts/live_smoke_test.py --profile OPERATOR_PROFILE --cleanup
```

The profile needs read access to the stack and logs, plus write and version-delete
access limited to the deployed bucket's `incoming/*` test objects.
