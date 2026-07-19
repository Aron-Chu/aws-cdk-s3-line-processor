# Deployment and maintenance

## Purpose

Provide routine, repeatable procedures for validating, deploying, observing,
maintaining, recovering, and cleaning up the stack.

## Who should use this

Repository maintainers, deployment approvers, and IAM Identity Center smoke
operators. Commands assume Ubuntu/WSL or a similar Linux environment.

## What this does not do

This document does not create AWS identities, GitHub OIDC trust, CDK bootstrap
roles, repository rules, or environment protections. Platform owners prepare
those controls using [platform access](platform-access.md).

## Status labels

- **Implemented:** Verified repository or workflow behavior.
- **Platform prerequisite:** Required outside this stack.
- **Future hardening:** Designed but not yet implemented.

## Prerequisites

- Git, GNU Make, Node.js 24+, AWS CLI v2, and either `uv` or Python 3.14.
- For code review: repository access and the workflow checks required by the
  default-branch ruleset.
- For deployment approval: access to the protected GitHub `production`
  environment.
- For live operations: an approved IAM Identity Center profile for the intended
  account and region.

The GitHub environment name `production` describes the deployment-control
boundary. The current stack resources and application logs are tagged
`Sandbox`.

## Local validation

Local validation requires no AWS access:

```bash
make setup
TMPDIR=/tmp TMP=/tmp TEMP=/tmp make check
```

`make setup` creates a Python 3.14 virtual environment, installs the hash-pinned
Python graph, runs `npm ci`, and installs pre-commit. `make check` verifies the
lock, runs pre-commit and pytest with coverage, and synthesizes CloudFormation.

Run `make help` for individual targets. `VENV`, `PROFILE`, `REGION`, and `STACK`
may be overridden. The three `/tmp` overrides prevent WSL from passing an
unusable Windows temporary path to Linux tools.

**Expected result:** Every hook and test passes and CDK synthesizes one stack.

**Common failure:** If an absolute virtual environment is needed, pass it as
`VENV=/absolute/path`; the Makefile resolves its binary directory correctly.

**Stop condition:** Do not open or merge a PR with a stale lock, failing test,
unreviewed generated template change, or unexpected tracked file.

## Contribution handoff

[Contributing](../CONTRIBUTING.md) owns branch, testing, agent, review, and PR
requirements. Operations begin only after a reviewed change reaches protected
`main`. A merged pull request is repository evidence, not deployment evidence.

## Repository deployment

**Implemented:** Relevant changes merged to protected `main` start the Deploy
workflow. Documentation-only merges do not deploy. A maintainer can also run the
workflow manually from the default branch.

**Platform prerequisite:** GitHub environment protection supplies the human
approval gates. The workflow declares `environment: production` for both
protected jobs, but repository administrators own its reviewer assignments,
protected-branch rule, and administrator-bypass setting.

```text
validate exact merged commit without AWS
  -> approve plan preparation
  -> check out, install, and synthesize without AWS credentials
  -> obtain 15-minute OIDC session
  -> publish asset and prepare CloudFormation change set
  -> review account-redacted DescribeChangeSet artifact
     -> empty plan: skip execution
     -> changes: approve exact plan execution
  -> obtain a new 15-minute OIDC session
  -> compare artifact with the live immutable change set
  -> execute that ID and wait for the final stack status
  -> approved operator runs smoke separately
```

The plan phase may publish the Lambda asset to the CDK bootstrap bucket, but it
does not execute the application change set. The execute job has no checkout,
Python, Node, dependency installation, synthesis, or CDK command, so it cannot
build a replacement plan. Every newly run plan job uses its run attempt in the
change-set and artifact names. If GitHub reruns only a failed execute job, it
reuses the successful plan job's emitted artifact rather than creating a plan.

**Implemented:** After OIDC assumes the deploy role, plan and execute mask any
existing CloudFormation stack output values in Actions logs before CDK or
change-set mutation steps. Physical names are not credentials; masking reduces
unnecessary public disclosure.

`--require-approval never` disables only CDK's terminal prompt. It does not
bypass the protected GitHub environment approvals.

### Deploy procedure

1. Open the Deploy run for the merged commit.
2. Confirm the `validate` job passed for the expected commit.
3. Approve plan preparation only if the account, region, actor, and commit are
   correct.
4. Review the short change table and the complete redacted JSON artifact.
5. Stop on an unexpected resource, replacement, IAM change, deletion, or
   unresolved review question.
6. If the plan is empty, confirm execution was skipped.
7. If the plan is correct, approve execution of that exact change set.
8. Confirm the execute job compares the live plan and finishes with the expected
   CloudFormation status.

Read-only verification:

```bash
gh run view <RUN_ID> \
  --repo <OWNER>/<REPOSITORY> \
  --json headSha,event,status,conclusion,jobs,url
```

