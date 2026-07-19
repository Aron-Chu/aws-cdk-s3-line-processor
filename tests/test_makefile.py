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
    assert _sandbox_ack("reviewer-owned").returncode == 0
