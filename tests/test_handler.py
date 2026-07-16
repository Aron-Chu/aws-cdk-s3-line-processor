import json
from types import SimpleNamespace

import pytest

from lambda_src import handler


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.read_sizes = []
        self.closed = False

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return self.data[:size]

    def close(self) -> None:
        self.closed = True


class FakeS3Client:
    def __init__(self, responses: list[bytes | Exception | dict]) -> None:
        self.responses = iter(responses)
        self.calls = []
        self.bodies = []

    def get_object(self, **kwargs: str) -> dict:
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, dict):
            return response
        body = FakeBody(response)
        self.bodies.append(body)
        return {"Body": body, "ContentLength": len(response)}


def make_record(
    key: str = "incoming/valid.json",
    version_id: str | None = "version-1",
    size: int = 42,
) -> dict:
    object_record = {
        "key": key,
        "size": size,
        "eTag": "etag-1",
        "sequencer": "sequencer-1",
    }
    if version_id is not None:
        object_record["versionId"] = version_id
    return {
        "eventSource": "aws:s3",
        "s3": {
            "bucket": {"name": "input-bucket"},
            "object": object_record,
        },
    }


@pytest.mark.parametrize(
    "data",
    [
        b'{"event_id":"one"}',
        b'{"event_id":"one"}\n',
        b'{"event_id":"one"}\r\n',
        b'\xef\xbb\xbf{"event_id":"one"}',
    ],
)
def test_parse_valid_single_line_object(data: bytes) -> None:
    assert handler.parse_single_line_json(data) == {"event_id": "one"}


@pytest.mark.parametrize(
    ("data", "reason_code"),
    [
        (b"", "empty_input"),
        (b" \t ", "empty_input"),
        (b"\xff", "invalid_utf8"),
        (b'{"event_id":}', "invalid_json"),
        (b'{"value":NaN}', "invalid_json"),
        (b'{"value":Infinity}', "invalid_json"),
        (b'{\n  "event_id": "one"\n}', "multiline_input"),
        (b'{"one":1}\n{"two":2}', "multiline_input"),
        (b"[]", "non_object_json"),
        (b'"text"', "non_object_json"),
        (b"42", "non_object_json"),
        (b"true", "non_object_json"),
        (b"null", "non_object_json"),
    ],
)
def test_parse_rejects_invalid_contract(data: bytes, reason_code: str) -> None:
    with pytest.raises(handler.ValidationError) as error:
        handler.parse_single_line_json(data)

    assert error.value.reason_code == reason_code


def test_parse_maps_recursion_error_to_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_recursion_error(*_args: object, **_kwargs: object) -> object:
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(handler.json, "loads", raise_recursion_error)

    with pytest.raises(handler.ValidationError) as error:
        handler.parse_single_line_json(b'{"event_id":"one"}')

    assert error.value.reason_code == "invalid_json"


def test_parse_accepts_maximum_size_and_rejects_one_byte_over() -> None:
    overhead = len(b'{"value":""}')
    maximum = b'{"value":"' + b"a" * (handler.MAX_FILE_BYTES - overhead) + b'"}'

    assert len(maximum) == handler.MAX_FILE_BYTES
    assert handler.parse_single_line_json(maximum)["value"].startswith("a")

    with pytest.raises(handler.ValidationError) as error:
        handler.parse_single_line_json(maximum + b" ")

    assert error.value.reason_code == "object_too_large"


def test_process_decodes_spaces_and_literal_plus_and_uses_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeS3Client([b'{"message":"ok"}'])
    monkeypatch.setattr(handler, "s3_client", client)

    result = handler.process_s3_record(
        make_record("incoming/my+file%2Bname.json", version_id="version-7")
    )

    assert client.calls == [
        {
            "Bucket": "input-bucket",
            "Key": "incoming/my file+name.json",
            "VersionId": "version-7",
        }
    ]
    assert result["key"] == "incoming/my file+name.json"
    assert result["version_id"] == "version-7"
    assert result["parsed_field_count"] == 1
    assert client.bodies[0].read_sizes == [handler.MAX_FILE_BYTES + 1]
    assert client.bodies[0].closed is True


