from pathlib import Path

WORKFLOW = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")
PLAN_JOB, EXECUTE_JOB = WORKFLOW.split("\n  deploy:\n", maxsplit=1)


def test_execute_job_only_verifies_and_executes_frozen_plan() -> None:
    forbidden = [
        "actions/checkout",
        "actions/setup-node",
        "actions/setup-python",
        "npm ",
        "pip ",
        "npx cdk",
    ]

    assert all(command not in EXECUTE_JOB for command in forbidden)
    assert "actions/download-artifact" in EXECUTE_JOB
    assert "aws cloudformation describe-change-set" in EXECUTE_JOB
    assert 'test "$live_id" = "$approved_id"' in EXECUTE_JOB
    assert "aws cloudformation execute-change-set" in EXECUTE_JOB


def test_deploy_uses_cloudformation_evidence_and_hardened_oidc() -> None:
    assert "cdk diff" not in WORKFLOW
    assert "aws cloudformation describe-change-set" in PLAN_JOB
    assert "plan-evidence/change-set.json" in WORKFLOW
    assert WORKFLOW.count("role-to-assume: ${{ secrets.AWS_ROLE_ARN }}") == 2
    assert WORKFLOW.count("allowed-account-ids: ${{ secrets.AWS_ACCOUNT_ID }}") == 2
    assert WORKFLOW.count("role-duration-seconds: 900") == 2
    assert WORKFLOW.count("unset-current-credentials: true") == 2
    assert "vars.AWS_ROLE_ARN" not in WORKFLOW
