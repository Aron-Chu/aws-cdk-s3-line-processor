# Secure S3 Line Processor

An AWS CDK example that creates a private S3 bucket and a Python Lambda.
Files uploaded to `incoming/*.json` are read as one-line JSON objects and
recorded as safe processing metadata in CloudWatch Logs.

![Architecture](docs/architecture.svg)

Editable source: [docs/architecture.excalidraw](docs/architecture.excalidraw).

```text
HTTPS upload
     ↓
Private, encrypted, versioned S3 bucket
     ↓ ObjectCreated: incoming/*.json
Python Lambda with read-only object access
     ↓
CloudWatch Logs without uploaded contents
```

See [deployment and maintenance](docs/operations.md) for setup, validation,
deployment, smoke testing, and cleanup.
