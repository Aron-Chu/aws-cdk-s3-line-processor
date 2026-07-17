# Reviewer guide

This page is the human-readable tour of the repository. Start here for a code
review or interview, then open the implementation files only when a question
needs more detail.

## The 60-second explanation

An uploader writes a one-line JSON object to `incoming/*.json` in a private,
versioned S3 bucket. S3 invokes one Python Lambda. The Lambda reads only that
object version, validates the size, UTF-8 encoding, line count, JSON syntax, and
top-level shape, then writes structured metadata to CloudWatch Logs. It never
logs the payload, JSON field names or values, raw bucket/key, or S3 ETag.

AWS CDK is the source-code layer used to define this system. `cdk synth` turns
the Python constructs into a CloudFormation template. CloudFormation—not the
GitHub runner or CDK library—is the AWS control plane that creates and updates
the resources.

Production delivery prepares one real CloudFormation change set. The reviewer
approves after that plan exists. The execute job does not rebuild anything; it
checks the commit, account-redacted change-set ID, and normalized review fields
against AWS, then executes that exact immutable change-set ID.

## CDK, CloudFormation, and the AWS services

| Layer | Responsibility | This repository |
| --- | --- | --- |
| AWS CDK | Defines infrastructure with normal programming-language constructs | `app.py`, `s3_line_processor/stack.py`, `cdk.json` |
| Cloud assembly | Local generated templates and asset manifests | `cdk.out/`; generated and never committed |
| CloudFormation | Calculates change sets and mutates AWS resources transactionally | `S3LineProcessorStack` |
| AWS services | Run the deployed workload | S3, Lambda, IAM, CloudWatch Logs |
| GitHub Actions | Validates Git, requests short-lived AWS credentials, and orchestrates prepare/execute | `.github/workflows/` |

CDK is not a second deployment engine. It synthesizes and publishes the Lambda
asset, then asks CloudFormation to prepare the plan. The execute job calls
CloudFormation directly so it cannot resynthesize a different template.

## Every deployed resource

| Resource | Why it exists | Important controls |
| --- | --- | --- |
| S3 input bucket | Stores uploaded JSON objects and emits create notifications | Block Public Access, SSE-S3, versioning, bucket-owner-enforced ownership, retained on stack deletion |
| S3 bucket policy | Enforces transport security | Explicitly denies all S3 actions when `aws:SecureTransport` is false; retained with the bucket |
| Lambda function | Reads and validates each matching object | Python 3.14 ARM64, 256 MiB, 15-second timeout, no VPC, structured JSON logging |
| Lambda execution role | Gives the function its runtime permissions | Trusts only Lambda; reads only `incoming/*`; writes only to its log group; no S3 writes |
| CloudWatch log group | Stores application and runtime records | 14-day retention, explicit resource, `CentralLoggingOptIn=true` tag |
| Lambda invoke permission | Allows the S3 service to invoke this function | Restricted by bucket ARN and AWS account, not a wildcard source |
| S3 notification | Connects object creation to the Lambda | Only `s3:ObjectCreated:*` keys with prefix `incoming/` and suffix `.json` |
| CloudFormation outputs | Lets operators discover runtime names | Bucket name and function name only |

The stack also applies `Project`, `ManagedBy`, and `Environment` tags. It does
not create a VPC, queue, database, API, KMS key, alarm, GitHub identity, or CDK
bootstrap role because none is required by the current contract.

## Runtime decisions

### Duplicate delivery

S3 notifications are at-least-once, so duplicate invocations are possible.
Today the only side effect is another validation log, so replay is safe. Before
adding a database write or outbound call, introduce an idempotency key derived
from bucket, key, and version ID and store the completion decision durably.

### Safe correlation

`object_ref` is a SHA-256 digest of length-delimited bucket, decoded key, and
version ID. It lets operators correlate retries without placing raw names in
logs. It is pseudonymous, not anonymous. ETag is deliberately excluded because
for some S3 uploads it can act as a content fingerprint.

### Error behavior

Invalid input is a permanent business rejection, so the handler logs a reason
code and continues to the next record. An S3 or unexpected service failure is
operational, so the handler emits a safe error class and raises a generic error
to let the platform retry.

