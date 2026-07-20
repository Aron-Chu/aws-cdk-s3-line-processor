# Design

## Purpose

Stable runtime, security, networking, failure, and retention contract for the
S3 line processor.

## Who should use this

Contributors and maintainers evaluating application or infrastructure behavior.

## What this does not do

Does not grant access or deployment commands. See
[platform access](platform-access.md) and [operations](operations.md).

## System in one minute

An authorized uploader writes one JSON object on one line under `incoming/`,
with a key ending in `.json`. S3 invokes one Lambda. The Lambda reads the exact
object version when available, validates the input, and writes structured
metadata to CloudWatch Logs. It never logs the payload, JSON field names or
values, raw bucket/key, or S3 ETag.

AWS CDK defines the desired resources and synthesizes a CloudFormation template.
CloudFormation is the control plane that creates and updates the stack; CDK is
not a second runtime or deployment engine.

```text
authorized uploader
  -> private S3: prefix incoming/, suffix .json
  -> S3 ObjectCreated notification
  -> Python Lambda validation
  -> safe CloudWatch Logs metadata
```

## Runtime flow

1. A temporary-credential uploader writes an object under `incoming/` with a
   `.json` suffix over HTTPS.
2. S3 emits `s3:ObjectCreated:*` for the matching key and invokes the Lambda.
3. The Lambda reads at most `MAX_FILE_BYTES + 1` bytes and closes the body.
4. Valid input is logged as `processed`; malformed input is logged as
   `rejected`; AWS or unexpected service errors are logged safely and raised.

## Deployed resources

| Resource | Purpose | Important controls |
| --- | --- | --- |
| S3 input bucket | Store uploaded JSON and emit create notifications | Block Public Access, SSE-S3, versioning, owner-enforced ownership, retained |
| S3 bucket policy | Enforce transport security | Denies all S3 actions when `aws:SecureTransport` is false; retained |
| Lambda function | Read and validate each matching object | Python 3.14 ARM64, 256 MiB, 15-second timeout, no VPC |
| Lambda role | Give runtime permissions | Trusts only Lambda; reads only `incoming/*`; writes only to its log group |
| CloudWatch log group | Store structured runtime and application records | 14-day retention and `CentralLoggingOptIn=true` tag |
| Lambda permission | Let S3 invoke the function | Restricted by source account and bucket ARN |
| S3 notification | Connect object creation to Lambda | Prefix `incoming/`, suffix `.json` |
| Stack outputs | Let operators discover runtime names | Bucket and function names only |

The stack applies `Project`, `ManagedBy`, and `Environment=Sandbox` tags. The
GitHub environment named `production` is a deployment-control boundary; it does
not change the workload's current `Sandbox` tag or log field.

## Networking model

The stack creates no customer-managed VPC. Uploaders and the non-VPC Lambda use
AWS regional service endpoints over HTTPS; AWS manages service DNS, routing, and
transport termination. A private bucket is protected by IAM, Block Public
Access, and bucket policy. It is not a claim that the regional S3 endpoint is
reachable only through a private network.

S3-to-Lambda notification delivery is an AWS-managed service invocation, not a
customer-routed TCP connection. The Lambda resource policy still restricts the
source account and bucket ARN. A VPC, NAT gateway, security groups, Route 53,
and VPC endpoints would add no required protection for the current flow. Revisit
that decision only for private-resource access, a private-only upload path, or
explicit egress controls.

## Input contract

| Rule | Requirement |
| --- | --- |
| Key | Starts with `incoming/` and ends with `.json` |
| Size | At most `MAX_FILE_BYTES` (default 1 MiB) |
| Encoding | UTF-8 with an optional BOM |
| Shape | Exactly one JSON line; trailing `\n` or `\r\n` allowed |
| JSON | One object; no array, scalar, `NaN`, `Infinity`, or `-Infinity` |
| Rejected | Empty body, multiple lines, invalid UTF-8/JSON, or non-object JSON |

## Uploader access contract

**Platform prerequisite:** This stack intentionally creates no human or
workload uploader identity. The account owner supplies a temporary-credential
role outside this stack.

The minimum application capability is `s3:PutObject` on the deployed bucket's
`incoming/*.json` object ARN. In an S3 IAM resource ARN, `*` can match nested
key text; it is not limited to one path segment. Normal uploaders do not need
bucket listing, object reads, deletes, version deletion, IAM administration, or
log access. Cross-account uploads require an explicit bucket-policy decision
and are not part of the current design. Smoke operators have separate cleanup
permissions because the test creates and removes its own object versions.

## Security boundaries

- The bucket is private, TLS-only, owner-enforced, SSE-S3 encrypted, versioned,
  and retained.
- The Lambda role may call `s3:GetObject` and `s3:GetObjectVersion` only on
  `incoming/*`; it has no S3 write permission.
- S3 invocation is constrained by source account and bucket ARN.
- Account identities, GitHub OIDC, and CDK bootstrap roles are platform-owned
  and remain outside the application stack.