**Expected result:** The run is tied to the intended `main` commit; validation,
plan, and applicable execute jobs succeed. An empty plan skips execute.

**Common failure:** A plan job that cannot assume AWS may have an expired or
incorrect environment configuration. Do not replace OIDC with stored keys or
broaden the role subject; ask the platform owner to inspect the live trust.

**Stop condition:** Never approve an artifact that differs from the intended
commit or contains an unexplained IAM, replacement, or deletion change.

Both protected jobs currently use one deploy-capable role. See [the current
role boundary](platform-access.md#current-role-boundary-and-future-hardening)
for the risk and the future split-role design.

## Post-deploy smoke test

Shared-account smoke uses a scoped Identity Center profile. Local bootstrap or
`cdk deploy` against the shared repository account is prohibited.

```text
aws sso login
  -> make smoke-check
  -> human authorization
  -> make smoke
```

```bash
aws sso login --profile <SMOKE_SSO_PROFILE>
make smoke-check PROFILE=<SMOKE_SSO_PROFILE> REGION=<AWS_REGION>
# After explicit human authorization:
make smoke PROFILE=<SMOKE_SSO_PROFILE> REGION=<AWS_REGION>
```

`make smoke-check` is read-only and does **not** prove S3 write or
version-cleanup permissions. `make smoke` runs the same preflight, then uploads
under `incoming/smoke-*/*` and deletes only the exact versions it created.
The five-action permission contract is owned by
[platform access](platform-access.md#smoke-operator-permission-contract).

**Expected result:** Nine application outcomes; sensitive values absent from
logs; created versions removed.

**Common failure:** Expired SSO, wrong stack/region, or a missing platform
permission set. Do not grant broad access to unblock `smoke-check`.

**Stop condition:** If cleanup fails, remove only the reported version IDs. Do
not empty the bucket.

## Safe observation

Discover the log group from CloudFormation rather than hardcoding a physical
name:

```bash
export LOG_GROUP="$(aws cloudformation describe-stack-resources \
  --stack-name S3LineProcessorStack \
  --profile <READ_ONLY_SSO_PROFILE> \
  --region <AWS_REGION> \
  --query "StackResources[?ResourceType=='AWS::Logs::LogGroup'].PhysicalResourceId | [0]" \
  --output text)"

aws logs filter-log-events \
  --log-group-name "$LOG_GROUP" \
  --profile <READ_ONLY_SSO_PROFILE> \
  --region <AWS_REGION> \
  --limit 20
```

Application JSON is inside Lambda's outer `message` field. Approved fields are
documented in [the design](design.md). Stop and treat it as a security issue if
logs contain raw bucket/key, payload values, field names, credentials, or ETag.

## Failure diagnosis and recovery

Start read-only:

```bash
aws cloudformation describe-stacks \
  --stack-name S3LineProcessorStack \
  --profile <OPERATOR_SSO_PROFILE> \
  --region <AWS_REGION> \
  --query 'Stacks[0].StackStatus' \
  --output text

aws cloudformation describe-stack-events \
  --stack-name S3LineProcessorStack \
  --profile <OPERATOR_SSO_PROFILE> \
  --region <AWS_REGION> \
  --max-items 20
```

| State | Action |
| --- | --- |
| `*_IN_PROGRESS` | Wait; do not start another deployment |
| `UPDATE_ROLLBACK_COMPLETE` | Diagnose the failed resource, fix through a new PR, and prepare a new plan |
| `UPDATE_ROLLBACK_FAILED` | Escalate to the platform owner for reviewed continue-rollback parameters |
| Unexpected replacement/deletion | Stop and review the approved plan and CloudTrail before acting |

Only an authorized platform owner may resume a failed rollback:

```bash
aws cloudformation continue-update-rollback \
  --stack-name S3LineProcessorStack \
  --profile <PLATFORM_ADMIN_PROFILE> \
  --region <AWS_REGION>
```

**Expected result:** CloudFormation returns the stack to a stable rollback state;
a later fix still follows the normal PR and change-set workflow.

**Common failure:** A resource that cannot roll back may need specific
`--resources-to-skip`. Skipping resources creates drift; do not guess the list.

**Stop condition:** Never delete the retained bucket, bypass GitHub controls, or
make an unrecorded console edit to force the application stack green.

## Dependency maintenance

`requirements.txt` and `requirements-dev.txt` are human-edited inputs.
`requirements.lock` is the hashed transitive graph used by local setup, CI, and
deployment. Node dependencies remain pinned by `package-lock.json`.

After a Python dependency change:

```bash
make setup
make lock
TMPDIR=/tmp TMP=/tmp TEMP=/tmp make check
```

Commit Python inputs and `requirements.lock` together. Review Dependabot PRs for
Python, npm, GitHub Actions, and pre-commit; do not merge an update based only on
the bot label.

## Maintenance cadence

| When | Required review |
| --- | --- |
| Every PR | Full local validation, diff, security/architecture impact, documentation ownership |
| Every deployment | Frozen plan, final stack status, authorized smoke, dated evidence |
| Monthly | Dependabot, CodeQL, secret scanning, runtime and action support status |
| Quarterly | Platform-access checklist, drift, and retention decision |
| After an incident | CloudTrail and stack events, credential exposure, rollback evidence, corrective test |

Manual drift detection is not automated today:

```bash
export DRIFT_ID="$(aws cloudformation detect-stack-drift \
  --stack-name S3LineProcessorStack \
  --profile <PLATFORM_AUDIT_PROFILE> \
  --region <AWS_REGION> \
  --query StackDriftDetectionId \
  --output text)"

aws cloudformation describe-stack-drift-detection-status \
  --stack-drift-detection-id "$DRIFT_ID" \
  --profile <PLATFORM_AUDIT_PROFILE> \
  --region <AWS_REGION>
```

Record the result; do not reconcile drift through an unreviewed console edit.

## Cleanup

The bucket and TLS policy are retained when the stack is destroyed. Cleanup is
destructive and requires explicit authorization.

### Destroy control-plane resources while retaining data

1. Confirm identity, region, stack, and ownership of the bucket.
2. Discover the bucket through the stack output:

   ```bash
   export BUCKET="$(aws cloudformation describe-stacks \
     --stack-name S3LineProcessorStack \
     --profile <PLATFORM_ADMIN_PROFILE> \
     --region <AWS_REGION> \
     --query "Stacks[0].Outputs[?OutputKey=='InputBucketName'].OutputValue | [0]" \
     --output text)"
   ```

3. Clear the notification before destroying the function:

   ```bash
   aws s3api put-bucket-notification-configuration \
     --bucket "$BUCKET" \
     --notification-configuration '{}' \
     --profile <PLATFORM_ADMIN_PROFILE> \
     --region <AWS_REGION>

   AWS_REGION=<AWS_REGION> npx cdk destroy \
     --profile <PLATFORM_ADMIN_PROFILE>
   ```

**Expected result:** Lambda, role, and log group are removed; the versioned
bucket and TLS policy remain.

**Common failure:** Destroy can fail if the notification still references the
function. Re-read the bucket notification and stack events; do not empty the
bucket as a workaround.

**Stop condition:** Stop if the discovered bucket is empty, unexpected, shared,
or not dedicated to this stack.

### Delete retained data separately

List versions and delete markers first:

```bash
aws s3api list-object-versions \
  --bucket "$BUCKET" \
  --profile <PLATFORM_ADMIN_PROFILE> \
  --region <AWS_REGION>
```

Delete only reviewed keys and version IDs, then delete the empty bucket:

```bash
aws s3api delete-object \
  --bucket "$BUCKET" \
  --key <OBJECT_KEY> \
  --version-id <VERSION_ID> \
  --profile <PLATFORM_ADMIN_PROFILE> \
  --region <AWS_REGION>

aws s3api delete-bucket \
  --bucket "$BUCKET" \
  --profile <PLATFORM_ADMIN_PROFILE> \
  --region <AWS_REGION>
```

**Expected result:** Only explicitly reviewed versions are removed; bucket
deletion succeeds only when no object version or delete marker remains.

**Stop condition:** Do not use a recursive delete, wildcard, `git clean`, or a
bulk script against retained data without a separately reviewed inventory and
recovery decision.

## Optional developer-owned AWS sandbox

This appendix is only for a developer's disposable AWS account. It never targets
the shared repository account and never replaces protected-main deployment.

```bash
git clone https://github.com/Aron-Chu/aws-cdk-s3-line-processor.git
cd aws-cdk-s3-line-processor

export PROFILE=<SANDBOX_SSO_PROFILE>
export REGION=<AWS_REGION>
export SANDBOX_ACK=reviewer-owned

make setup
make aws-check
make bootstrap
make deploy
make smoke-check
make smoke
```

`make deploy` runs local checks and `cdk diff`, then uses the normal interactive
CDK approval. The acknowledgement prevents either local write command from
being mistaken for the repository deployment path. `make bootstrap` writes
account-level resources and can use broad CDK defaults; run it only after
confirming the identity is the developer's own disposable account.

**Expected result:** The developer owns all created resources and can reproduce
the live path independently.

**Common failure:** `aws-check` showing an unintended account means the profile
or cached session is wrong. Stop instead of overriding the account in a command.

**Stop condition:** Never point this path at the repository's shared account or
use it to bypass protected-main deployment.
