"""Run the deployed S3-to-Lambda smoke-test matrix."""

import argparse
import json
import os
import time
from collections import defaultdict
from typing import Any

import boto3

EXPECTED_LOGS = 9
EXPECTED_LOG_CONTEXT = {
    "service": "s3-line-processor",
    "environment": "sandbox",
    "log_schema_version": 1,
}


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


def collect_run_logs(
    logs_client: Any, log_group: str, started_ms: int, run_id: str
) -> tuple[list[str], list[dict[str, Any]]]:
    events = logs_client.filter_log_events(
        logGroupName=log_group, startTime=started_ms
    ).get("events", [])
    raw_messages = [event["message"] for event in events if run_id in event["message"]]
    records = [
        parsed for message in raw_messages if (parsed := parse_log(message)) is not None
    ]
    return raw_messages, records


def outcome_for(record: dict[str, Any]) -> str:
    if record.get("status") == "processed":
        return "processed"
    return str(record.get("reason_code"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", help="AWS CLI profile; omit for ambient credentials"
    )
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    parser.add_argument("--stack", default="S3LineProcessorStack")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete the exact object versions created by this run",
    )
    args = parser.parse_args()

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

    run_id = f"smoke-{int(time.time())}"
    prefix = f"incoming/{run_id}/"
    sentinel = f"DO_NOT_LOG_{run_id}"
    started_ms = int(time.time() * 1000) - 5_000

    cases = [
        ("valid.json", json.dumps({"private": sentinel}).encode(), "processed"),
        ("invalid.json", b'{"broken":}', "invalid_json"),
        ("multiline.json", b'{"a":1}\n{"b":2}', "multiline_input"),
        ("empty.json", b"", "empty_input"),
        ("array.json", b"[1,2,3]", "non_object_json"),
        ("invalid-utf8.json", b"\xff\xfe\xfa", "invalid_utf8"),
        ("oversized.json", b"x" * (1024 * 1024 + 1), "object_too_large"),
    ]

    expected: dict[str, str] = {}
    versions: list[tuple[str, str]] = []
    for name, body, outcome in cases:
        key = prefix + name
        response = s3.put_object(Bucket=bucket, Key=key, Body=body)
        expected[key] = outcome
        versions.append((key, response["VersionId"]))

    ignored_key = prefix + "test.txt"
    response = s3.put_object(Bucket=bucket, Key=ignored_key, Body=b"ignored")
    versions.append((ignored_key, response["VersionId"]))

    rapid_key = prefix + "rapid.json"
    rapid_valid = s3.put_object(Bucket=bucket, Key=rapid_key, Body=b'{"generation":1}')[
        "VersionId"
    ]
    rapid_invalid = s3.put_object(
        Bucket=bucket, Key=rapid_key, Body=b'{"generation":2,"broken":}'
    )["VersionId"]
    versions.extend([(rapid_key, rapid_valid), (rapid_key, rapid_invalid)])

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        _, records = collect_run_logs(logs, log_group, started_ms, run_id)
        observed_keys = {
            record.get("key")
            for record in records
            if isinstance(record.get("key"), str)
        }
        observed_versions = {
            record.get("version_id")
            for record in records
            if record.get("key") == rapid_key
        }
        if set(expected).issubset(observed_keys) and {
            rapid_valid,
            rapid_invalid,
        }.issubset(observed_versions):
            time.sleep(5)
            break
        time.sleep(3)

    raw_messages, records = collect_run_logs(logs, log_group, started_ms, run_id)

    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = record.get("key")
        if isinstance(key, str):
            by_key[key].append(record)

    failures: list[str] = []
    results: list[tuple[str, str, str]] = []
    for key, outcome in expected.items():
        matching = by_key.get(key, [])
        actual = "missing"
        observed = {outcome_for(record) for record in matching}
        if len(observed) == 1:
            actual = observed.pop()
        if actual != outcome:
            failures.append(f"{key}: expected {outcome}, got {actual}")
        results.append((key.removeprefix(prefix), outcome, actual))

    filter_actual = f"{len(by_key.get(ignored_key, []))} invocations"
    if by_key.get(ignored_key):
        failures.append(f"{ignored_key}: notification filter failed")
    results.append(("test.txt", "0 invocations", filter_actual))

    rapid_by_version = {
        record.get("version_id"): outcome_for(record)
        for record in by_key.get(rapid_key, [])
    }
    rapid_actual = (
        f"{rapid_by_version.get(rapid_valid)}, {rapid_by_version.get(rapid_invalid)}"
    )
    if rapid_actual != "processed, invalid_json":
        failures.append(f"rapid overwrite: got {rapid_actual}")
    results.append(("rapid overwrite", "processed, invalid_json", rapid_actual))

    if sentinel in "\n".join(raw_messages):
        failures.append("uploaded payload value appeared in logs")
    context_valid = True
    for record in records:
        for field, expected_value in EXPECTED_LOG_CONTEXT.items():
            if record.get(field) != expected_value:
                context_valid = False
                failures.append(
                    f"{record.get('key')}: expected {field}={expected_value}"
                )

    print("| Case | Expected | Actual |")
    print("| --- | --- | --- |")
    for name, expected_result, actual in results:
        print(f"| {name} | `{expected_result}` | `{actual}` |")
    print(f"\nPayload value logged: {sentinel in ''.join(raw_messages)}")
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
