import os
import shutil
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mask_stack_outputs.sh"
WORKFLOW = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")
BEFORE_PLAN, AFTER_PLAN = WORKFLOW.split("\n  plan:\n", maxsplit=1)
PLAN_JOB, EXECUTE_JOB = AFTER_PLAN.split("\n  deploy:\n", maxsplit=1)


def _run_mask_script(
    fake_aws: Path, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        raise RuntimeError("bash executable not found")

    environment = os.environ.copy()
    if env:
        environment.update(env)
    environment["PATH"] = f"{fake_aws.parent}{os.pathsep}{environment.get('PATH', '')}"
    return subprocess.run(
        [bash, str(SCRIPT), "S3LineProcessorStack"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )


def test_plan_uses_mask_script_before_cdk_deploy() -> None:
    assert "bash scripts/mask_stack_outputs.sh" in PLAN_JOB
    assert PLAN_JOB.index("bash scripts/mask_stack_outputs.sh") < PLAN_JOB.index(
        "npx cdk deploy S3LineProcessorStack"
    )
    assert "plan-evidence/mask_stack_outputs.sh" in PLAN_JOB
    assert "chmod +x scripts/mask_stack_outputs.sh" not in PLAN_JOB


def test_execute_reuses_mask_script_from_plan_evidence() -> None:
    assert "bash plan-evidence/mask_stack_outputs.sh" in EXECUTE_JOB
    assert EXECUTE_JOB.index("bash plan-evidence/mask_stack_outputs.sh") < (
        EXECUTE_JOB.index("aws cloudformation execute-change-set")
    )


def test_mask_script_masks_existing_output_values(tmp_path: Path) -> None:
    fake_aws = tmp_path / "aws"
    fake_aws.write_text(
        "#!/usr/bin/env bash\n"
        "cat <<'EOF'\n"
        '{"Stacks":[{"Outputs":['
        '{"OutputKey":"InputBucketName","OutputValue":"bucket-alpha"},'
        '{"OutputKey":"ProcessorFunctionName","OutputValue":"function-beta"},'
        '{"OutputKey":"Weird","OutputValue":"name%with\\nbreak"}'
        "]}]}\n"
        "EOF\n",
        encoding="utf-8",
    )
    fake_aws.chmod(fake_aws.stat().st_mode | stat.S_IXUSR)

    result = _run_mask_script(fake_aws)

    assert result.returncode == 0
    assert "::add-mask::bucket-alpha" in result.stdout
    assert "::add-mask::function-beta" in result.stdout
    assert "::add-mask::name%25with%0Abreak" in result.stdout


def test_mask_script_ignores_missing_stack(tmp_path: Path) -> None:
    fake_aws = tmp_path / "aws"
    fake_aws.write_text(
        "#!/usr/bin/env bash\n"
        'echo "An error occurred (ValidationError) when calling the '
        "DescribeStacks operation: Stack with id S3LineProcessorStack "
        'does not exist" >&2\n'
        "exit 254\n",
        encoding="utf-8",
    )
    fake_aws.chmod(fake_aws.stat().st_mode | stat.S_IXUSR)

    result = _run_mask_script(fake_aws)

    assert result.returncode == 0
    assert "::add-mask::" not in result.stdout


def test_mask_script_fails_closed_on_access_denied(tmp_path: Path) -> None:
    fake_aws = tmp_path / "aws"
    fake_aws.write_text(
        "#!/usr/bin/env bash\n"
        'echo "An error occurred (AccessDenied) when calling the '
        'DescribeStacks operation: User is not authorized" >&2\n'
        "exit 254\n",
        encoding="utf-8",
    )
    fake_aws.chmod(fake_aws.stat().st_mode | stat.S_IXUSR)

    result = _run_mask_script(fake_aws)

    assert result.returncode == 254
    assert "AccessDenied" in result.stderr
    assert "::add-mask::" not in result.stdout


def test_mask_script_fails_closed_on_unrelated_does_not_exist(tmp_path: Path) -> None:
    fake_aws = tmp_path / "aws"
    fake_aws.write_text(
        "#!/usr/bin/env bash\n"
        'echo "Throttling: temporary credential does not exist in cache" >&2\n'
        "exit 255\n",
        encoding="utf-8",
    )
    fake_aws.chmod(fake_aws.stat().st_mode | stat.S_IXUSR)

    result = _run_mask_script(fake_aws)

    assert result.returncode == 255
    assert "::add-mask::" not in result.stdout
