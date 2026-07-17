# Deployment and maintenance

Commands assume Ubuntu/WSL (or similar Linux).

## Prerequisites

- Git, GNU Make, Node.js 24+, AWS CLI, and either `uv` or Python 3.14
- Repository access to protected `main` and the GitHub `production` environment

## Local validation

```bash
make setup
make check
```

`make setup` creates a seeded Python 3.14 virtualenv, installs the hash-pinned
Python graph, runs `npm ci`, and enables pre-commit. `make check` runs lock,
lint, unit, coverage, and synth checks without AWS access.

`VENV`, `PROFILE`, `REGION`, and `STACK` may be overridden. If WSL inherits a
Windows temporary directory, set `TMPDIR=/tmp` before tests. Run `make help` for
individual targets.

## Deploy this repository: GitHub Actions

A merge to protected `main` starts Deploy; manual **Run workflow** also works.
Validation has no AWS access. The deploy job waits for **Approve** or **Reject**
on the GitHub `production` environment before obtaining credentials.

Required `production` environment variables:

| Variable | Purpose |
| --- | --- |
| `AWS_REGION` | Target region |
| `AWS_ROLE_ARN` | Deploy role assumed through OIDC |

The account must already have CDK bootstrap resources, a GitHub OIDC provider,
and a deploy role trusted only for:

- Audience: `sts.amazonaws.com`
- Subject: the exact `sub` claim for this repository's `production` environment

Do not use a wildcard subject or stored AWS keys. These account-level resources
are intentionally outside this application stack.

After approval the workflow shows `cdk diff`, then deploys. Run `make smoke`
separately with an approved operator profile; the deploy role does not need
application-data or log-reading permissions.

## External reviewer: deploy to your own sandbox

This path is for a fork or clone targeting the reviewer's AWS account. It does
not replace this repository's protected GitHub deployment path.

```bash
git clone https://github.com/Aron-Chu/aws-cdk-s3-line-processor.git
cd aws-cdk-s3-line-processor

export PROFILE=my-sandbox-profile
export REGION=us-west-2

make setup
make aws-check       # confirm the account before any write
make bootstrap       # once per account/region; skip if already bootstrapped
make deploy          # local checks, cdk diff, then normal CDK approval
make smoke           # nine live cases; deletes the versions it creates
```

The profile must be an approved non-root identity allowed to bootstrap and
deploy CDK in that sandbox. Smoke additionally needs scoped access to
`cloudformation:DescribeStacks`, `cloudformation:DescribeStackResources`,
`logs:FilterLogEvents`, `s3:PutObject`, and `s3:DeleteObjectVersion`. Teams
should separate deploy and smoke identities; one sandbox profile is sufficient
for a reviewer if it has both permission sets.

## Dependency maintenance

`requirements.txt` and `requirements-dev.txt` are the human-edited inputs.
`requirements.lock` pins the full transitive graph with hashes; local setup, CI,
and deploy install from that lockfile only.

After a Python pin change:

```bash
make setup
make lock
make check
```

Commit the input files and `requirements.lock` together. Node stays locked by
`package-lock.json`; Actions and pre-commit hooks have separate Dependabot
groups.

## Maintain

- Review Dependabot PRs and regenerate `requirements.lock` for Python changes.
- Run `make check` and review `make diff PROFILE=...` before sandbox deploys.
- Keep `architecture.excalidraw` and `architecture.svg` synchronized.

## Clean up

The bucket and TLS policy are retained. Discover the bucket, confirm the account
and that the bucket is dedicated to this stack, then clear its notification and
destroy the function:

```bash
export BUCKET="$(aws cloudformation describe-stacks \
  --stack-name S3LineProcessorStack \
  --profile "$PROFILE" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='InputBucketName'].OutputValue | [0]" \
  --output text)"

aws s3api put-bucket-notification-configuration \
  --bucket "$BUCKET" \
  --notification-configuration '{}' \
  --profile "$PROFILE" \
  --region "$REGION"

AWS_REGION="$REGION" npx cdk destroy --profile "$PROFILE"
```

Deleting the retained, versioned bucket is a separate destructive step. Remove
every object version and delete marker before deleting the empty bucket:

```bash
aws s3api list-object-versions \
  --bucket "$BUCKET" --profile "$PROFILE" --region "$REGION"

# Repeat for every VersionId and DeleteMarker.
aws s3api delete-object \
  --bucket "$BUCKET" \
  --key OBJECT_KEY \
  --version-id VERSION_ID \
  --profile "$PROFILE" \
  --region "$REGION"

aws s3api delete-bucket \
  --bucket "$BUCKET" --profile "$PROFILE" --region "$REGION"
```
