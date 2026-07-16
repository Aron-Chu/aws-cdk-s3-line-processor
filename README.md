# Secure S3 Line Processor

A small AWS CDK v2 application that sends S3 object-created events directly to
a Python 3.14 Lambda. The function validates one-line JSON files and writes
safe structured metadata to CloudWatch Logs.

![Secure S3 line processor architecture](docs/architecture.svg)

The editable diagram is
[docs/architecture.excalidraw](docs/architecture.excalidraw).

## How it works

1. Upload a file to `incoming/*.json` over HTTPS.
2. S3 invokes Lambda with an object-created event.
3. Lambda reads the exact object version when the event provides one.
4. The function validates the file and logs `processed` or `rejected`.
5. AWS service failures are raised so the event can be retried.

The input must be at most 1 MiB, valid UTF-8, and contain exactly one
non-empty logical line with a top-level JSON object. One trailing newline is
allowed.

```json
{"event_id":"example-001","message":"hello","source":"manual-test"}
```

Arrays, primitives, malformed JSON, multiline JSON, invalid UTF-8, `NaN`, and
`Infinity` are rejected. Examples are available in `samples/`.

## Security

- S3 is private, encrypted with SSE-S3, versioned, owner-enforced, and covered
  by Block Public Access.
- An explicit bucket policy denies all non-TLS S3 requests.
- The bucket and its TLS policy are retained when the stack is deleted.
- Lambda can only read `incoming/*`; it has no S3 write permission.
- S3 invocation is constrained by source bucket and account.
- Lambda writes only to its dedicated log group.
- Logs exclude uploaded content, parsed values, and field names.
- Pull-request CI has no AWS access.
- Production deployment uses short-lived GitHub OIDC credentials, protected
  `main`, and a reviewer-gated `production` environment.

Account-level administration, the GitHub OIDC provider, deployment role, and
CDK bootstrap roles are intentionally outside this application stack. The
default CDK bootstrap uses an administrator CloudFormation execution role;
shared or regulated accounts should replace that default with approved
policies and guardrails.

## Project layout

- `s3_line_processor/stack.py` — bucket, policy, Lambda, IAM, notification, and
  outputs.
- `lambda_src/handler.py` — bounded S3 read and strict input validation.
- `tests/` — mocked handler tests and CDK template assertions.
- `docs/` — editable Excalidraw source and SVG export.
- `samples/` — valid and invalid inputs.
- `.github/workflows/` — pull-request validation and manual OIDC deployment.
- `AGENTS.md` — concise repository and SDLC guardrails.

Dependencies and tool versions are pinned in `requirements*.txt`,
`package.json`, `.python-version`, and `.pre-commit-config.yaml`.

## Set up and validate

Prerequisites are Python 3.14, Node.js 24, and AWS CLI v2 for authenticated
operations.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci
pre-commit install

pre-commit run --all-files
ruff format --check .
ruff check .
pytest
npx cdk synth
```

Tests and synthesis require no AWS credentials. Before deployment, review the
authenticated diff:

```bash
npx cdk diff --profile DEPLOY_PROFILE
```

## Deploy

Bootstrap each target account and region once with an approved non-root setup
identity:

```bash
npx cdk bootstrap aws://ACCOUNT_ID/AWS_REGION --profile ADMIN_PROFILE
```

Manual deployment:

```bash
npx cdk deploy --profile DEPLOY_PROFILE
```

The optional `Deploy` GitHub Actions workflow:

- runs only through `workflow_dispatch` from the default branch;
- requires approval of the `production` environment;
- reruns formatting, linting, tests, and synthesis;
- assumes `GitHubCdkDeployRole` through OIDC;
- shows `cdk diff` before deployment; and
- prevents overlapping production deployments.

Configure these non-secret `production` environment variables:

```text
AWS_REGION
AWS_ROLE_ARN
```

The role trust must require audience `sts.amazonaws.com` and the exact subject:

```text
repo:OWNER/REPOSITORY:environment:production
```

Do not store AWS access keys in GitHub.

## Operate

CDK outputs the bucket and function names. Upload a valid sample:

```bash
aws s3 cp samples/valid.json \
  s3://BUCKET_NAME/incoming/example.json \
  --profile OPERATOR_PROFILE
```

Inspect recent processing results:

```bash
aws logs tail /aws/lambda/FUNCTION_NAME \
  --since 10m \
  --profile OPERATOR_PROFILE
```

A valid file logs `status: processed`. Permanent input errors log
`status: rejected` with a safe reason code.

## Maintain

- Dependabot proposes pinned pip, npm, and GitHub Actions updates.
- CodeRabbit provides advisory review; required CI remains authoritative.
- Pre-commit runs file hygiene, Ruff, and Gitleaks checks.
- After dependency or infrastructure changes, run pre-commit, Pytest,
  `cdk synth`, and an authenticated `cdk diff`.
- Keep both architecture files aligned with the deployed design.
- Use a read-only audit role for routine AWS inspection rather than an
  administrator identity.

## Clean up

The versioned bucket and TLS policy are retained. Clear the retained S3
notification before deleting the Lambda:

```bash
aws s3api put-bucket-notification-configuration \
  --bucket BUCKET_NAME \
  --notification-configuration '{}' \
  --profile DEPLOY_PROFILE

npx cdk destroy --profile DEPLOY_PROFILE
```

Deleting the retained bucket is a separate destructive operation. List and
remove every object version and delete marker before deleting it:

```bash
aws s3api list-object-versions \
  --bucket BUCKET_NAME \
  --profile DEPLOY_PROFILE
```

Confirm the account and bucket name before removing retained data.

## Known limitations

- S3 notifications are at-least-once and can arrive out of order.
- Invalid files remain in the input bucket.
- There is no queue, DLQ, replay store, quarantine, or idempotency database.
- One operational record failure causes AWS to retry the invocation.
- A production workload may add those controls when reliability requirements
  justify the additional complexity.
