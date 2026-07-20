from pathlib import Path

WORKFLOW = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
TRIGGERS = WORKFLOW.split("\nconcurrency:\n", maxsplit=1)[0]


def test_ci_runs_for_pull_requests_only() -> None:
    assert "pull_request:" in TRIGGERS
    assert "push:" not in TRIGGERS


def test_ci_cannot_request_aws_credentials() -> None:
    assert "id-token: write" not in WORKFLOW
    assert "configure-aws-credentials" not in WORKFLOW


def test_ci_validate_asserts_clean_worktree_after_validation() -> None:
    assert "git diff --exit-code" in WORKFLOW
    assert WORKFLOW.index("npx cdk synth --quiet") < WORKFLOW.index(
        "git diff --exit-code"
    )
