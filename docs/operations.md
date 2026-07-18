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
individual targets. If Windows also exports `TMP` or `TEMP`, override all three:

```bash
TMPDIR=/tmp TMP=/tmp TEMP=/tmp make check
```

## Deploy this repository: GitHub Actions

Pull requests run credential-free CI. A merge to protected `main` starts Deploy
when infrastructure, runtime, dependency, or deploy-workflow paths change; its
validate job checks the exact merged commit before any AWS access.
Documentation-only merges do not start Deploy. Manual **Run workflow** also
works.

```text
validate (no AWS)
  -> Approve AWS plan preparation (no stack execution)
  -> prepare one CloudFormation change set
  -> review DescribeChangeSet artifact
     -> empty: stop
     -> changes: Approve exact plan execution
  -> verify artifact against AWS
  -> execute that exact ChangeSetId and wait
  -> operator runs make smoke separately
```

The plan job synthesizes once, publishes required CDK assets, and prepares a
commit/run-named change set without executing it. Its 30-day artifact contains
the stable, review-relevant fields from an account-redacted `DescribeChangeSet`
response plus a short resource table. Volatile response metadata such as the
creation timestamp and pagination token is excluded. A known CloudFormation
no-change result skips execute without parsing human CDK output.

The execute job intentionally has no checkout, Python, Node, dependency
installation, synthesis, or CDK command. After the second approval it:

1. downloads the plan artifact;
2. verifies the commit, redacted change-set ID, status, and nonempty plan;
3. obtains a new 15-minute OIDC session;
4. describes the live change set and compares both its immutable ID and its
   normalized, account-redacted review fields with the approved artifact; and
5. executes that ID with the AWS CLI and waits for CloudFormation.

This means the second approval authorizes an already-created plan.
`--require-approval never` only disables the CDK terminal prompt; it does not
bypass either GitHub environment approval.

Required `production` environment configuration:

| Kind | Name | Purpose |
| --- | --- | --- |
| Secret | `AWS_ROLE_ARN` | Existing OIDC role ARN; kept out of workflow logs |
| Secret | `AWS_ACCOUNT_ID` | Account allowlist and redaction/reconstruction value |
| Variable | `AWS_REGION` | Target AWS region |

The account must already have CDK bootstrap resources, a GitHub OIDC provider,
and a deploy role trusted only for:

- Audience: `sts.amazonaws.com`
- Subject: the exact `sub` claim for this repository's `production` environment

Do not use a wildcard subject or stored AWS keys. These account-level resources
are intentionally outside this application stack.

The role must retain the permissions already required by CDK asset publication
and change-set creation, plus `cloudformation:DescribeChangeSet`; execution also
requires `cloudformation:ExecuteChangeSet` and the stack waiter reads. Keep the
permissions resource-scoped wherever the CDK bootstrap model allows it.

### Current limitation and next hardening

Both protected jobs currently reference `production` and assume the same role.
The approval timing is real, but Approve #1 still releases a role capable of
execution. Do not hide this limitation in an interview.

The account/platform owner can close it without changing `stack.py`:

| Boundary | GitHub environment | OIDC role capability |
| --- | --- | --- |
| Plan | `production-plan` | Publish this stack's assets, create and describe its change set; deny execute |
| Execute | `production-execute` | Describe and execute the approved change set; cannot publish or create a replacement plan |

Give each environment its own exact OIDC `sub` trust, secret role ARN, required
reviewer policy, and no administrator bypass. The workflow should switch only
after both roles and environment protections exist; the application repository
must not create account-level GitHub trust or bootstrap roles.

For a team, require an independent reviewer and prevent self-review. A solo
repository can demonstrate the mechanics but cannot manufacture separation of
duties.

Run `make smoke` separately with an approved operator profile; the deploy role
does not need application-data or log-reading permissions. `--require-approval
never` is used only for the CDK CLI prompt because GitHub provides the prepare
and execute approval boundaries.

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
