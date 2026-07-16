# Secure S3 Line Processor

AWS CDK example: a private S3 bucket with a TLS-only bucket policy invokes a
Python 3.14 Lambda when objects land under `incoming/*.json`. The Lambda
validates one-line JSON and writes safe processing metadata to CloudWatch Logs.

![Architecture](docs/architecture.svg)

Editable source: [docs/architecture.excalidraw](docs/architecture.excalidraw).

## Key decisions

- Lambda reads only `incoming/*`; S3 invoke permission is constrained by source
  account and bucket ARN.
- S3→Lambda delivery is at-least-once; this stack does not deduplicate.
- Malformed input is rejected permanently; AWS/service failures retry. Logs contain
  safe processing metadata—no payload contents, parsed values, or JSON field names.

## Documentation

| Topic | Document |
| --- | --- |
| Deployment and maintenance | [docs/operations.md](docs/operations.md) |
| Design, security, and failure behavior | [docs/design.md](docs/design.md) |
| Live verification results | [docs/test-results.md](docs/test-results.md) |
| Contributor and agent guardrails | [AGENTS.md](AGENTS.md) |

Deploy, validate, smoke-test, and clean up using the
[operations guide](docs/operations.md).
