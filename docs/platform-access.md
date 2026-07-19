# Platform access prerequisites

## Purpose

Define the AWS account and GitHub controls required before this repository can
deploy or operate safely.

## Who should use this

AWS account owners and GitHub administrators. Contributors use
[contributing](../CONTRIBUTING.md); operators use
[operations](operations.md).

## What this does not do

This guide does not authorize an agent or contributor to create identities,
bootstrap an account, change GitHub settings, or deploy. The application stack
does not create administrators, human access, GitHub OIDC, or bootstrap roles.

Labels used below: **Implemented** is repository behavior, **Platform
prerequisite** is externally owned, and **Future hardening** is not active.

## What to do now

This public example is a reviewer **Sandbox**. Complete and verify these
boundaries in order:

| Boundary | Owner | Required now | Tighten later |
| --- | --- | --- | --- |
| Human AWS access | AWS account owner | Identity Center groups and temporary sessions | Remove old keys after SSO works |
| CDK bootstrap | Platform administrator | Approved execution policy and protection | Review as CDK requirements change |
| GitHub OIDC | Platform owner | Exact audience, subject, and short session | Split plan/execute roles for production |
| GitHub controls | Repository administrator | PR, `validate`, frozen-plan approvals | Add independent review when a second maintainer exists |
| Application access | Application owner / this stack | External scoped uploader; stack-managed Lambda role | Revisit only when the application contract changes |

Do not create a control before its reviewer, role, or recovery owner exists.
Root and long-lived IAM users are not routine maintenance identities.

## IAM Identity Center

**Platform prerequisite:** The account owner enables Identity Center, requires
MFA, assigns permission sets through groups, and records an accountable owner.
Use the current
[AWS CLI SSO guidance](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html).

| Permission set | Minimum purpose |
| --- | --- |
| Platform administrator | Time-limited Identity Center, OIDC, bootstrap, and access administration |
| Read-only auditor | Inspect stack, IAM trust, bootstrap, CloudTrail, and integration settings |
| Smoke operator | Describe this stack, read its logs, upload smoke objects, and delete only smoke-created versions |

### Configure and verify a profile

```bash
aws configure sso --profile <SSO_PROFILE>
aws sso login --profile <SSO_PROFILE>
aws sts get-caller-identity --profile <SSO_PROFILE>
aws configure get region --profile <SSO_PROFILE>
```

| Check | Meaning |
| --- | --- |
| **Expected** | STS shows the intended account and assumed role; the region is approved |
| **Verify** | `aws sts get-caller-identity --profile <SSO_PROFILE>` is read-only |
| **Common failure** | Refresh an expired session with `aws sso login`; do not substitute an access key |
| **Stop** | Stop on the wrong account, root/IAM-user ARN, or broader-than-approved permission set |

### Access lifecycle

- **Join:** Use an Identity Center group and test the person's minimum task.
- **Review:** Check assignments quarterly with the person's own session.
- **Leave:** Remove group assignments, AWS sessions, and GitHub access.

Verify assignments read-only:

```bash
aws sso-admin list-account-assignments --instance-arn <INSTANCE_ARN> \
  --account-id <ACCOUNT_ID> --permission-set-arn <PERMISSION_SET_ARN> \
  --profile <PLATFORM_AUDIT_PROFILE>
```

**Expected:** Every assignment has a current person, group, purpose, and owner.
**Failure/stop:** Missing audit permission means unverified, not safe; never
share a cached token, profile, access key, or account.

## CDK bootstrap

