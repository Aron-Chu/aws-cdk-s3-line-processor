# Platform access prerequisites

## Purpose

AWS account and GitHub controls required before this repository can deploy or
operate safely.

## Who should use this

AWS account owners and GitHub administrators. Contributors use
[contributing](../CONTRIBUTING.md); operators use
[operations](operations.md).

## What this does not do

Does not authorize creating identities, bootstrapping, changing GitHub
settings, or deploying. This application stack does not create administrators,
human access, OIDC, or bootstrap roles.

## What to do now

This public example is an operator **Sandbox**. Complete and verify these
boundaries in order:

| Boundary | Owner | Required now | Tighten later |
| --- | --- | --- | --- |
| Human AWS access | AWS account owner | Identity Center or scoped role assumption | Retire source keys after replacement access works |
| CDK bootstrap | Platform administrator | Approved execution policy and protection | Review as CDK requirements change |
| GitHub OIDC | Platform owner | Exact audience, subject, and short session | Split plan/execute roles for production |
| GitHub controls | Repository administrator | PR, `validate`, frozen-plan approvals | Add independent review when a second maintainer exists |
| Application access | Application owner / this stack | External scoped uploader; stack-managed Lambda role | Revisit only when the application contract changes |

Do not create a control before its owner, role, or recovery owner exists.
Root and long-lived IAM users are not routine maintenance identities.

This free-tier Sandbox may use IAM role assumption before Identity Center is
available. The smoke script still rejects IAM-user/root sessions; the effective
caller must be `assumed-role/...`.

## IAM Identity Center

Account owner enables Identity Center, requires MFA, assigns permission sets
through groups, and records an accountable owner. See
[AWS CLI SSO guidance](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html).

| Permission set | Minimum purpose |
| --- | --- |
| Platform administrator | Time-limited Identity Center, OIDC, bootstrap, and access administration |
| Read-only auditor | Inspect stack, IAM trust, bootstrap, CloudTrail, and integration settings |
| Smoke operator | Five-action contract below; no deploy or bootstrap |

### Smoke Operator permission contract

Provision this as a short-session Identity Center permission set, or as a
dedicated IAM role assumed from a narrow source profile while this remains a
Sandbox. Resolve the live log-group physical ID privately from the application
stack when building the set; never copy physical names, ARNs, or account IDs
into public docs.

| Action | Resource scope (placeholders) |
| --- | --- |
| `cloudformation:DescribeStacks` | Exact application stack |
| `cloudformation:DescribeStackResources` | Exact application stack |
| `logs:FilterLogEvents` | Exact application log group |
| `s3:PutObject` | `<BUCKET_ARN>/incoming/smoke-*/*` |
| `s3:DeleteObjectVersion` | `<BUCKET_ARN>/incoming/smoke-*/*` |

Include non-`.json` keys under the smoke prefix (the matrix uploads `test.txt`).
Do not grant deploy, bootstrap, IAM, Lambda, SSM, S3 list/read, broad
`incoming/*` cleanup, `s3:DeleteObject` without version IDs, or CloudFormation
mutation.

### Sandbox assumed-role profile

Without Identity Center, the account owner can create a private role with the
five-action contract above. Configure both sides with exact ARNs; never use a
wildcard principal or role resource.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "<SOURCE_PRINCIPAL_ARN>"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

The source identity needs only:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "<SMOKE_ROLE_ARN>"
    }
  ]
}
```

Local profile:

```ini
[profile smoke-s3-line]
role_arn = arn:aws:iam::<ACCOUNT_ID>:role/S3LineProcessorSmokeOperator
source_profile = <SOURCE_PROFILE>
region = <AWS_REGION>
```

```bash
aws sts get-caller-identity --profile smoke-s3-line
make smoke-check PROFILE=smoke-s3-line REGION=<AWS_REGION>
```

Expect `assumed-role/S3LineProcessorSmokeOperator/...` in the intended account.
Access denied means the trust, source permission, or five-action role policy is
incomplete. Stop on root, IAM-user, wrong account, or broader access. After an
authorized smoke succeeds, remove direct application permissions from the
source user. Disable its credentials only after replacement access works. See
[AWS CLI role profiles](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-role.html).

### Configure and verify an Identity Center profile

```bash
aws configure sso --profile <SSO_PROFILE>
aws sso login --profile <SSO_PROFILE>
aws sts get-caller-identity --profile <SSO_PROFILE>
aws configure get region --profile <SSO_PROFILE>
```

Expect the intended account and assumed role with an approved region. Refresh
expired SSO sessions with `aws sso login`; refresh source-profile credentials
only if they are the approved path to assume the smoke role. Stop on the wrong
account, root/IAM-user ARN, or a broader-than-approved set.

### Access lifecycle

- **Join:** Identity Center group; test the person's minimum task.
- **Review:** Quarterly, with the person's own session.
- **Leave:** Remove group assignments, AWS sessions, and GitHub access.

```bash
aws sso-admin list-account-assignments --instance-arn <INSTANCE_ARN> \
  --account-id <ACCOUNT_ID> --permission-set-arn <PERMISSION_SET_ARN> \
  --profile <PLATFORM_AUDIT_PROFILE>
