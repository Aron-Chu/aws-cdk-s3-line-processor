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

## Networking model

The stack creates no customer-managed VPC. Uploaders and the non-VPC Lambda use
AWS regional service endpoints over HTTPS; AWS manages service DNS, routing, and
transport termination. "Private bucket" means access is controlled by IAM,
Block Public Access, and bucket policy—it does not mean the S3 regional endpoint
is reachable only through a private network.

S3-to-Lambda notification delivery is an AWS-managed service invocation rather
than a customer-routed TCP connection. The Lambda resource permission still
constrains that invocation by source account and bucket ARN. A VPC, NAT gateway,
security groups, Route 53, and VPC endpoints would add no required protection
for the current flow. Revisit them only for private-resource access, private-only
upload paths, or explicit egress controls; ZTNA is not applicable because this
stack exposes no interactive private application.

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
Object keys are logged for correlation, so uploaders must not place secrets or
personal data in file names.

Lambda's native JSON log format keeps application records machine-readable.
Every entry carries `service`, `environment`, and `log_schema_version` fields
for consistent queries and future enrichment. The log group has a
`CentralLoggingOptIn=true` tag as a declarative integration point for a
platform-owned forwarding service. This stack does not create that forwarding
pipeline.

## Security boundaries

- Bucket is private: block public access, owner-enforced, SSE-S3 encrypted, and
  versioned.
- Bucket policy denies all `s3:*` when `aws:SecureTransport` is false.
- The Lambda execution role trusts only the Lambda service and may
  `s3:GetObject` / `s3:GetObjectVersion` only on `incoming/*`; it has no S3
  write permissions.
- S3-to-Lambda invoke permission is constrained by source account and bucket ARN.
- Logs stay structured and free of payload contents.

The GitHub OIDC provider, deploy role, and CDK bootstrap roles are
account-provisioned controls outside this application stack. The workflow only
requests short-lived credentials from that existing trust boundary.

## Errors

| Class | Examples | Behavior |
| --- | --- | --- |
| Permanent | Unexpected key or record shape, oversized object, empty/multiline input, invalid UTF-8/JSON, non-object JSON | Logged as `rejected` with a reason code; other records in the same event continue |
| Operational | S3 read failures, unexpected service errors | Logged as `failed` with a safe exception class and no application traceback, then re-raised so the platform can retry |

The Lambda runtime can still emit its own standard record for an unhandled
exception after the function re-raises it. Application logs deliberately avoid
duplicating the exception message or traceback.

## Delivery semantics

S3 event notifications to Lambda are at-least-once. The same object create can
invoke more than once. This stack does not implement idempotency keys or
deduplication; treat processing as potentially repeated.

The handler reads the exact S3 version named by the event when one is present.
The retained bucket keeps noncurrent versions until an operator removes them;
add automatic expiration only after defining an approved retention period.

## Out of scope

Not implemented. Revisit when requirements demand them:

| Need | Candidate |
| --- | --- |
| Buffering, isolated retries, or poison-message handling | SQS between S3 and Lambda, plus a DLQ |
| Operator alerts on failures or throttling | CloudWatch alarms |
| Customer-managed encryption | KMS (SSE-KMS) on the bucket |
| Safe reprocessing of duplicate deliveries | Explicit idempotency (for example keyed by bucket/key/version) |