**Platform prerequisite:** Bootstrap each deployment account and region once.
CDK's modern default can give CloudFormation `AdministratorAccess`; a production
owner must approve a narrower execution policy and termination protection. See
the [bootstrap command](https://docs.aws.amazon.com/cdk/v2/guide/ref-cli-cmd-bootstrap.html)
and [bootstrap maintenance](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping-env.html).

Owner-approved production example:

```bash
npx cdk bootstrap aws://<ACCOUNT_ID>/<AWS_REGION> \
  --profile <PLATFORM_ADMIN_PROFILE> --termination-protection \
  --cloudformation-execution-policies <EXECUTION_POLICY_ARN>
```

`make bootstrap PROFILE=<SSO_PROFILE> SANDBOX_ACK=reviewer-owned` is only for an
external reviewer's own sandbox; it uses CDK defaults.

Read-only verification:

```bash
aws cloudformation describe-stacks --stack-name CDKToolkit \
  --profile <PLATFORM_AUDIT_PROFILE> --region <AWS_REGION> \
  --query 'Stacks[0].[StackStatus,EnableTerminationProtection]'

aws ssm get-parameter --name /cdk-bootstrap/hnb659fds/version \
  --profile <PLATFORM_AUDIT_PROFILE> --region <AWS_REGION> \
  --query 'Parameter.Value' --output text
```

**Expected:** `CDKToolkit` is complete, protected as approved, and new enough
for this CDK CLI. **Common failure:** Access denied means the configuration is
unverified. **Stop:** Do not recreate or re-bootstrap it until the owner reviews
the live template, trust, and parameters.

## GitHub OIDC and deploy role

**Implemented:** Each protected job requests a 15-minute OIDC session, checks
the allowed account, masks its ID, and clears inherited credentials. GitHub
stores no AWS access key.

**Platform prerequisite:** The account has provider URL
`https://token.actions.githubusercontent.com`. Role trust uses `StringEquals`:

| Claim | Required value |
| --- | --- |
| `token.actions.githubusercontent.com:aud` | `sts.amazonaws.com` |
| `token.actions.githubusercontent.com:sub` | `<EXACT_GITHUB_ENVIRONMENT_SUB>` |

Use the exact subject for this repository's `production` environment, never
`repo:<OWNER>/<REPOSITORY>:*`. Verify the live claim because GitHub can include
immutable owner/repository IDs. See
[GitHub's AWS OIDC guidance](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).

Read-only verification:

```bash
aws iam get-open-id-connect-provider --open-id-connect-provider-arn <OIDC_PROVIDER_ARN> \
  --profile <PLATFORM_AUDIT_PROFILE>

aws iam get-role --role-name <GITHUB_DEPLOY_ROLE_NAME> \
  --profile <PLATFORM_AUDIT_PROFILE> \
  --query 'Role.AssumeRolePolicyDocument'
```

**Expected:** Exact audience and environment subject; no wildcard repository
subject or unrelated principal. **Common failure:** A successful workflow proves
assumption, not least privilege. **Stop:** Never broaden trust to fix a failed
assumption; compare the real claim, environment, and immutable IDs.

## GitHub repository and environment

**Implemented:** Both protected jobs use `production`. The default-branch
ruleset requires a PR, current `validate`, linear history, and resolved review
conversations; it blocks deletion and force pushes. Actions use read-only
defaults, approved sources, and SHA-pinned actions.

**Platform prerequisite:** The `production` environment contains:

| Kind | Name |
| --- | --- |
| Secret | `AWS_ROLE_ARN` |
| Secret | `AWS_ACCOUNT_ID` |
| Variable | `AWS_REGION` |

It allows protected branches only, has an accountable reviewer, and disables
administrator bypass. These are GitHub settings, not workflow guarantees. See
[deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

Read-only verification:

```bash
gh api repos/<OWNER>/<REPOSITORY>/rulesets
gh api repos/<OWNER>/<REPOSITORY>/environments/production
gh api repos/<OWNER>/<REPOSITORY>/environments/production/secrets --jq '.secrets[].name'
gh api repos/<OWNER>/<REPOSITORY>/environments/production/variables --jq '.variables[].name'
```

**Expected:** Controls and names match; secret values are never printed.
**Common failure:** A solo maintainer cannot create independent review. **Stop:**
Do not weaken rules or environment protection to unblock a run.

## Known limitation: shared deploy role

**Implemented:** Plan and execute currently use the same deploy-capable role.
The second approval protects the frozen plan, but the first approval releases a
role that can also execute.

**Future hardening:** A real production workload can use `production-plan` to
publish assets and prepare—but never execute—a change set, and
`production-execute` to execute—but never replace—the approved plan. Each needs
its own exact OIDC subject, role secret, reviewer policy, and disabled
administrator bypass. Do not change the workflow before these exist.

## Quarterly access review

- Identity Center groups, MFA, permission sets, and unused sessions;
- no routine root or IAM-user access keys;
- OIDC audience, exact subject, role permissions, and last use;
- bootstrap version, execution policy, and termination protection;
- GitHub collaborators, ruleset, reviewers, bypass, and value names; and
- uploader and smoke permissions remain scoped to their stated purpose.
