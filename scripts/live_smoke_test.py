"""Run the deployed S3-to-Lambda smoke-test matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

import boto3
from botocore.exceptions import (
    ClientError,
    ConfigNotFound,
    ConfigParseError,
    InvalidConfigError,
    NoCredentialsError,
    PartialCredentialsError,
    ProfileNotFound,
    SSOTokenLoadError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
    UnknownCredentialError,
)

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
        "SMOKE_SSO_PROFILE",
    }
)
PREFLIGHT_PASSED = (
    "Read-only smoke preflight passed. S3 write and version-cleanup "
    "permissions remain unproven until an authorized smoke run."
)
SSO_SESSION_EXPIRED = (
    "SSO session expired. Run `aws sso login --profile <SSO_PROFILE>` and retry."
)
AWS_PROFILE_NOT_FOUND = (
    "AWS profile not found. Configure an Identity Center SSO profile and retry."
)
AWS_CONFIG_INVALID = (
    "Local AWS configuration is invalid or incomplete. "
    "Fix the SSO profile configuration and retry."
)
AWS_CREDENTIALS_MISSING = (
    "AWS credentials unavailable. "
    "Run `aws sso login --profile <SSO_PROFILE>` and retry."
)


class SmokePreflightError(Exception):
    """Operator-facing preflight failure without sensitive AWS details."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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
            "Use your configured Identity Center SSO profile name.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def require_temporary_assumed_role(identity: Mapping[str, Any]) -> None:
    arn = str(identity.get("Arn", ""))
    if arn.endswith(":root"):
        raise SmokePreflightError("unsupported long-lived identity")
    if ":user/" in arn:
        raise SmokePreflightError("unsupported long-lived identity")
    if ":assumed-role/" not in arn:
        raise SmokePreflightError("unsupported long-lived identity")


def scoped_profile_config(session: Any) -> Mapping[str, Any]:
    """Read profile config from the underlying botocore session only."""
    botocore_session = getattr(session, "_session", None)
    if botocore_session is None:
        return {}
    get_scoped_config = getattr(botocore_session, "get_scoped_config", None)
    if not callable(get_scoped_config):
        return {}
    config = get_scoped_config()
    if not isinstance(config, Mapping):
        return {}
    return config


def profile_uses_identity_center(config: Mapping[str, Any]) -> bool:
    has_account = bool(str(config.get("sso_account_id") or "").strip())
    has_role = bool(str(config.get("sso_role_name") or "").strip())
    has_session = bool(
        str(config.get("sso_session") or "").strip()
        or str(config.get("sso_start_url") or "").strip()
    )
    return has_account and has_role and has_session


def resolve_expected_account(
    config: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> str | None:
    env = os.environ if environ is None else environ
    override = (env.get("SMOKE_EXPECTED_ACCOUNT") or "").strip()
    if override:
        return override
    configured = config.get("sso_account_id")
    if configured:
        return str(configured).strip() or None
    return None


def call_aws_preflight(operation: Any, *, failure_message: str) -> Any:
    """Run one AWS read and map failures to safe operator messages."""
    try:
        return operation()
    except (TokenRetrievalError, UnauthorizedSSOTokenError, SSOTokenLoadError) as exc:
        raise SmokePreflightError(SSO_SESSION_EXPIRED) from exc
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in {"ExpiredToken", "ExpiredTokenException", "RequestExpired"}:
            raise SmokePreflightError(SSO_SESSION_EXPIRED) from exc
        raise SmokePreflightError(failure_message) from exc


def map_session_setup_error(exc: BaseException) -> SmokePreflightError:
    if isinstance(exc, ProfileNotFound):
        return SmokePreflightError(AWS_PROFILE_NOT_FOUND)
    if isinstance(exc, (ConfigNotFound, ConfigParseError, InvalidConfigError)):
        return SmokePreflightError(AWS_CONFIG_INVALID)
    if isinstance(
        exc,
        (
            NoCredentialsError,
            PartialCredentialsError,
            UnknownCredentialError,
        ),
    ):
        return SmokePreflightError(AWS_CREDENTIALS_MISSING)
    if isinstance(
        exc,
        (TokenRetrievalError, UnauthorizedSSOTokenError, SSOTokenLoadError),
    ):
        return SmokePreflightError(SSO_SESSION_EXPIRED)
    if isinstance(exc, SmokePreflightError):
        return exc
    raise exc


SESSION_SETUP_ERRORS = (
    ProfileNotFound,
    ConfigNotFound,
    ConfigParseError,
    InvalidConfigError,
    NoCredentialsError,
    PartialCredentialsError,
    UnknownCredentialError,
    TokenRetrievalError,
    UnauthorizedSSOTokenError,
    SSOTokenLoadError,
)


def open_smoke_session(
    session_factory: Any,
    *,
    profile: str | None,
    region: str,
) -> Any:
    """Create a boto3 session with operator-friendly setup errors."""
    try:
        return session_factory(profile_name=profile, region_name=region)
    except SESSION_SETUP_ERRORS as exc:
        raise map_session_setup_error(exc) from exc


def open_service_client(session: Any, service_name: str) -> Any:
    try:
        return session.client(service_name)
    except SESSION_SETUP_ERRORS as exc:
        raise map_session_setup_error(exc) from exc


def discover_stack_targets(cloudformation: Any, stack_name: str) -> tuple[str, str]:
    stack = call_aws_preflight(
        lambda: cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0],
        failure_message="stack unavailable in selected region",
    )
    outputs = {
        item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])
    }
    bucket = outputs.get("InputBucketName")
    if not bucket:
        raise SmokePreflightError("stack unavailable in selected region")

    resources = call_aws_preflight(
        lambda: cloudformation.describe_stack_resources(StackName=stack_name)[
            "StackResources"
        ],
        failure_message="missing stack-resource permission",
    )
    log_group = next(
        (
            item["PhysicalResourceId"]
            for item in resources
            if item.get("ResourceType") == "AWS::Logs::LogGroup"
        ),
        None,
    )
    if not log_group:
        raise SmokePreflightError("missing stack-resource permission")
    return bucket, log_group