```

Every assignment needs a current person, group, purpose, and owner. Missing
audit permission means unverified, not safe. Never share a cached token,
profile, access key, or account.

## CDK bootstrap

Bootstrap each deployment account and region once. CDK's modern default can
give CloudFormation `AdministratorAccess`; a production owner must approve a
narrower execution policy and termination protection. See the
[bootstrap command](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-bootstrap.html)
and [bootstrap maintenance](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping-env.html).

```bash
npx cdk bootstrap aws://<ACCOUNT_ID>/<AWS_REGION> \
  --profile <PLATFORM_ADMIN_PROFILE> --termination-protection \
  --cloudformation-execution-policies <EXECUTION_POLICY_ARN>
```

`make bootstrap PROFILE=<SSO_PROFILE> SANDBOX_ACK=developer-owned` is only for a
developer's own disposable sandbox (CDK defaults).

```bash
aws cloudformation describe-stacks --stack-name CDKToolkit \
  --profile <PLATFORM_AUDIT_PROFILE> --region <AWS_REGION> \
  --query 'Stacks[0].[StackStatus,EnableTerminationProtection]'

aws ssm get-parameter --name /cdk-bootstrap/hnb659fds/version \
  --profile <PLATFORM_AUDIT_PROFILE> --region <AWS_REGION> \
  --query 'Parameter.Value' --output text
```

Expect `CDKToolkit` complete, protected as approved, and new enough for this
CDK CLI. Access denied means unverified. Do not recreate or re-bootstrap until
the owner reviews the live template, trust, and parameters.

## GitHub OIDC and deploy role

Each protected job requests a 15-minute OIDC session, checks the allowed
account, masks its ID, and clears inherited credentials. GitHub stores no AWS
access key.

Provider URL: `https://token.actions.githubusercontent.com`. Role trust uses
`StringEquals`:

| Claim | Required value |
| --- | --- |
| `token.actions.githubusercontent.com:aud` | `sts.amazonaws.com` |
| `token.actions.githubusercontent.com:sub` | `<EXACT_GITHUB_ENVIRONMENT_SUB>` |

Use the exact subject for this repository's `production` environment, never
`repo:<OWNER>/<REPOSITORY>:*`. Verify the live claim; GitHub can include
immutable owner/repository IDs. See
[GitHub's AWS OIDC guidance](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).

```bash
aws iam get-open-id-connect-provider --open-id-connect-provider-arn <OIDC_PROVIDER_ARN> \
  --profile <PLATFORM_AUDIT_PROFILE>

aws iam get-role --role-name <GITHUB_DEPLOY_ROLE_NAME> \
  --profile <PLATFORM_AUDIT_PROFILE> \
  --query 'Role.AssumeRolePolicyDocument'
```

Expect exact audience and environment subject; no wildcard repository subject
or unrelated principal. A successful workflow proves assumption, not least
privilege. Never broaden trust to fix a failed assumption.

## GitHub repository and environment

Both protected jobs use `production`. The default-branch ruleset requires a PR,
current `validate`, linear history, and resolved review conversations; it
blocks deletion and force pushes. Actions use read-only defaults, approved
sources, and SHA-pinned actions.

The `production` environment must contain:

| Kind | Name |
| --- | --- |
| Secret | `AWS_ROLE_ARN` |
| Secret | `AWS_ACCOUNT_ID` |
| Variable | `AWS_REGION` |

It allows protected branches only, has an accountable reviewer, and disables
administrator bypass. These are GitHub settings, not workflow guarantees. See
[deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

```bash
gh api repos/<OWNER>/<REPOSITORY>/rulesets
gh api repos/<OWNER>/<REPOSITORY>/environments/production
gh api repos/<OWNER>/<REPOSITORY>/environments/production/secrets --jq '.secrets[].name'
gh api repos/<OWNER>/<REPOSITORY>/environments/production/variables --jq '.variables[].name'
```

Expect matching control names; never print secret values. Do not weaken rules
or environment protection to unblock a run.

## Current role boundary and future hardening

Plan and execute currently use the same deploy-capable role. The second
approval protects the frozen plan, but the first approval releases a role that
can also execute.

A real production workload can use `production-plan` to publish assets and
prepare (but never execute) a change set, and `production-execute` to execute
(but never replace) the approved plan. Each needs its own exact OIDC subject,
role secret, reviewer policy, and disabled administrator bypass. Do not change
the workflow before these exist.

## Quarterly access review

- Identity Center groups, MFA, permission sets, and unused sessions
- no routine root or IAM-user access keys
- OIDC audience, exact subject, role permissions, and last use
- bootstrap version, execution policy, and termination protection
- GitHub collaborators, ruleset, reviewers, bypass, and value names
- uploader and smoke permissions remain scoped to their stated purpose