@pytest.mark.parametrize("version_id", [None, "null"])
def test_process_omits_missing_or_null_version_id(
    version_id: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeS3Client([b'{"message":"ok"}'])
    monkeypatch.setattr(handler, "s3_client", client)

    result = handler.process_s3_record(make_record(version_id=version_id))

    assert client.calls == [{"Bucket": "input-bucket", "Key": "incoming/valid.json"}]
    assert result["version_id"] is None


def test_handler_processes_multiple_records(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeS3Client([b'{"first":1}', b'{"second":2}'])
    monkeypatch.setattr(handler, "s3_client", client)
    event = {
        "Records": [
            make_record("incoming/first.json"),
            make_record("incoming/second.json"),
        ]
    }

    response = handler.lambda_handler(
        event, SimpleNamespace(aws_request_id="request-1")
    )

    assert [result["status"] for result in response["results"]] == [
        "processed",
        "processed",
    ]
    assert [call["Key"] for call in client.calls] == [
        "incoming/first.json",
        "incoming/second.json",
    ]


@pytest.mark.parametrize(
    "key",
    ["outside/valid.json", "incoming/valid.txt"],
)
def test_handler_rejects_unexpected_object_keys_without_s3_read(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeS3Client([])
    monkeypatch.setattr(handler, "s3_client", client)

    response = handler.lambda_handler(
        {"Records": [make_record(key)]},
        SimpleNamespace(aws_request_id="request-1"),
    )

    assert response["results"][0]["status"] == "rejected"
    assert response["results"][0]["reason_code"] == "unexpected_object_key"
    assert client.calls == []


def test_handler_reports_permanent_validation_failure_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeS3Client([b'{"invalid":}', b'{"valid":true}'])
    monkeypatch.setattr(handler, "s3_client", client)
    event = {
        "Records": [
            make_record("incoming/invalid.json"),
            make_record("incoming/valid.json"),
        ]
    }

    response = handler.lambda_handler(
        event, SimpleNamespace(aws_request_id="request-1")
    )

    assert response["results"][0]["status"] == "rejected"
    assert response["results"][0]["reason_code"] == "invalid_json"
    assert response["results"][1]["status"] == "processed"


@pytest.mark.parametrize(
    ("record", "reason_code"),
    [
        ({"eventSource": "aws:sns"}, "unexpected_event_source"),
        ({"eventSource": "aws:s3", "s3": {}}, "invalid_s3_record"),
        (
            {
                "eventSource": "aws:s3",
                "s3": {"bucket": {"name": 7}, "object": {"key": "incoming/a.json"}},
            },
            "invalid_s3_record",
        ),
        (
            {
                "eventSource": "aws:s3",
                "s3": {
                    "bucket": {"name": "input-bucket"},
                    "object": {"key": "incoming/a.json", "versionId": 7},
                },
            },
            "invalid_s3_record",
        ),
        (
            {
                "eventSource": "aws:s3",
                "s3": {"bucket": {"name": "input-bucket"}, "object": []},
            },
            "invalid_s3_record",
        ),
        (
            {
                "eventSource": "aws:s3",
                "s3": {
                    "bucket": [],
                    "object": {"key": "incoming/a.json"},
                },
            },
            "invalid_s3_record",
        ),
        ("not-a-record", "invalid_s3_record"),
    ],
)
def test_handler_rejects_malformed_records_without_s3_read(
    record: object, reason_code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeS3Client([])
    monkeypatch.setattr(handler, "s3_client", client)

    response = handler.lambda_handler(
        {"Records": [record]},
        SimpleNamespace(aws_request_id="request-1"),
    )

    assert response["results"][0]["status"] == "rejected"
    assert response["results"][0]["reason_code"] == reason_code
    assert client.calls == []


def test_handler_propagates_s3_operational_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeS3Client([PermissionError("access denied")])
    monkeypatch.setattr(handler, "s3_client", client)

    with pytest.raises(PermissionError, match="access denied"):
        handler.lambda_handler(
            {"Records": [make_record()]},
            SimpleNamespace(aws_request_id="request-1"),
        )

    logged = json.loads(caplog.records[-1].message)
    assert logged["status"] == "failed"
    assert logged["error_type"] == "PermissionError"
    assert caplog.records[-1].exc_info is None
    assert "access denied" not in caplog.records[-1].message
    assert logged["service"] == "s3-line-processor"
    assert logged["environment"] == "sandbox"
    assert logged["log_schema_version"] == 1


def test_handler_logs_safe_success_metadata_without_uploaded_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    uploaded_field = "private_customer_identifier"
    uploaded_value = "TOP-SECRET-UPLOADED-VALUE"
    client = FakeS3Client([json.dumps({uploaded_field: uploaded_value}).encode()])
    monkeypatch.setattr(handler, "s3_client", client)

    handler.lambda_handler(
        {"Records": [make_record()]},
        SimpleNamespace(aws_request_id="request-9"),
    )

    log_message = caplog.records[-1].message
    logged = json.loads(log_message)
    assert uploaded_field not in log_message
    assert uploaded_value not in log_message
    assert logged["status"] == "processed"
    assert "top_level_fields" not in logged
    assert logged["parsed_field_count"] == 1
    assert logged["request_id"] == "request-9"
    assert logged["service"] == "s3-line-processor"
    assert logged["environment"] == "sandbox"
    assert logged["log_schema_version"] == 1


def test_handler_rejects_reported_or_content_length_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeS3Client([])
    monkeypatch.setattr(handler, "s3_client", client)

    reported = handler.lambda_handler(
        {"Records": [make_record(size=handler.MAX_FILE_BYTES + 1)]},
        SimpleNamespace(aws_request_id="request-1"),
    )

    assert reported["results"][0]["reason_code"] == "object_too_large"
    assert client.calls == []

    body = FakeBody(b"")
    client = FakeS3Client([{"Body": body, "ContentLength": handler.MAX_FILE_BYTES + 1}])
    monkeypatch.setattr(handler, "s3_client", client)

    content_length = handler.lambda_handler(
        {"Records": [make_record()]},
        SimpleNamespace(aws_request_id="request-1"),
    )

    assert content_length["results"][0]["reason_code"] == "object_too_large"
    assert body.closed is True


@pytest.mark.parametrize("event", [{}, {"Records": []}, {"Records": {}}])
def test_handler_requires_non_empty_records(event: dict) -> None:
    with pytest.raises(ValueError, match="Records must be a non-empty list"):
        handler.lambda_handler(event, SimpleNamespace(aws_request_id="request-1"))


def test_handler_ignores_s3_test_event(caplog: pytest.LogCaptureFixture) -> None:
    response = handler.lambda_handler(
        {"Service": "Amazon S3", "Event": "s3:TestEvent"},
        SimpleNamespace(aws_request_id="request-1"),
    )

    assert response == {
        "results": [
            {
                "status": "ignored",
                "event_type": "s3:TestEvent",
                "request_id": "request-1",
            }
        ]
    }
    assert json.loads(caplog.records[-1].message)["status"] == "ignored"