def probe_log_read(logs_client: Any, log_group: str) -> None:
    started_ms = int(time.time() * 1000) - 60_000
    call_aws_preflight(
        lambda: logs_client.filter_log_events(
            logGroupName=log_group,
            startTime=started_ms,
            limit=1,
        ),
        failure_message="missing log-read permission",
    )


def run_preflight(
    session: Any,
    *,
    stack_name: str,
    require_identity_center: bool = True,
    environ: Mapping[str, str] | None = None,
    sts_client: Any | None = None,
    cloudformation_client: Any | None = None,
    logs_client: Any | None = None,
) -> tuple[str, str]:
    """Validate identity and read paths. Returns (bucket, log_group) privately."""
    sts = sts_client or session.client("sts")
    cloudformation = cloudformation_client or session.client("cloudformation")
    logs = logs_client or session.client("logs")
    config = scoped_profile_config(session)

    identity = call_aws_preflight(
        sts.get_caller_identity,
        failure_message=SSO_SESSION_EXPIRED,
    )

    require_temporary_assumed_role(identity)
    if require_identity_center and not profile_uses_identity_center(config):
        raise SmokePreflightError("unsupported long-lived identity")

    expected_account = resolve_expected_account(config, environ=environ)
    actual_account = str(identity.get("Account", "")).strip()
    if not expected_account or not actual_account or expected_account != actual_account:
        raise SmokePreflightError("expected account mismatch")

    bucket, log_group = discover_stack_targets(cloudformation, stack_name)
    probe_log_read(logs, log_group)
    return bucket, log_group


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Post-deploy smoke matrix against the live stack. "
            "--profile must be a real Identity Center SSO profile, "
            "not a docs placeholder."
        )
    )
    parser.add_argument(
        "--profile",
        help=(
            "Local AWS CLI SSO profile name (not SMOKE_SSO_PROFILE). "
            "Required for --check-only."
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
    parser.add_argument(
        "--check-only",
        action="store_true",
        help=(
            "Read-only Identity Center preflight only. "
            "Does not prove S3 write or version-cleanup permissions."
        ),
    )
    return parser


def cleanup_created_versions(
    s3: Any,
    bucket: str,
    versions: list[tuple[str, str]],
) -> int:
    """Delete exact recorded versions; continue after individual failures."""
    failures = 0
    for key, version_id in versions:
        try:
            s3.delete_object(Bucket=bucket, Key=key, VersionId=version_id)
        except ClientError:
            failures += 1
    return failures


def run_smoke_matrix(
    *,
    s3: Any,
    logs: Any,
    timeout: int,
    cleanup: bool,
    bucket: str,
    log_group: str,
) -> int:
    run_id = f"smoke-{uuid.uuid4().hex}"
    prefix = f"incoming/{run_id}/"
    field_sentinel = f"DO_NOT_LOG_FIELD_{run_id}"
    sentinel = f"DO_NOT_LOG_{run_id}"
    started_ms = int(time.time() * 1000) - 5_000
    print(f"Created prefix: {prefix}")

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
    etags: list[str] = []
    ignored_key = prefix + "test.txt"
    ignored_ref = ""
    rapid_valid_ref = ""
    rapid_invalid_ref = ""
    smoke_exit = 1
    cleanup_failed = False

    try:
        for name, body, outcome in cases:
            key = prefix + name
            response = s3.put_object(Bucket=bucket, Key=key, Body=body)
            version_id = response["VersionId"]
            versions.append((key, version_id))
            etags.append(response["ETag"].strip('"'))
            expected[object_reference(bucket, key, version_id)] = (key, outcome)

        response = s3.put_object(Bucket=bucket, Key=ignored_key, Body=b"ignored")
        ignored_version = response["VersionId"]
        versions.append((ignored_key, ignored_version))
        etags.append(response["ETag"].strip('"'))
        ignored_ref = object_reference(bucket, ignored_key, ignored_version)

        rapid_key = prefix + "rapid.json"
        rapid_valid_response = s3.put_object(
            Bucket=bucket, Key=rapid_key, Body=b'{"generation":1}'
        )
        rapid_valid = rapid_valid_response["VersionId"]
        versions.append((rapid_key, rapid_valid))
        etags.append(rapid_valid_response["ETag"].strip('"'))

        rapid_invalid_response = s3.put_object(
            Bucket=bucket, Key=rapid_key, Body=b'{"generation":2,"broken":}'
        )
        rapid_invalid = rapid_invalid_response["VersionId"]
        versions.append((rapid_key, rapid_invalid))
        etags.append(rapid_invalid_response["ETag"].strip('"'))

        rapid_valid_ref = object_reference(bucket, rapid_key, rapid_valid)
        rapid_invalid_ref = object_reference(bucket, rapid_key, rapid_invalid)
        run_object_refs = set(expected) | {
            ignored_ref,
            rapid_valid_ref,
            rapid_invalid_ref,
        }

        deadline = time.monotonic() + timeout
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
            f"{rapid_by_ref.get(rapid_valid_ref)}, "
            f"{rapid_by_ref.get(rapid_invalid_ref)}"
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
        etag_logged = any(etag in joined_logs for etag in etags)
        if etag_logged:
            failures.append("S3 ETag fingerprint appeared in logs")
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
                f"{', '.join(EXPECTED_LOG_CONTEXT)} — deployed Lambda likely "
                "predates the logging contract; redeploy from main and rerun smoke"
            )

        print("| Case | Expected | Actual |")
        print("| --- | --- | --- |")
        for name, expected_result, actual in results:
            print(f"| {name} | `{expected_result}` | `{actual}` |")
        payload_logged = sentinel in joined_logs or field_sentinel in joined_logs
        print(f"\nPayload value or field name logged: {payload_logged}")
        print(f"Raw bucket name or object key logged: {raw_identity_logged}")
        print(f"S3 ETag fingerprint logged: {etag_logged}")
        print(f"Standard log context valid: {context_valid}")
        print(f"Observed logs: {len(records)}/{EXPECTED_LOGS}")

        if failures:
            print("\nFailures:")
            for failure in failures:
                print(f"- {failure}")
            smoke_exit = 1
        else:
            print("\nSmoke matrix passed.")
            smoke_exit = 0
    finally:
        if cleanup and versions:
            failed_deletes = cleanup_created_versions(s3, bucket, versions)
            if failed_deletes:
                cleanup_failed = True
                print(
                    f"Version cleanup failed for {failed_deletes} object version(s). "
                    "Delete only the reported prefix versions manually.",
                    file=sys.stderr,
                )
            else:
                print("Created object versions deleted.")

    if cleanup_failed:
        return 1
    return smoke_exit


def main(
    argv: list[str] | None = None,
    *,
    session_factory: Any | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    validate_profile(args.profile)

    if args.check_only and not args.profile:
        print(
            "Usage: live_smoke_test.py --check-only --profile <SSO_PROFILE>",
            file=sys.stderr,
        )
        return 2

    factory = session_factory or boto3.Session
    try:
        session = open_smoke_session(
            factory,
            profile=args.profile,
            region=args.region,
        )
        sts = open_service_client(session, "sts")
        cloudformation = open_service_client(session, "cloudformation")
        logs = open_service_client(session, "logs")
        bucket, log_group = run_preflight(
            session,
            stack_name=args.stack,
            sts_client=sts,
            cloudformation_client=cloudformation,
            logs_client=logs,
        )
    except SmokePreflightError as exc:
        print(exc.message, file=sys.stderr)
        return 1

    if args.check_only:
        print(PREFLIGHT_PASSED)
        return 0

    try:
        s3 = open_service_client(session, "s3")
    except SmokePreflightError as exc:
        print(exc.message, file=sys.stderr)
        return 1

    return run_smoke_matrix(
        s3=s3,
        logs=logs,
        timeout=args.timeout,
        cleanup=args.cleanup,
        bucket=bucket,
        log_group=log_group,
    )


if __name__ == "__main__":
    raise SystemExit(main())
