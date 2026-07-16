# Deployment and maintenance

## Local validation

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
npm ci
pre-commit install

pre-commit run --all-files
pytest
npx cdk synth
```

## Deploy

Bootstrap each account and region once with an approved non-root setup
identity:

```bash
npx cdk bootstrap aws://ACCOUNT_ID/AWS_REGION --profile ADMIN_PROFILE
```

Review and deploy:

```bash
npx cdk diff --profile DEPLOY_PROFILE
npx cdk deploy --profile DEPLOY_PROFILE
```

Alternatively, run the manual `Deploy` GitHub Actions workflow from protected
`main` and approve the `production` environment. It uses short-lived OIDC
credentials; do not store AWS access keys in GitHub.

## Smoke test

Use the CloudFormation output values:

```bash
aws s3 cp samples/valid.json \
  s3://BUCKET_NAME/incoming/example.json \
  --profile OPERATOR_PROFILE

LOG_GROUP=$(aws cloudformation describe-stack-resources \
  --stack-name S3LineProcessorStack \
  --query "StackResources[?ResourceType=='AWS::Logs::LogGroup'].PhysicalResourceId | [0]" \
  --output text \
  --profile OPERATOR_PROFILE)

aws logs tail "$LOG_GROUP" \
  --since 10m \
  --profile OPERATOR_PROFILE
```

Confirm the function logs `status: processed` without uploaded values.

## Maintain

- Review Dependabot updates before merging.
- Run pre-commit, Pytest, synthesis, and an authenticated CDK diff after
  dependency or infrastructure changes.
- Keep `architecture.excalidraw` and `architecture.svg` synchronized.
- Use a read-only audit role for routine inspection.

## Clean up

The bucket and TLS policy are retained. Confirm the bucket is dedicated to this
stack, then remove its Lambda notification before destroying the function:

```bash
aws s3api put-bucket-notification-configuration \
  --bucket BUCKET_NAME \
  --notification-configuration '{}' \
  --profile DEPLOY_PROFILE

npx cdk destroy --profile DEPLOY_PROFILE
```

Deleting the retained bucket is a separate destructive operation. Remove every
object version and delete marker first, and confirm the account and bucket name
before deleting data.
