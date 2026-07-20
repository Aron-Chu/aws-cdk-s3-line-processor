# Deployment and maintenance

## Purpose

Validate, deploy, observe, recover, and clean up this stack.

## Who should use this

Maintainers, deployment approvers, and smoke operators on Ubuntu/WSL or similar
Linux.

## What this does not do

Does not create AWS identities, OIDC trust, bootstrap roles, or GitHub
controls. See [platform access](platform-access.md).

## Prerequisites

- Git, GNU Make, Node.js 24+, AWS CLI v2, and either `uv` or Python 3.14.
- Review: repository access and default-branch workflow checks.
- Deploy approval: protected GitHub `production` environment.
- Live ops: approved temporary assumed-role profile for the intended
  account/region.

GitHub environment `production` is the deployment-control boundary. Current
stack resources and application logs are tagged `Sandbox`.

CLI placeholders used below: `<PROFILE>`, `<AWS_REGION>`, stack
`S3LineProcessorStack`. Pass `--profile` and `--region` on every AWS command.
Raw AWS CLI works from a laptop or CloudShell; only the repeated local paths
are Make targets (`make help`).

## Local validation

No AWS access required:

```bash
make setup
TMPDIR=/tmp TMP=/tmp TEMP=/tmp make check
```

`make setup` creates the Python 3.14 venv, installs the hash-pinned graph, runs
`npm ci`, and installs pre-commit. `make check` is lock + pre-commit + pytest
(with coverage) + `cdk synth`. The `/tmp` overrides keep WSL from handing Linux
tools a Windows temp path. Override `VENV`, `PROFILE`, `REGION`, or `STACK` as
needed.

Stop if the lock is stale, tests fail, the synthesized template is unreviewed,
or unexpected files are tracked.

## Contribution handoff

[Contributing](../CONTRIBUTING.md) owns branch, testing, agent, review, and PR
rules. Operations start only after a reviewed change reaches protected `main`.
A merged PR is repository evidence, not deployment evidence.

## Repository deployment

Relevant merges to protected `main` start Deploy; documentation-only merges do
not. Maintainers can also run the workflow manually from the default branch.
GitHub environment protection owns the human approvals; the workflow only
declares `environment: production`.

```text
validate (no AWS)
  -> approve plan
  -> synth (no AWS) -> 15-min OIDC -> publish asset + prepare change set
  -> review redacted DescribeChangeSet
       empty -> skip execute
       changes -> approve exact execute
  -> new 15-min OIDC -> compare live immutable change set -> execute
  -> authorized smoke (separate)
```

Plan may publish the Lambda asset to the bootstrap bucket but does not execute
the application change set. Execute has no checkout, install, synth, or CDK, so
it cannot build a replacement plan. New plan runs use the run attempt in
change-set and artifact names; rerunning only a failed execute reuses the
successful plan artifact.

After OIDC assume-role, plan and execute mask existing CloudFormation output
values in Actions logs. `--require-approval never` disables only CDK's
terminal prompt, not GitHub approvals.

