import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]

CANONICAL_DOCUMENTS = (
    Path("README.md"),
    Path("CONTRIBUTING.md"),
    Path("SECURITY.md"),
    Path("AGENTS.md"),
    Path("docs/design.md"),
    Path("docs/operations.md"),
    Path("docs/platform-access.md"),
    Path("docs/test-results.md"),
)
RETIRED_DOCUMENTS = (
    Path("docs/intentional-omissions.md"),
    Path("docs/review-guide.md"),
)
IGNORED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "cdk.out",
    "node_modules",
}
MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
AWS_ACCOUNT_ID = re.compile(r"(?<!\d)\d{12}(?!\d)")


def _markdown_files() -> list[Path]:
    markdown_files = []

    for directory, child_directories, filenames in os.walk(ROOT):
        child_directories[:] = sorted(
            child for child in child_directories if child not in IGNORED_DIRECTORIES
        )
        markdown_files.extend(
            Path(directory) / filename
            for filename in filenames
            if filename.endswith(".md")
        )

    return sorted(markdown_files)


def _relative_link_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    if not target or target.startswith("#"):
        return None
    if "://" in target or target.startswith("mailto:"):
        return None
    return unquote(target.split("#", maxsplit=1)[0])


def test_canonical_documentation_exists() -> None:
    assert all((ROOT / path).is_file() for path in CANONICAL_DOCUMENTS)


def test_readme_indexes_every_canonical_document() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for path in CANONICAL_DOCUMENTS[1:]:
        assert f"]({path.as_posix()})" in readme


def test_all_relative_markdown_links_resolve_inside_repository() -> None:
    repository_root = ROOT.resolve()

    for document in _markdown_files():
        content = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(content):
            relative_target = _relative_link_target(raw_target)
            if relative_target is None:
                continue

            resolved_target = (document.parent / relative_target).resolve()
            assert resolved_target.is_relative_to(repository_root), (
                f"{document.relative_to(ROOT)} links outside the repository: "
                f"{raw_target}"
            )
            assert resolved_target.exists(), (
                f"{document.relative_to(ROOT)} has a missing link: {raw_target}"
            )


def test_retired_documents_are_removed_and_unreferenced() -> None:
    markdown = "\n".join(path.read_text(encoding="utf-8") for path in _markdown_files())

    for path in RETIRED_DOCUMENTS:
        assert not (ROOT / path).exists()
        assert path.name not in markdown


def test_public_markdown_contains_no_literal_aws_account_id() -> None:
    for document in _markdown_files():
        content = document.read_text(encoding="utf-8")
        assert AWS_ACCOUNT_ID.search(content) is None, (
            f"{document.relative_to(ROOT)} contains a literal AWS account ID"
        )


def test_operational_documents_have_reader_context() -> None:
    required_headings = {
        "## Purpose",
        "## Who should use this",
        "## What this does not do",
    }

    for relative_path in (
        Path("CONTRIBUTING.md"),
        Path("SECURITY.md"),
        Path("docs/operations.md"),
        Path("docs/platform-access.md"),
    ):
        headings = set((ROOT / relative_path).read_text(encoding="utf-8").splitlines())
        assert required_headings <= headings


def test_major_topics_have_one_canonical_owner() -> None:
    topic_owners = {
        "## Repository deployment": Path("docs/operations.md"),
        "## IAM Identity Center": Path("docs/platform-access.md"),
        "## Vulnerability reporting": Path("SECURITY.md"),
        "## Intentional omissions": Path("docs/design.md"),
        "## Agent-assisted changes": Path("CONTRIBUTING.md"),
        "## Change and test workflow": Path("CONTRIBUTING.md"),
    }
    markdown_files = _markdown_files()

    for heading, expected_owner in topic_owners.items():
        owners = [
            path.relative_to(ROOT)
            for path in markdown_files
            if heading in path.read_text(encoding="utf-8").splitlines()
        ]
        assert owners == [expected_owner]


def test_architecture_source_and_export_share_required_visible_labels() -> None:
    source = json.loads(
        (ROOT / "docs/architecture.excalidraw").read_text(encoding="utf-8")
    )
    source_labels = {
        line.strip()
        for element in source["elements"]
        if element.get("type") == "text" and not element.get("isDeleted", False)
        for line in element.get("text", "").splitlines()
        if line.strip()
    }
    svg_root = ET.parse(ROOT / "docs/architecture.svg").getroot()
    export_labels = {
        "".join(element.itertext()).strip()
        for element in svg_root.iter()
        if element.tag.rsplit("}", maxsplit=1)[-1] == "text"
        and "".join(element.itertext()).strip()
    }

    required_labels = {
        "external identity",
        "prefix incoming/",
        "suffix .json",
        "Amazon S3",
        "AWS Lambda",
        "Amazon CloudWatch",
        "GitHub Actions",
        "validate · synth",
        "Deploy role",
        "CloudFormation",
        "Application stack",
        "exact change-set ID",
        (
            "Solid arrows: runtime traffic · Dashed arrows: deployment traffic · "
            "AWS-managed networking; no customer VPC"
        ),
    }

    for label in required_labels:
        assert label in source_labels, f"Excalidraw source is missing: {label}"
        assert label in export_labels, f"SVG export is missing: {label}"
