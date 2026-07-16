# Secure S3 Line Processor

Private S3 bucket → Python Lambda. Uploads under `incoming/*.json` are validated as one-line JSON and logged safely.

![Architecture](docs/architecture.svg)

Editable source: [docs/architecture.excalidraw](docs/architecture.excalidraw).

```text
uploader --HTTPS--> S3 (private, SSE-S3, versioned, TLS-only, RETAIN)
                         |
                         | ObjectCreated (incoming/*.json)
                         v
                   Lambda (read-only incoming/*, own logs)
                         |
                         v
                   CloudWatch Logs (no object contents)

deploy: protected main → production approval → GitHub OIDC
        → GitHubCdkDeployRole → CDK bootstrap roles → CloudFormation
```

## Deploy and maintain

```bash
# local
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && npm ci && pre-commit install
pre-commit run --all-files && pytest && npx cdk synth

# one-time account setup (outside this stack)
npx cdk bootstrap aws://ACCOUNT_ID/AWS_REGION --profile ADMIN_PROFILE

# deploy
npx cdk diff --profile DEPLOY_PROFILE
npx cdk deploy --profile DEPLOY_PROFILE
# or: Actions → Deploy (workflow_dispatch on main, approve production)

# smoke test
aws s3 cp samples/valid.json s3://BUCKET/incoming/example.json --profile OPERATOR_PROFILE
aws logs tail /aws/lambda/FUNCTION --since 10m --profile OPERATOR_PROFILE

# cleanup (bucket + TLS policy are retained)
aws s3api put-bucket-notification-configuration \
  --bucket BUCKET --notification-configuration '{}' --profile DEPLOY_PROFILE
npx cdk destroy --profile DEPLOY_PROFILE
```

GitHub `production` needs non-secret `AWS_REGION` and `AWS_ROLE_ARN`. Role trust:

`repo:OWNER/REPOSITORY:environment:production` + audience `sts.amazonaws.com`.

No AWS access keys in GitHub. See `AGENTS.md` for SDLC guardrails.
