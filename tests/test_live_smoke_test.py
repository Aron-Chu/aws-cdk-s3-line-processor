import json
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from scripts import live_smoke_test as smoke

ACCOUNT = "111122223333"
OTHER_ACCOUNT = "999988887777"
ROLE_ARN = f"arn:aws:sts::{ACCOUNT}:assumed-role/SmokeOperator/session"
USER_ARN = f"arn:aws:iam::{ACCOUNT}:user/legacy-operator"
ROOT_ARN = f"arn:aws:iam::{ACCOUNT}:root"
BUCKET = "example-bucket"
LOG_GROUP = "/aws/lambda/example"


def _client_error(code: str, message: str = "denied") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "Operation",
    )


def _sso_session(
    *,
    account: str = ACCOUNT,
    sso_account_id: str | None = ACCOUNT,
) -> MagicMock:
    session = MagicMock()
    config: dict[str, str] = {
        "sso_session": "example-sso",
        "sso_role_name": "SmokeOperator",
    }
    if sso_account_id is not None:
        config["sso_account_id"] = sso_account_id
    session.get_scoped_config.return_value = config

    sts = MagicMock()
    sts.get_caller_identity.return_value = {
        "Account": account,
        "Arn": ROLE_ARN,
        "UserId": "AIDACKCEVSQ6C2EXAMPLE:session",
    }
    cloudformation = MagicMock()
    cloudformation.describe_stacks.return_value = {
        "Stacks": [
            {
                "Outputs": [
                    {"OutputKey": "InputBucketName", "OutputValue": BUCKET},
                    {
                        "OutputKey": "ProcessorFunctionName",
                        "OutputValue": "example-fn",
                    },
                ]
            }
        ]
    }
    cloudformation.describe_stack_resources.return_value = {
        "StackResources": [
            {
                "ResourceType": "AWS::Logs::LogGroup",
                "PhysicalResourceId": LOG_GROUP,
            }
        ]
    }
    logs = MagicMock()
    logs.filter_log_events.return_value = {"events": []}
    s3 = MagicMock()

    def client(service_name: str, **_kwargs: Any) -> MagicMock:
        return {
            "sts": sts,
            "cloudformation": cloudformation,
            "logs": logs,
            "s3": s3,
        }[service_name]

    session.client.side_effect = client
    session._sts = sts
    session._cloudformation = cloudformation
    session._logs = logs
    session._s3 = s3
    return session


def test_parse_log_reads_direct_json_message() -> None:
    record = smoke.parse_log('{"status":"processed","key":"incoming/a.json"}')
    assert record == {"status": "processed", "key": "incoming/a.json"}


def test_parse_log_reads_classic_lambda_line_with_context() -> None:
    line = (
        "[INFO]\t2026-07-16T00:00:00.000Z\tabc\t"
        '{"environment":"sandbox","object_ref":"abc123",'
        '"log_schema_version":2,"service":"s3-line-processor","status":"processed"}'
    )
    record = smoke.parse_log(line)
    assert record is not None
    assert record["status"] == "processed"
    assert record["service"] == "s3-line-processor"
    assert record["environment"] == "sandbox"
    assert record["log_schema_version"] == 2


def test_parse_log_unwraps_nested_message_envelope() -> None:
    nested = (
        '{"environment":"sandbox","log_schema_version":2,'
        '"reason_code":"invalid_json","service":"s3-line-processor","status":"rejected"}'
    )
    envelope = json.dumps({"level": "ERROR", "message": nested})
    record = smoke.parse_log(envelope)
    assert record == {
        "environment": "sandbox",
        "log_schema_version": 2,
        "reason_code": "invalid_json",
        "service": "s3-line-processor",
        "status": "rejected",
    }


def test_parse_log_returns_none_for_non_json() -> None:
    assert smoke.parse_log("START RequestId: abc") is None


def test_outcome_for_processed_and_reason_code() -> None:
    assert smoke.outcome_for({"status": "processed"}) == "processed"
    assert smoke.outcome_for({"status": "rejected", "reason_code": "empty_input"}) == (
        "empty_input"
    )


def test_collect_run_logs_filters_by_object_reference_and_parses() -> None:
    object_ref = smoke.object_reference("bucket", "incoming/a.json", "version-1")
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {
            "events": [
                {
                    "message": json.dumps(
                        {
                            "status": "processed",
                            "object_ref": object_ref,
                        }
                    )
                },
                {
                    "message": json.dumps(
                        {"status": "rejected", "object_ref": "other-ref"}
                    )
                },
                {"message": "not-json"},
            ]
        }
    ]

    raw, records = smoke.collect_run_logs(client, "/aws/lambda/fn", 1, {object_ref})

    assert len(raw) == 3
    assert records == [{"status": "processed", "object_ref": object_ref}]
    client.get_paginator.assert_called_once_with("filter_log_events")


