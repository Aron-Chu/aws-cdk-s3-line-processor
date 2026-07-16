import json
from unittest.mock import MagicMock

import pytest

from scripts import live_smoke_test as smoke


def test_parse_log_reads_direct_json_message() -> None:
    record = smoke.parse_log('{"status":"processed","key":"incoming/a.json"}')
    assert record == {"status": "processed", "key": "incoming/a.json"}


def test_parse_log_reads_classic_lambda_line_with_context() -> None:
    line = (
        "[INFO]\t2026-07-16T00:00:00.000Z\tabc\t"
        '{"environment":"sandbox","key":"incoming/a.json",'
        '"log_schema_version":1,"service":"s3-line-processor","status":"processed"}'
    )
    record = smoke.parse_log(line)
    assert record is not None
    assert record["status"] == "processed"
    assert record["service"] == "s3-line-processor"
    assert record["environment"] == "sandbox"
    assert record["log_schema_version"] == 1


def test_parse_log_unwraps_nested_message_envelope() -> None:
    nested = (
        '{"environment":"sandbox","log_schema_version":1,'
        '"reason_code":"invalid_json","service":"s3-line-processor","status":"rejected"}'
    )
    envelope = json.dumps({"level": "ERROR", "message": nested})
    record = smoke.parse_log(envelope)
    assert record == {
        "environment": "sandbox",
        "log_schema_version": 1,
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


def test_collect_run_logs_filters_by_run_id_and_parses() -> None:
    run_id = "smoke-abc"
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {
            "events": [
                {"message": f'other-{run_id} {{"status":"processed","key":"a"}}'},
                {"message": '{"status":"rejected","key":"b"}'},
                {"message": f"{run_id} not-json"},
            ]
        }
    ]

    raw, records = smoke.collect_run_logs(client, "/aws/lambda/fn", 1, run_id)

    assert len(raw) == 2
    assert records == [{"status": "processed", "key": "a"}]
    client.get_paginator.assert_called_once_with("filter_log_events")


def test_validate_profile_rejects_documentation_placeholders(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        smoke.validate_profile("OPERATOR_PROFILE")
    assert raised.value.code == 2
    assert "documentation placeholder" in capsys.readouterr().err


def test_validate_profile_allows_real_names_and_none() -> None:
    smoke.validate_profile(None)
    smoke.validate_profile("s3-line-processor-operator")


def test_build_parser_accepts_cleanup_flag() -> None:
    args = smoke.build_parser().parse_args(
        ["--profile", "s3-line-processor-operator", "--cleanup"]
    )
    assert args.profile == "s3-line-processor-operator"
    assert args.cleanup is True
    assert args.stack == "S3LineProcessorStack"
