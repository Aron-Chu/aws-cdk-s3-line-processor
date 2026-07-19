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

## Deploy and maintain

Protected `main` runs credential-free validate, then an OIDC plan that prepares
one CloudFormation change set; an empty plan skips execute. Smoke is a separate,
explicitly authorized step—see [Operations](docs/operations.md). Bootstrap is an
account/region prerequisite ([Platform access](docs/platform-access.md)).
Optional own-account sandbox lives in Operations; never use it against the
shared repository account.

## Docs

- [Design](docs/design.md)
- [Contributing](CONTRIBUTING.md)
- [Operations](docs/operations.md)
- [Platform access](docs/platform-access.md)
- [Test results](docs/test-results.md)
- [Security](SECURITY.md)
- [Agent guide](AGENTS.md)
