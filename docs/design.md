# Design

## Runtime flow

1. A client uploads an object to the private bucket under `incoming/` with a
   `.json` suffix over HTTPS.
2. S3 emits `s3:ObjectCreated:*` for matching keys and invokes the Lambda
   directly.
3. The Lambda reads that object version (when present), validates one-line JSON,
   and logs structured metadata only.
4. Malformed input is rejected permanently for that record. AWS or service
   failures raise and remain retryable.

## Input contract

| Rule | Requirement |
| --- | --- |
| Key | Must start with `incoming/` and end with `.json` |
| Size | At most `MAX_FILE_BYTES` (default 1 MiB) |
| Encoding | UTF-8, optional BOM |
| Shape | Exactly one JSON line; trailing `\n` or `\r\n` allowed |
| JSON | A single object (`{...}`); no arrays, scalars, `NaN`, `Infinity`, or `-Infinity` |
| Rejected | Empty body, multiple lines, invalid UTF-8, invalid JSON, non-object JSON |

Successful logs include object identity fields and `parsed_field_count`. They
never include object contents, parsed values, or field names.

## Security boundaries

- Bucket is private: block public access, owner-enforced, SSE-S3 encrypted, and
  versioned.
- Bucket policy denies all `s3:*` when `aws:SecureTransport` is false.
- Lambda may `s3:GetObject` / `s3:GetObjectVersion` only on `incoming/*`; it has
  no S3 write permissions.
- S3-to-Lambda invoke permission is constrained by source account and bucket ARN.
- Logs stay structured and free of payload contents.

## Errors

| Class | Examples | Behavior |
| --- | --- | --- |
| Permanent | Unexpected key or record shape, oversized object, empty/multiline input, invalid UTF-8/JSON, non-object JSON | Logged as `rejected` with a reason code; other records in the same event continue |
| Operational | S3 read failures, unexpected service errors | Logged as `failed` and re-raised so the platform can retry |

## Delivery semantics

S3 event notifications to Lambda are at-least-once. The same object create can
invoke more than once. This stack does not implement idempotency keys or
deduplication; treat processing as potentially repeated.

## Out of scope

Not implemented. Revisit when requirements demand them:

| Need | Candidate |
| --- | --- |
| Buffering, isolated retries, or poison-message handling | SQS between S3 and Lambda, plus a DLQ |
| Operator alerts on failures or throttling | CloudWatch alarms |
| Customer-managed encryption | KMS (SSE-KMS) on the bucket |
| Safe reprocessing of duplicate deliveries | Explicit idempotency (for example keyed by bucket/key/version) |