### Retention and SDK choices

The bucket and its versions are retained to prevent accidental data loss. Only
incomplete multipart uploads expire after seven days. Production needs an
approved retention period before adding current/noncurrent version expiration.

The Lambda uses the boto3 supplied by the AWS Python runtime. The development
and test SDK is pinned, but the deployed SDK patch is controlled by AWS. Vendor
and pin boto3 when exact runtime SDK reproducibility outweighs the larger asset
and dependency-maintenance surface.

## File map

| File | What to say when asked |
| --- | --- |
| `app.py` | CDK entry point; creates the app and the single stack |
| `cdk.json` | Tells CDK how to run the app and pins reviewed feature-flag behavior |
| `s3_line_processor/stack.py` | Desired AWS resources, permissions, notifications, retention, outputs, and tags |
| `lambda_src/handler.py` | Runtime input contract, S3 read, safe logging, rejection, and retry semantics |
| `tests/test_stack.py` | Assertions that security controls survive refactoring in the synthesized template |
| `tests/test_handler.py` | Unit coverage for valid, malformed, sensitive, and operational cases |
| `scripts/live_smoke_test.py` | Post-deploy proof against real S3, Lambda, and CloudWatch Logs |
| `.github/workflows/ci.yml` | Credential-free pull-request and main validation |
| `.github/workflows/deploy.yml` | Protected prepare, review, exact execute, and no-op skip workflow |
| `Makefile` | Short, repeatable local validation, deployment, and smoke commands |
| `requirements.lock` / `package-lock.json` | Reproducible Python development and CDK CLI dependency graphs |

## Deployment in one screen

```text
relevant change reaches protected main
  -> validate (no AWS credentials)
  -> Approve plan
  -> OIDC session (15 minutes)
  -> synth + publish Lambda asset + prepare CloudFormation change set
  -> DescribeChangeSet JSON + short table
     -> empty plan: stop
     -> changes: Approve execute
  -> new OIDC session (15 minutes)
  -> download artifact + compare commit, ID, and reviewed fields with AWS
  -> execute that exact ChangeSetId + wait for CloudFormation
  -> operator runs make smoke with a separate identity
```

The plan phase is not completely read-only: CDK may publish the Lambda asset to
the bootstrap bucket before it creates the change set. It does not execute the
application stack change set.

## Questions a reviewer may press on

**Is this GitOps?** Git is the desired state, Actions/CDK translate it, and
CloudFormation is the only service that mutates the application stack. The
second approval is based on an already-prepared plan, so it is not an
approve-before-diff gate.

**Can Approve #2 deploy something else?** The execute job has no checkout,
synthesis, dependency installation, or CDK deployment. It reconstructs the
account-redacted ID using the protected account secret, compares the live ID and
normalized, redacted `DescribeChangeSet` fields with the artifact, and executes
that ID.

**Is plan/execute separation perfect?** Not yet. Both jobs currently use the
same protected environment and deploy-capable role, so Approve #1 technically
releases execute-capable credentials. The application stack must not create its
own GitHub trust. The next account-level hardening is two GitHub environments
and two OIDC roles: an asset/prepare role without execute, and an execute role
that cannot prepare a new plan.

**Why direct S3 to Lambda?** It is the assignment's smallest correct path. Add
SQS and a DLQ when buffering, backpressure, poison isolation, or replay becomes
a requirement.

**Why no VPC?** The function only calls an AWS regional public service endpoint
over TLS. A VPC would add networking and usually NAT cost without protecting a
private dependency that does not exist.

**Why retain the bucket?** Preventing accidental data loss is safer for this
example. The tradeoff is manual cleanup and indefinite growth until a real
retention policy is approved.

**Why not log the key or ETag?** Keys can contain sensitive business data and
ETags can fingerprint content. `object_ref`, version ID, sequencer, sizes, and
reason codes are sufficient for this example's operations.

**What proves the controls?** Unit tests verify parser and log behavior, CDK
assertion tests inspect the synthesized IAM and resource properties, CI runs
without AWS credentials, and the live smoke matrix exercises the deployed path.
