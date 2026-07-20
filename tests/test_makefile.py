import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


def _sandbox_ack(value: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("SANDBOX_ACK", None)
    if value is not None:
        environment["SANDBOX_ACK"] = value

    make = shutil.which("make")
    if make is None:
        raise RuntimeError("make executable not found")

    return subprocess.run(
        [make, "--no-print-directory", "sandbox-ack"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )


def test_local_aws_write_targets_require_sandbox_acknowledgement() -> None:
    assert "bootstrap: sandbox-ack aws-check" in MAKEFILE
    assert "deploy: sandbox-ack check diff" in MAKEFILE

    result = _sandbox_ack()

    assert result.returncode != 0
    assert "Refusing a local AWS write." in result.stdout
    assert "protected GitHub Deploy workflow" in result.stdout


def test_exact_sandbox_acknowledgement_is_accepted() -> None:
    assert _sandbox_ack("wrong-value").returncode != 0
    assert _sandbox_ack("developer-owned").returncode == 0
    assert _sandbox_ack("reviewer-owned").returncode == 0


def test_smoke_check_target_is_read_only_preflight() -> None:
    assert "smoke-check" in MAKEFILE
    assert "--check-only" in MAKEFILE
    assert "make smoke-check PROFILE=<smoke-profile>" in MAKEFILE
    assert MAKEFILE.index("smoke-check:") < MAKEFILE.index("\nsmoke:")
    help_block = MAKEFILE.split("help:", maxsplit=1)[1].split("\nsetup:", maxsplit=1)[0]
    assert "Read-only assumed-role smoke preflight" in help_block
    assert "does not authorize or run make smoke" in MAKEFILE


def test_smoke_recipes_do_not_echo_expected_account() -> None:
    smoke_check = MAKEFILE.split("smoke-check:", maxsplit=1)[1].split(
        "\nsmoke:", maxsplit=1
    )[0]
    smoke = MAKEFILE.split("\nsmoke:", maxsplit=1)[1]
    assert "SMOKE_PY" in MAKEFILE
    assert "@$(SMOKE_PY)" in smoke_check
    assert "@$(SMOKE_PY)" in smoke
    assert "\n\tSMOKE_EXPECTED_ACCOUNT=" not in smoke_check
    assert "\n\tSMOKE_EXPECTED_ACCOUNT=" not in smoke


def test_test_recipe_supplies_linux_safe_temp_directory() -> None:
    test_recipe = MAKEFILE.split("\ntest:", maxsplit=1)[1].split(
        "\nsynth:", maxsplit=1
    )[0]
    assert "TMPDIR=/tmp TMP=/tmp TEMP=/tmp $(PY) -m pytest" in test_recipe
    assert "check: lock-check lint test synth" in MAKEFILE