Both protected jobs currently share one deploy-capable role. See [role
boundary](platform-access.md#current-role-boundary-and-future-hardening).

### Deploy procedure

1. Open the Deploy run for the merged commit; confirm `validate` passed.
2. Approve plan only if account, region, actor, and commit are correct.
3. Review the short change table and full redacted JSON artifact.
4. Stop on unexpected resource, replacement, IAM, deletion, or open questions.
5. Empty plan: confirm execute was skipped. Otherwise approve that exact ID.
6. Confirm execute compares the live plan and reaches the expected stack status.

```bash
gh run view <RUN_ID> --repo <OWNER>/<REPOSITORY> \
  --json headSha,event,status,conclusion,jobs,url
```

If plan cannot assume AWS, ask the platform owner to inspect trust; do not
replace OIDC with stored keys or broaden the role subject. Never approve an
artifact for the wrong commit or with unexplained IAM/replacement/deletion.

## Post-deploy smoke test

Shared-account smoke uses a scoped temporary assumed-role profile. Identity
Center is the preferred workforce path; this Sandbox may use an IAM role profile
with `source_profile` until Identity Center exists. Local bootstrap or
`cdk deploy` against the shared repository account is prohibited.

```bash
aws sts get-caller-identity --profile <SMOKE_PROFILE>
make smoke-check PROFILE=<SMOKE_PROFILE> REGION=<AWS_REGION>
# After explicit human authorization:
make smoke PROFILE=<SMOKE_PROFILE> REGION=<AWS_REGION>
```

`smoke-check` is read-only and does not prove S3 write or version cleanup.
`smoke` reruns preflight, prints the randomized `incoming/smoke-*` prefix
before uploads, then deletes only the exact versions it created (including on
mid-run failure). Permissions:
[Smoke Operator contract](platform-access.md#smoke-operator-permission-contract).

Expect an `assumed-role/...` caller in the intended account, nine application
outcomes, no sensitive log fields, and created versions removed. On expired
credentials, wrong stack/region, or a missing role permission, fix the scoped
role path; do not broaden access. If cleanup fails, delete only the printed
prefix's exact version IDs. Never empty the bucket.

## Safe observation

Resolve the log group from CloudFormation; do not hardcode the physical name:

```bash
export LOG_GROUP="$(aws cloudformation describe-stack-resources \
  --stack-name S3LineProcessorStack --profile <PROFILE> --region <AWS_REGION> \
  --query "StackResources[?ResourceType=='AWS::Logs::LogGroup'].PhysicalResourceId | [0]" \
  --output text)"

aws logs filter-log-events --log-group-name "$LOG_GROUP" \
  --profile <PROFILE> --region <AWS_REGION> --limit 20
```

Application JSON sits in Lambda's outer `message` field; approved fields are in
[design](design.md). Treat raw bucket/key, payload, field names, credentials, or
ETag in logs as a security issue.

## Failure diagnosis and recovery

```bash
aws cloudformation describe-stacks --stack-name S3LineProcessorStack \
  --profile <PROFILE> --region <AWS_REGION> \
  --query 'Stacks[0].StackStatus' --output text

aws cloudformation describe-stack-events --stack-name S3LineProcessorStack \
  --profile <PROFILE> --region <AWS_REGION> --max-items 20
```

| State | Action |
| --- | --- |
| `*_IN_PROGRESS` | Wait; do not start another deployment |
| `UPDATE_ROLLBACK_COMPLETE` | Fix via PR; prepare a new plan |
| `UPDATE_ROLLBACK_FAILED` | Escalate for reviewed continue-rollback parameters |
| Unexpected replacement/deletion | Stop; review approved plan and CloudTrail |

Authorized platform owner only:

```bash
aws cloudformation continue-update-rollback \
  --stack-name S3LineProcessorStack \
  --profile <PLATFORM_ADMIN_PROFILE> --region <AWS_REGION>
```

`--resources-to-skip` creates drift; do not guess the list. Never delete the
retained bucket, bypass GitHub controls, or force the stack green with an
unrecorded console edit.

## Dependency maintenance

Human-edit `requirements.txt` / `requirements-dev.txt`; `requirements.lock` is
the hashed graph for setup, CI, and deploy. Node stays on `package-lock.json`.

```bash
make setup && make lock && TMPDIR=/tmp TMP=/tmp TEMP=/tmp make check
```

Commit Python inputs and the lock together. Review Dependabot PRs; do not merge
on the bot label alone.

## Maintenance cadence

| When | Review |
| --- | --- |
| Every PR | Local validation, diff, security/architecture, doc ownership |
| Every deploy | Frozen plan, stack status, authorized smoke, dated evidence |
| Monthly | Dependabot, CodeQL, secret scanning, runtime/action support |
| Quarterly | Platform-access checklist, drift, retention decision |
| After incident | CloudTrail/events, credential exposure, rollback, corrective test |

Drift is manual today:

```bash
export DRIFT_ID="$(aws cloudformation detect-stack-drift \
  --stack-name S3LineProcessorStack \
  --profile <PLATFORM_AUDIT_PROFILE> --region <AWS_REGION> \
  --query StackDriftDetectionId --output text)"

aws cloudformation describe-stack-drift-detection-status \
  --stack-drift-detection-id "$DRIFT_ID" \
  --profile <PLATFORM_AUDIT_PROFILE> --region <AWS_REGION>
```

Record the result; do not reconcile via unreviewed console edits.

## Cleanup

Bucket and TLS policy are retained on stack destroy. Cleanup is destructive and
needs explicit authorization.

1. Confirm identity, region, stack, and bucket ownership.
2. Discover the bucket, clear notifications, then destroy:

```bash
export BUCKET="$(aws cloudformation describe-stacks \
  --stack-name S3LineProcessorStack \
  --profile <PLATFORM_ADMIN_PROFILE> --region <AWS_REGION> \
  --query "Stacks[0].Outputs[?OutputKey=='InputBucketName'].OutputValue | [0]" \
  --output text)"

aws s3api put-bucket-notification-configuration \
  --bucket "$BUCKET" --notification-configuration '{}' \
  --profile <PLATFORM_ADMIN_PROFILE> --region <AWS_REGION>

AWS_REGION=<AWS_REGION> npx cdk destroy --profile <PLATFORM_ADMIN_PROFILE>
```

Expect Lambda, role, and log group gone; versioned bucket and TLS policy remain.
If destroy fails because the notification still references the function, re-read
notification and stack events; do not empty the bucket. Stop if `$BUCKET` is
empty, unexpected, shared, or not dedicated to this stack.

### Delete retained data separately

```bash
aws s3api list-object-versions --bucket "$BUCKET" \
  --profile <PLATFORM_ADMIN_PROFILE> --region <AWS_REGION>

# After reviewing each key and version ID:
aws s3api delete-object --bucket "$BUCKET" \
  --key <OBJECT_KEY> --version-id <VERSION_ID> \
  --profile <PLATFORM_ADMIN_PROFILE> --region <AWS_REGION>

aws s3api delete-bucket --bucket "$BUCKET" \
  --profile <PLATFORM_ADMIN_PROFILE> --region <AWS_REGION>
```

No recursive delete, wildcards, `git clean`, or bulk scripts against retained
data without a separately reviewed inventory and recovery decision.

## Optional developer-owned AWS sandbox

Disposable developer account only. Never targets the shared repository account
or replaces protected-main deployment.

```bash
export PROFILE=<SANDBOX_PROFILE> REGION=<AWS_REGION>
export SANDBOX_ACK=developer-owned

make setup && make aws-check && make bootstrap && make deploy
make smoke-check && make smoke
```

`make deploy` runs check + `cdk diff` then interactive CDK approval. The ack
keeps local writes distinct from repository Deploy. `make bootstrap` writes
account-level resources; confirm the profile is the developer's own disposable
account first. Stop if `aws-check` shows the wrong account.
