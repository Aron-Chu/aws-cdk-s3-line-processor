# Secure S3 Line Processor

AWS CDK example: a private S3 bucket with a TLS-only bucket policy invokes a
Python 3.14 Lambda when objects land under `incoming/*.json`. The Lambda
validates one-line JSON and writes safe processing metadata to CloudWatch Logs.

![Architecture](docs/architecture.svg)

Editable source: [docs/architecture.excalidraw](docs/architecture.excalidraw).

## Quickstart

```bash
make setup
make check
```

Deploy, smoke-test, and clean up: [docs/operations.md](docs/operations.md).

## Key decisions

- Lambda reads only `incoming/*`; S3 invoke permission is constrained by source
  account and bucket ARN.
- S3→Lambda delivery is at-least-once; this stack does not deduplicate.
- Malformed input is rejected permanently; AWS/service failures retry. Logs use a
  pseudonymous object reference and contain no raw bucket/key, payload contents,
  parsed values, or JSON field names.

## Review path

1. Architecture and behavior — this README and [docs/design.md](docs/design.md)
2. CDK stack — `s3_line_processor/stack.py`
3. Lambda handler — `lambda_src/handler.py`
4. CI and deploy workflows — `.github/workflows/`
5. Evidence — [docs/test-results.md](docs/test-results.md)

## Documentation

| Topic | Document |
| --- | --- |
| Deployment and maintenance | [docs/operations.md](docs/operations.md) |
| Design, security, and failure behavior | [docs/design.md](docs/design.md) |
| What was intentionally not added | [docs/intentional-omissions.md](docs/intentional-omissions.md) |
| Live verification results | [docs/test-results.md](docs/test-results.md) |
