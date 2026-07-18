from pathlib import Path

WORKFLOW = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")
TRIGGERS = WORKFLOW.split("\npermissions:\n", maxsplit=1)[0]
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
    assert "--client-request-token" in EXECUTE_JOB
    assert "EXECUTE_IN_PROGRESS|EXECUTE_COMPLETE" in EXECUTE_JOB
    assert 'if [ "$change_set_type" = "CREATE" ]' in EXECUTE_JOB
    assert 'test "$final_status" = "$expected_status"' in EXECUTE_JOB
    assert "ChangeSetType" in WORKFLOW


def test_deploy_trigger_covers_the_python_lockfile() -> None:
    assert '- "requirements.lock"' in TRIGGERS


def test_empty_cloudformation_plan_skips_execute() -> None:
    assert "The submitted information didn't contain changes." in PLAN_JOB
    assert "No updates are to be performed." in PLAN_JOB
    assert 'echo "has_changes=false"' in PLAN_JOB
    assert "if: needs.plan.outputs.has_changes == 'true'" in EXECUTE_JOB


def test_deploy_uses_cloudformation_evidence_and_hardened_oidc() -> None:
    assert "cdk diff" not in WORKFLOW
    assert "aws cloudformation describe-change-set" in PLAN_JOB
    assert "plan-evidence/change-set.json" in WORKFLOW
    assert "CHANGE_SET_PROJECTION" in WORKFLOW
    assert "cmp --silent" in EXECUTE_JOB
    assert WORKFLOW.count("role-to-assume: ${{ secrets.AWS_ROLE_ARN }}") == 2
    assert WORKFLOW.count("allowed-account-ids: ${{ secrets.AWS_ACCOUNT_ID }}") == 2
    assert WORKFLOW.count("role-duration-seconds: 900") == 2
    assert WORKFLOW.count("unset-current-credentials: true") == 2
    assert "vars.AWS_ROLE_ARN" not in WORKFLOW
