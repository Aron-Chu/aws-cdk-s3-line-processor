# Secure S3 Line Processor

Small AWS CDK example: one private S3 bucket invokes one Python 3.14 Lambda for
objects under `incoming/` whose keys end in `.json`. The Lambda validates
one-line JSON and writes safe processing metadata to CloudWatch Logs.

![Architecture](docs/architecture.svg)

Editable source: [docs/architecture.excalidraw](docs/architecture.excalidraw).

## Runtime in 60 seconds

1. An authorized uploader writes a JSON file to `incoming/` over TLS.
2. S3 invokes the Lambda for matching `.json` object-created events.
3. The Lambda reads at most 1 MiB, validates one JSON object on one line, and
   records structured metadata.
4. Invalid input is rejected permanently. AWS or service failures raise so the
   platform can retry.

The bucket is private, encrypted, owner-enforced, versioned, and retained. The
Lambda reads only `incoming/*` and cannot write to S3. Logs contain no payload,
JSON field names or values, raw bucket/key, or S3 ETag.

## Validate locally

```bash
make setup
make check
```

These commands install locked dependencies, run pre-commit, execute the test
suite with coverage, and synthesize CloudFormation without AWS access.

## Table of contents

| Need | Document |
| --- | --- |
| Understand architecture, security, networking, and tradeoffs | [Design](docs/design.md) |
| Contribute or review an agent-assisted change | [Contributing](CONTRIBUTING.md) |
| Deploy, smoke-test, diagnose, or clean up | [Operations](docs/operations.md) |
| Prepare AWS identities, CDK bootstrap, OIDC, and GitHub controls | [Platform access](docs/platform-access.md) |
| Review recorded local and live evidence | [Test results](docs/test-results.md) |
| Report a vulnerability privately | [Security](SECURITY.md) |
| Guide a coding agent working in this repository | [Agent guide](AGENTS.md) |

Documentation uses three labels: **Implemented** for verified current behavior,
**Platform prerequisite** for controls owned outside this stack, and **Future
hardening** for designs that are not yet implemented.
