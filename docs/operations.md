# Deployment and maintenance

Local Make targets and examples assume **Ubuntu/WSL** (or similar Linux).

## Prerequisites

- Python 3.14, Node.js 24+, AWS CLI, and an approved non-root AWS identity
- Repository access to protected `main` and the GitHub `production` environment

## Local validation

```bash
make setup
make check
```

`make setup` creates a seeded Python 3.14 virtualenv (default `.venv`, override
with `VENV=`), installs hash-pinned deps from `requirements.lock`, runs
`npm ci`, and enables pre-commit. `make check` runs lock verification, lint,
tests, and `cdk synth`.

## Dependency maintenance

`requirements.txt` and `requirements-dev.txt` are the human-edited inputs.
`requirements.lock` pins the full transitive graph with hashes; local setup, CI,
and deploy install from that lockfile only.

After Dependabot or a manual pin change:

```bash
make setup
make lock
make check
```

Commit the input files and `requirements.lock` together. Node stays locked by
`package-lock.json`; Actions and pre-commit hooks have their own Dependabot
groups.

## One-time CDK bootstrap

Bootstrap each account/region once with an approved non-root setup identity:

```bash
npx cdk bootstrap aws://ACCOUNT_ID/AWS_REGION --profile ADMIN_PROFILE
```

## Deploy (recommended): GitHub Actions

Every push to protected `main` (and manual **Actions → Deploy → Run workflow**)
starts Deploy. The workflow checks out that `main` tip (all merged commits),
runs `validate`, then the `deploy` job waits for **Approve** or **Reject** on
the GitHub `production` environment before any AWS credentials or `cdk deploy`
steps run.

Required `production` environment variables (not secrets):

| Variable | Purpose |
| --- | --- |
| `AWS_REGION` | Target region |
| `AWS_ROLE_ARN` | Deploy role assumed via OIDC |

Trust the role for this repository and environment only:

- Audience: `sts.amazonaws.com`
- Subject: the exact `sub` claim for this repository's `production` environment

Do not use a wildcard subject. The workflow uses short-lived OIDC credentials
(`id-token: write`); do not store AWS access keys in GitHub. The OIDC provider,
deploy role, and CDK bootstrap roles are account-provisioned and are not created
by this application stack.

After approval the workflow shows a live `cdk diff`, then deploys. The GitHub
environment name `production` is the approval boundary; the sample workload
remains tagged/logged as `sandbox`.

## Deploy (alternative): manual CDK

```bash
npx cdk diff --profile DEPLOY_PROFILE
npx cdk deploy --profile DEPLOY_PROFILE
```

## Smoke test

Use a real local AWS CLI profile (IAM user or SSO), not a docs placeholder:

```bash
make smoke PROFILE=s3-line-processor-operator
```

The script discovers stack outputs, uploads the nine-case matrix under
`incoming/smoke-*`, checks CloudWatch outcomes and log context, and deletes the
created object versions when `--cleanup` is set (default via Make).

## Maintain

- Review Dependabot PRs; regenerate `requirements.lock` when Python pins change.
- After infrastructure changes, run `make check` and review `cdk diff` before
  deploy.
- Keep `architecture.excalidraw` and `architecture.svg` synchronized.

## Clean up

The bucket and TLS policy are retained. Confirm the bucket is dedicated to this
stack, clear its Lambda notification, then destroy the function:

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
aws s3api list-object-versions --bucket "$BUCKET" --profile DEPLOY_PROFILE

# For each VersionId and DeleteMarker:
aws s3api delete-object \
  --bucket "$BUCKET" \
  --key OBJECT_KEY \
  --version-id VERSION_ID \
  --profile DEPLOY_PROFILE

aws s3api delete-bucket --bucket "$BUCKET" --profile DEPLOY_PROFILE
```