- Pull-request CI has no AWS credential path. Repository deployment obtains
  short-lived credentials only after the protected environment gate.

## Safe logging

Successful records include a SHA-256 `object_ref`, bounded version/sequencer
metadata, sizes, and `parsed_field_count`. `object_ref` uses length-delimited
bucket, decoded key, and version inputs, allowing retry correlation without raw
names. It is pseudonymous, not anonymous.

Logs exclude object contents, parsed values, JSON field names, raw bucket names,
raw keys, and S3 ETags. Invalid or oversized metadata is omitted. The ETag is
excluded because some upload types make it a content fingerprint.

Lambda's native JSON format provides an outer runtime envelope. The application
record is JSON inside the envelope's `message` field. Every application record
includes `service`, `environment`, and `log_schema_version=2`. The log group's
`CentralLoggingOptIn=true` tag is only an integration signal; this stack does
not create a forwarding pipeline.

## Failure behavior

| Class | Examples | Behavior |
| --- | --- | --- |
| Permanent rejection | Unexpected key/record, malformed Unicode bucket/key metadata, oversized object, empty or multiline input, invalid UTF-8/JSON, non-object JSON | Log `rejected` with a reason code and continue with other records |
| Invalid invocation envelope | Missing, empty, or non-list `Records` | Log `failed` with `failure_code=invalid_event_envelope`, then raise generic `OperationalError` |
| Operational error | S3 access denial, missing object/version, timeout, connection failure, throttling/5xx, or unexpected service/implementation error | Log `failed` with safe `error_type` plus allowlisted `failure_code`, then raise generic `OperationalError` for retry |

Malformed documents and malformed S3 record metadata are permanent rejections.
Invalid invocation envelopes and operational failures fail the whole invocation.
Direct S3-to-Lambda delivery retries at invocation scope; there is no partial-batch
acknowledgement protocol in this stack.

Operational logs use only stable allowlisted `failure_code` values
(`s3_access_denied`, `s3_object_unavailable`, `s3_timeout`,
`s3_service_unavailable`, `s3_service_error`, `unexpected_error`, and
`invalid_event_envelope`). Exception messages, raw AWS error codes, HTTP
headers, request/host IDs, endpoints, ARNs, account IDs, bucket names, object
keys, ETags, and uploaded data stay out of application logs. The original
service exception is not chained onto the raised `OperationalError`. The Lambda
runtime may still emit its standard record for the generic raised error.

All operational failures remain retryable until a durable failure destination is
designed. An on-failure destination and alarm remain future hardening, not
implemented behavior. Missing objects (`NoSuchKey` / `NoSuchVersion`) are not
treated as success because there is still no durable place to record permanent
operational loss.


## Delivery and retention

S3 notifications are at-least-once, so duplicate invocations are possible.
Today the only side effect is another validation log. Before adding a database
write or outbound call, introduce a durable idempotency decision.

The handler reads the event's exact S3 version when present. The retained,
versioned bucket prevents accidental data loss but grows until an approved
retention policy or explicit cleanup removes versions. Only incomplete
multipart uploads expire automatically after seven days.

The Lambda uses the boto3 version supplied by the AWS runtime. Development and
test SDK dependencies are pinned; vendor boto3 only when an exact runtime SDK
patch is more important than the larger asset and maintenance surface.

## Intentional omissions

| Omitted | Why not now | Reconsider when |
| --- | --- | --- |
| SQS and DLQ | Direct S3-to-Lambda is the required smallest path | Buffering, backpressure, poison isolation, or durable replay is required |
| Kinesis, Firehose, OpenSearch | Current output is operational logging; forwarding is platform-owned | Multiple real-time consumers or central logging requires it |
| VPC, NAT, endpoints | There is no private dependency | A private-only upload path, private dependency, or egress policy is required |
| Customer-managed KMS key | SSE-S3 meets the current encryption requirement | Compliance requires a customer-managed key |
| Alarms and reserved concurrency | Not required to prove the parser path | Operators need paging or explicit cost/concurrency guardrails |
| Idempotency store | Current processing has no side effect beyond logs | A database write or outbound side effect is added |
| Downstream sink | No destination or side-effect contract exists | Product requirements define schema, retries, and idempotency |
| Vendored boto3 | Runtime boto3 keeps the asset small | Exact SDK patch reproducibility is required |
| Object-version expiration | No retention period has been approved | Legal and operations approve deletion and recovery policy |
| Continuous drift detection | Merge-triggered changes are the current reconciliation model | Multiple operators or compliance justify scheduled detection |
| Stack termination protection | Retained data reduces accidental-loss risk | Control-plane deletion becomes an accepted operational risk |
| S3 data-event audit trail | Account-level audit logging is platform-owned and can add cost | Investigations or compliance require object-level API history |

These are explicit tradeoffs, not claims that the omitted controls are never
useful. Change them only with a requirement, owner, test, and operating plan.
