# Deployment and maintenance

## Prerequisites

- Python 3.14, Node.js 24+, AWS CLI, and an approved non-root AWS identity
- Repository access to protected `main` and the GitHub `production` environment

## Local validation

Shortcut (WSL/Linux):

```bash
make setup
make check
```

Equivalent manual steps:

```bash
python3.14 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
npm ci
pre-commit install

pre-commit run --all-files
pytest
npx cdk synth
```

## One-time CDK bootstrap

Bootstrap each account and region once with an approved non-root setup identity.
Replace placeholders before running:

```bash
npx cdk bootstrap aws://ACCOUNT_ID/AWS_REGION --profile ADMIN_PROFILE
```

## Deploy (recommended): GitHub Actions

Manual `Deploy` workflow from protected `main`, then approve the `production`
environment.

Required `production` environment variables (not secrets):

| Variable | Purpose |
| --- | --- |
| `AWS_REGION` | Target region |
| `AWS_ROLE_ARN` | Deploy role assumed via OIDC |

Trust the role for this repository and environment only:

- Audience: `sts.amazonaws.com`
- Subject: the exact `sub` claim GitHub emits for this repository's
  `production` environment

Some repositories use immutable owner and repository IDs in this claim. Verify
the emitted subject and do not use a wildcard. The workflow uses short-lived
OIDC credentials (`id-token: write`); do not store AWS access keys in GitHub.
The OIDC provider, deploy role, and CDK bootstrap roles are provisioned at the
AWS account level and are not created by this application stack.

Environment approval gates the job. Review a recent local or CI-synthesized
`cdk diff` before dispatching; the workflow also runs a live diff after
approval.

The GitHub environment is named `production` because it is the protected
deployment approval boundary. The sample workload remains classified as
`sandbox` in its resource tag and structured log context; these labels describe
different control-plane and workload concerns.

## Deploy (alternative): manual CDK

```bash
npx cdk diff --profile DEPLOY_PROFILE
npx cdk deploy --profile DEPLOY_PROFILE
```

## Discover stack resources

Replace `s3-line-processor-operator` with your local AWS CLI profile name (IAM
user or SSO). Do not use documentation placeholders such as `OPERATOR_PROFILE`.

```bash
STACK=S3LineProcessorStack
PROFILE=s3-line-processor-operator

BUCKET=$(aws cloudformation describe-stacks \
  --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='InputBucketName'].OutputValue" \
  --output text \
  --profile "$PROFILE")

FUNCTION=$(aws cloudformation describe-stacks \
  --stack-name "$STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='ProcessorFunctionName'].OutputValue" \
  --output text \
  --profile "$PROFILE")

LOG_GROUP=$(aws cloudformation describe-stack-resources \
  --stack-name "$STACK" \
  --query "StackResources[?ResourceType=='AWS::Logs::LogGroup' && contains(LogicalResourceId, 'ProcessorLogGroup')].PhysicalResourceId | [0]" \
  --output text \
  --profile "$PROFILE")

printf 'bucket=%s\nfunction=%s\nlog_group=%s\n' "$BUCKET" "$FUNCTION" "$LOG_GROUP"
```

## Smoke test

Manual single uploads (optional):

```bash
aws s3 cp samples/valid.json \
  "s3://${BUCKET}/incoming/smoke-valid.json" \
  --profile "$PROFILE"

aws logs tail "$LOG_GROUP" \
  --since 10m \
  --filter-pattern '"processed"' \
  --profile "$PROFILE"
```

```bash
aws s3 cp samples/invalid-json.json \
  "s3://${BUCKET}/incoming/smoke-invalid.json" \
  --profile "$PROFILE"

aws logs tail "$LOG_GROUP" \
  --since 10m \
  --filter-pattern '"rejected"' \
  --profile "$PROFILE"
```

Confirm logs show only safe metadata (bucket, key, status, reason codes) and no
uploaded field names or values. After the logging-contract deploy, each
application log should also include `service`, `environment`, and
`log_schema_version`.

Full post-deploy matrix:

```bash
make smoke PROFILE=s3-line-processor-operator
```

Helper parsing and placeholder rejection are covered by `make test`. The live
matrix requires a deployed stack whose Lambda matches the current logging
contract; otherwise outcome checks can pass while log-context checks fail.

## Maintain

- Review Dependabot updates before merging.
- After dependency or infrastructure changes, run local validation and an
  authenticated `cdk diff` before deploy.
- Keep `architecture.excalidraw` and `architecture.svg` synchronized.
- Use a read-only audit role for routine inspection.

## Clean up

The bucket and TLS policy are retained. Confirm the bucket is dedicated to this
stack, then clear its Lambda notification before destroying the function:

```bash
aws s3api put-bucket-notification-configuration \
  --bucket "$BUCKET" \
  --notification-configuration '{}' \
  --profile DEPLOY_PROFILE

npx cdk destroy --profile DEPLOY_PROFILE
```

Deleting the retained, versioned bucket is a separate destructive step. Confirm
the account and bucket name, remove every object version and delete marker, then
delete the empty bucket:

```bash
aws s3api list-object-versions \
  --bucket "$BUCKET" \
  --profile DEPLOY_PROFILE

# For each VersionId and DeleteMarker:
aws s3api delete-object \
  --bucket "$BUCKET" \
  --key OBJECT_KEY \
  --version-id VERSION_ID \
  --profile DEPLOY_PROFILE

aws s3api delete-bucket \
  --bucket "$BUCKET" \
  --profile DEPLOY_PROFILE
```
