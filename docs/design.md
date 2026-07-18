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

Successful logs include a SHA-256 `object_ref`, version/sequencer metadata,
sizes, and `parsed_field_count`. The reference is derived from bucket, decoded
key, and version ID with length-delimited inputs, so repeated delivery of the
same object version remains correlatable without logging the raw bucket or key.
It is pseudonymous correlation metadata, not a claim of irreversible
anonymization. Logs never include object contents, parsed values, field names,
raw bucket names, or raw object keys.
S3 ETag is also excluded because it can act as a content fingerprint for some
uploads.

Lambda's native JSON format creates an outer runtime envelope; the application
record is serialized inside its `message` field and the smoke helper unwraps it.
Every application entry carries `service`, `environment`, and
`log_schema_version=2` fields for consistent queries and future enrichment. The
log group has a `CentralLoggingOptIn=true` tag as a declarative integration
point for a platform-owned forwarding service. This stack does not create that
forwarding pipeline.

## Security boundaries

- Bucket is private: block public access, owner-enforced, SSE-S3 encrypted, and
  versioned.
- Bucket policy denies all `s3:*` when `aws:SecureTransport` is false.
- The Lambda execution role trusts only the Lambda service and may
  `s3:GetObject` / `s3:GetObjectVersion` only on `incoming/*`; it has no S3
  write permissions.
- S3-to-Lambda invoke permission is constrained by source account and bucket ARN.
- Logs stay structured and free of raw bucket/key and payload contents.

The GitHub OIDC provider, deploy role, and CDK bootstrap roles are
account-provisioned controls outside this application stack. The workflow only
requests short-lived credentials from that existing trust boundary.

## Errors

| Class | Examples | Behavior |
| --- | --- | --- |
| Permanent | Unexpected key or record shape, oversized object, empty/multiline input, invalid UTF-8/JSON, non-object JSON | Logged as `rejected` with a reason code; other records in the same event continue |
| Operational | S3 read failures, unexpected service errors | Logged as `failed` with a safe exception class and no application traceback, then converted to a generic `OperationalError` so the platform retries without emitting the original exception message |

The Lambda runtime can still emit its own standard record for the generic
`OperationalError`. The original SDK/service exception message and traceback
are deliberately not chained because they could contain a bucket, key, or
endpoint URL.

## Delivery semantics

S3 event notifications to Lambda are at-least-once. The same object create can
invoke more than once. This stack does not implement idempotency keys or
deduplication; treat processing as potentially repeated.

The handler reads the exact S3 version named by the event when one is present.
The retained bucket keeps noncurrent versions until an operator removes them;
add automatic expiration only after defining an approved retention period.

## Out of scope

Services and patterns intentionally not implemented are listed in
[intentional-omissions.md](intentional-omissions.md).
