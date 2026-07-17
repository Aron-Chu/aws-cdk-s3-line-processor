"""Run the deployed S3-to-Lambda smoke-test matrix."""

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from collections import defaultdict
from typing import Any

import boto3

EXPECTED_LOGS = 9
EXPECTED_LOG_CONTEXT = {
    "service": "s3-line-processor",
    "environment": "sandbox",
    "log_schema_version": 2,
}
DOC_PLACEHOLDER_PROFILES = frozenset(
    {
        "OPERATOR_PROFILE",
        "ADMIN_PROFILE",
        "DEPLOY_PROFILE",
        "YOUR_OPERATOR_PROFILE",
    }
)


def parse_log(message: str) -> dict[str, Any] | None:
    start = message.find("{")
    if start < 0:
        return None
    try:
        value = json.loads(message[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    nested_message = value.get("message")
    if "status" not in value and isinstance(nested_message, str):
        return parse_log(nested_message)
    return value


def object_reference(bucket: str, key: str, version_id: str | None) -> str:
    digest = hashlib.sha256()
    for value in (bucket, key, version_id or ""):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)
    return digest.hexdigest()


def collect_run_logs(
    logs_client: Any, log_group: str, started_ms: int, object_refs: set[str]
) -> tuple[list[str], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    paginator = logs_client.get_paginator("filter_log_events")
    for page in paginator.paginate(logGroupName=log_group, startTime=started_ms):
        events.extend(page.get("events", []))
    raw_messages = [event["message"] for event in events]
    records = []
    for message in raw_messages:
        parsed = parse_log(message)
        if parsed is not None and parsed.get("object_ref") in object_refs:
            records.append(parsed)
    return raw_messages, records


def outcome_for(record: dict[str, Any]) -> str:
    if record.get("status") == "processed":
        return "processed"
    return str(record.get("reason_code"))


def validate_profile(profile: str | None) -> None:
    """Reject documentation placeholders before opening an AWS session."""
    if profile is None:
        return
    if profile in DOC_PLACEHOLDER_PROFILES:
        print(
            f"--profile {profile!r} is a documentation placeholder. "
            "Use your local AWS CLI profile name "
            "(for example, s3-line-processor-operator), or omit --profile "
            "to use ambient credentials.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Post-deploy smoke matrix against the live stack. "
            "--profile must be a real local AWS CLI profile, not a docs placeholder."
        )
    )
    parser.add_argument(
        "--profile",
        help=(
            "Local AWS CLI profile name (not OPERATOR_PROFILE). "
            "Omit to use ambient credentials."
        ),
    )
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    parser.add_argument("--stack", default="S3LineProcessorStack")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete the exact object versions created by this run",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    validate_profile(args.profile)

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    cloudformation = session.client("cloudformation")
    s3 = session.client("s3")
    logs = session.client("logs")

    stack = cloudformation.describe_stacks(StackName=args.stack)["Stacks"][0]
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
    bucket = outputs["InputBucketName"]
    resources = cloudformation.describe_stack_resources(StackName=args.stack)[
        "StackResources"
    ]
    log_group = next(
        item["PhysicalResourceId"]
        for item in resources
        if item["ResourceType"] == "AWS::Logs::LogGroup"
    )

    run_id = f"smoke-{uuid.uuid4().hex}"
    prefix = f"incoming/{run_id}/"
    field_sentinel = f"DO_NOT_LOG_FIELD_{run_id}"
    sentinel = f"DO_NOT_LOG_{run_id}"
    started_ms = int(time.time() * 1000) - 5_000

    cases = [
        (
            "valid.json",
            json.dumps({field_sentinel: sentinel}).encode(),
            "processed",
        ),
        ("invalid.json", b'{"broken":}', "invalid_json"),
        ("multiline.json", b'{"a":1}\n{"b":2}', "multiline_input"),
        ("empty.json", b"", "empty_input"),
        ("array.json", b"[1,2,3]", "non_object_json"),
        ("invalid-utf8.json", b"\xff\xfe\xfa", "invalid_utf8"),
        ("oversized.json", b"x" * (1024 * 1024 + 1), "object_too_large"),
    ]

    expected: dict[str, tuple[str, str]] = {}
    versions: list[tuple[str, str]] = []
    for name, body, outcome in cases:
        key = prefix + name
        response = s3.put_object(Bucket=bucket, Key=key, Body=body)
        version_id = response["VersionId"]
        expected[object_reference(bucket, key, version_id)] = (key, outcome)
        versions.append((key, version_id))

    ignored_key = prefix + "test.txt"
    response = s3.put_object(Bucket=bucket, Key=ignored_key, Body=b"ignored")
    ignored_version = response["VersionId"]
    ignored_ref = object_reference(bucket, ignored_key, ignored_version)
    versions.append((ignored_key, ignored_version))

    rapid_key = prefix + "rapid.json"
    rapid_valid = s3.put_object(Bucket=bucket, Key=rapid_key, Body=b'{"generation":1}')[
        "VersionId"
    ]
    rapid_invalid = s3.put_object(
        Bucket=bucket, Key=rapid_key, Body=b'{"generation":2,"broken":}'
    )["VersionId"]
    versions.extend([(rapid_key, rapid_valid), (rapid_key, rapid_invalid)])
    rapid_valid_ref = object_reference(bucket, rapid_key, rapid_valid)
    rapid_invalid_ref = object_reference(bucket, rapid_key, rapid_invalid)
    run_object_refs = set(expected) | {
        ignored_ref,
        rapid_valid_ref,
        rapid_invalid_ref,
    }

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        _, records = collect_run_logs(logs, log_group, started_ms, run_object_refs)
        observed_refs = {
            record.get("object_ref")
            for record in records
            if isinstance(record.get("object_ref"), str)
        }
        if set(expected).issubset(observed_refs) and {
            rapid_valid_ref,
            rapid_invalid_ref,
        }.issubset(observed_refs):
            time.sleep(5)
            break
        time.sleep(3)

    raw_messages, records = collect_run_logs(
        logs, log_group, started_ms, run_object_refs
    )

    by_ref: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        object_ref = record.get("object_ref")
        if isinstance(object_ref, str):
            by_ref[object_ref].append(record)

    failures: list[str] = []
    results: list[tuple[str, str, str]] = []
    for object_ref, (key, outcome) in expected.items():
        matching = by_ref.get(object_ref, [])
        actual = "missing"
        observed = {outcome_for(record) for record in matching}
        if len(observed) == 1:
            actual = observed.pop()
        if actual != outcome:
            failures.append(f"{key}: expected {outcome}, got {actual}")
        results.append((key.removeprefix(prefix), outcome, actual))

    filter_actual = f"{len(by_ref.get(ignored_ref, []))} invocations"
    if by_ref.get(ignored_ref):
        failures.append(f"{ignored_key}: notification filter failed")
    results.append(("test.txt", "0 invocations", filter_actual))

    rapid_by_ref = {
        record.get("object_ref"): outcome_for(record)
        for record in records
        if record.get("object_ref") in {rapid_valid_ref, rapid_invalid_ref}
    }
    rapid_actual = (
        f"{rapid_by_ref.get(rapid_valid_ref)}, {rapid_by_ref.get(rapid_invalid_ref)}"
    )
    if rapid_actual != "processed, invalid_json":
        failures.append(f"rapid overwrite: got {rapid_actual}")
    results.append(("rapid overwrite", "processed, invalid_json", rapid_actual))

    joined_logs = "\n".join(raw_messages)
    if sentinel in joined_logs or field_sentinel in joined_logs:
        failures.append("uploaded payload value or field name appeared in logs")
    raw_identity_logged = bucket in joined_logs or any(
        key in joined_logs for key, _version_id in versions
    )
    if raw_identity_logged:
        failures.append("raw bucket name or object key appeared in logs")
    context_valid = True
    missing_context = 0
    for record in records:
        if any(
            record.get(field) != expected_value
            for field, expected_value in EXPECTED_LOG_CONTEXT.items()
        ):
            context_valid = False
            missing_context += 1
    if missing_context:
        failures.append(
            f"{missing_context}/{len(records)} log records missing "
            f"{', '.join(EXPECTED_LOG_CONTEXT)} — deployed Lambda likely predates "
            "the logging contract; redeploy from main and rerun smoke"
        )

    print("| Case | Expected | Actual |")
    print("| --- | --- | --- |")
    for name, expected_result, actual in results:
        print(f"| {name} | `{expected_result}` | `{actual}` |")
    payload_logged = sentinel in joined_logs or field_sentinel in joined_logs
    print(f"\nPayload value or field name logged: {payload_logged}")
    print(f"Raw bucket name or object key logged: {raw_identity_logged}")
    print(f"Standard log context valid: {context_valid}")
    print(f"Observed logs: {len(records)}/{EXPECTED_LOGS}")
    print(f"Created prefix: {prefix}")

    if args.cleanup:
        for key, version_id in versions:
            s3.delete_object(Bucket=bucket, Key=key, VersionId=version_id)
        print("Created object versions deleted.")

    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nSmoke matrix passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