def test_object_reference_is_stable_and_version_specific() -> None:
    first = smoke.object_reference("bucket", "incoming/a.json", "version-1")

    assert len(first) == 64
    assert first == smoke.object_reference("bucket", "incoming/a.json", "version-1")
    assert first != smoke.object_reference("bucket", "incoming/a.json", "version-2")


def test_validate_profile_rejects_documentation_placeholders(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        smoke.validate_profile("OPERATOR_PROFILE")
    assert raised.value.code == 2
    assert "documentation placeholder" in capsys.readouterr().err


def test_validate_profile_allows_real_names_and_none() -> None:
    smoke.validate_profile(None)
    smoke.validate_profile("my-smoke-sso")


def test_build_parser_accepts_check_only_and_cleanup() -> None:
    args = smoke.build_parser().parse_args(
        ["--profile", "my-smoke-sso", "--cleanup", "--check-only"]
    )
    assert args.profile == "my-smoke-sso"
    assert args.cleanup is True
    assert args.check_only is True
    assert args.stack == "S3LineProcessorStack"


def test_require_temporary_assumed_role_rejects_user_and_root() -> None:
    smoke.require_temporary_assumed_role({"Arn": ROLE_ARN})
    with pytest.raises(
        smoke.SmokePreflightError, match="unsupported long-lived identity"
    ):
        smoke.require_temporary_assumed_role({"Arn": USER_ARN})
    with pytest.raises(
        smoke.SmokePreflightError, match="unsupported long-lived identity"
    ):
        smoke.require_temporary_assumed_role({"Arn": ROOT_ARN})


def test_check_only_accepts_identity_center_assumed_role(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _sso_session()

    def factory(**_kwargs: Any) -> MagicMock:
        return session

    code = smoke.main(
        ["--check-only", "--profile", "my-smoke-sso", "--region", "us-west-2"],
        session_factory=factory,
    )

    assert code == 0
    assert smoke.PREFLIGHT_PASSED in capsys.readouterr().out
    session._s3.put_object.assert_not_called()
    session._s3.delete_object.assert_not_called()
    assert session._cloudformation.execute_change_set.call_count == 0


def test_check_only_rejects_iam_user(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _sso_session()
    session._sts.get_caller_identity.return_value = {
        "Account": ACCOUNT,
        "Arn": USER_ARN,
    }

    code = smoke.main(
        ["--check-only", "--profile", "legacy"],
        session_factory=lambda **_: session,
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "unsupported long-lived identity" in captured.err
    assert ACCOUNT not in captured.err
    assert USER_ARN not in captured.err
    session._s3.put_object.assert_not_called()


def test_check_only_rejects_root_identity(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _sso_session()
    session._sts.get_caller_identity.return_value = {
        "Account": ACCOUNT,
        "Arn": ROOT_ARN,
    }

    code = smoke.main(
        ["--check-only", "--profile", "legacy"],
        session_factory=lambda **_: session,
    )

    assert code == 1
    assert "unsupported long-lived identity" in capsys.readouterr().err


def test_check_only_expired_credentials_fail_safely(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _sso_session()
    session._sts.get_caller_identity.side_effect = _client_error(
        "ExpiredToken", "expired"
    )

    code = smoke.main(
        ["--check-only", "--profile", "my-smoke-sso"],
        session_factory=lambda **_: session,
    )

    assert code == 1
    assert "SSO session expired" in capsys.readouterr().err


def test_check_only_account_mismatch_hides_both_accounts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _sso_session(account=ACCOUNT, sso_account_id=OTHER_ACCOUNT)

    code = smoke.main(
        ["--check-only", "--profile", "my-smoke-sso"],
        session_factory=lambda **_: session,
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "expected account mismatch" in captured.err
    assert ACCOUNT not in captured.err
    assert OTHER_ACCOUNT not in captured.out
    assert OTHER_ACCOUNT not in captured.err


def test_check_only_missing_stack_resources_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _sso_session()
    session._cloudformation.describe_stack_resources.side_effect = _client_error(
        "AccessDenied"
    )

    code = smoke.main(
        ["--check-only", "--profile", "my-smoke-sso"],
        session_factory=lambda **_: session,
    )

    assert code == 1
    assert "missing stack-resource permission" in capsys.readouterr().err


def test_check_only_missing_log_read_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = _sso_session()
    session._logs.filter_log_events.side_effect = _client_error("AccessDeniedException")

    code = smoke.main(
        ["--check-only", "--profile", "my-smoke-sso"],
        session_factory=lambda **_: session,
    )

    assert code == 1
    assert "missing log-read permission" in capsys.readouterr().err
    session._s3.put_object.assert_not_called()


def test_check_only_never_calls_mutation_apis() -> None:
    session = _sso_session()
    smoke.main(
        ["--check-only", "--profile", "my-smoke-sso"],
        session_factory=lambda **_: session,
    )

    session._s3.put_object.assert_not_called()
    session._s3.delete_object.assert_not_called()
    assert not hasattr(session._cloudformation, "execute_change_set") or (
        session._cloudformation.execute_change_set.call_count == 0
    )
    session.client.assert_any_call("sts")
    session.client.assert_any_call("cloudformation")
    session.client.assert_any_call("logs")
    # s3 client may be constructed by main but must not mutate
    assert session._s3.method_calls == []


def test_normal_smoke_runs_preflight_before_first_upload() -> None:
    session = _sso_session()
    call_order: list[str] = []

    def track_identity() -> dict[str, str]:
        call_order.append("sts")
        return {"Account": ACCOUNT, "Arn": ROLE_ARN}

    def track_describe_stacks(**_kwargs: Any) -> dict[str, Any]:
        call_order.append("describe_stacks")
        return {
            "Stacks": [
                {
                    "Outputs": [
                        {"OutputKey": "InputBucketName", "OutputValue": BUCKET},
                    ]
                }
            ]
        }

    def track_describe_resources(**_kwargs: Any) -> dict[str, Any]:
        call_order.append("describe_resources")
        return {
            "StackResources": [
                {
                    "ResourceType": "AWS::Logs::LogGroup",
                    "PhysicalResourceId": LOG_GROUP,
                }
            ]
        }

    def track_filter(**_kwargs: Any) -> dict[str, Any]:
        call_order.append("filter_logs")
        return {"events": []}

    def track_put(**_kwargs: Any) -> dict[str, str]:
        call_order.append("put_object")
        return {"VersionId": "v1", "ETag": '"etag"'}

    session._sts.get_caller_identity.side_effect = track_identity
    session._cloudformation.describe_stacks.side_effect = track_describe_stacks
    session._cloudformation.describe_stack_resources.side_effect = (
        track_describe_resources
    )
    session._logs.filter_log_events.side_effect = track_filter
    session._logs.get_paginator.return_value.paginate.return_value = [{"events": []}]
    session._s3.put_object.side_effect = track_put
    session._s3.delete_object.return_value = {}

    # Force timeout quickly by making logs empty; still verifies order before puts.
    code = smoke.main(
        [
            "--profile",
            "my-smoke-sso",
            "--timeout",
            "0",
            "--cleanup",
        ],
        session_factory=lambda **_: session,
    )

    assert code == 1  # matrix fails without expected logs
    assert "put_object" in call_order
    assert call_order.index("sts") < call_order.index("put_object")
    assert call_order.index("filter_logs") < call_order.index("put_object")
    assert call_order.index("describe_resources") < call_order.index("put_object")
    # First put happens only after preflight filter_logs
    first_put = call_order.index("put_object")
    assert call_order[:first_put] == [
        "sts",
        "describe_stacks",
        "describe_resources",
        "filter_logs",
    ]


def test_smoke_matrix_retains_txt_filter_case_and_versioned_cleanup() -> None:
    s3 = MagicMock()
    logs = MagicMock()
    versions = iter([f"v{i}" for i in range(1, 20)])

    def put_object(**_kwargs: Any) -> dict[str, str]:
        return {"VersionId": next(versions), "ETag": '"e"'}

    s3.put_object.side_effect = put_object
    logs.get_paginator.return_value.paginate.return_value = [{"events": []}]

    code = smoke.run_smoke_matrix(
        s3=s3,
        logs=logs,
        timeout=0,
        cleanup=True,
        bucket=BUCKET,
        log_group=LOG_GROUP,
    )

    assert code == 1
    put_keys = [call.kwargs["Key"] for call in s3.put_object.call_args_list]
    assert any(key.endswith("test.txt") for key in put_keys)
    assert all(
        "/incoming/smoke-" in f"/{key}" or key.startswith("incoming/smoke-")
        for key in put_keys
    )
    for call in s3.delete_object.call_args_list:
        assert "VersionId" in call.kwargs
        assert call.kwargs["VersionId"]
