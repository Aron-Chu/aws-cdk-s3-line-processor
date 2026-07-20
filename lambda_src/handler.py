import hashlib
import json
import logging
import os
from typing import Any
from urllib.parse import unquote_plus

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", 1024 * 1024))
SERVICE_NAME = os.environ.get("SERVICE_NAME", "s3-line-processor")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "sandbox")
LOG_SCHEMA_VERSION = 2
MAX_LOG_METADATA_BYTES = 1024

# Keep S3 attempt budget inside the Lambda's 15-second timeout so the handler
# can still emit a safe failure record before the runtime hard-stops.
S3_CLIENT_CONFIG = Config(
    connect_timeout=2,
    read_timeout=5,
    retries={
        "mode": "standard",
        "total_max_attempts": 2,
    },
)

_ACCESS_DENIED_CODES = frozenset({"AccessDenied", "AccessDeniedException"})
_OBJECT_UNAVAILABLE_CODES = frozenset({"NoSuchKey", "NoSuchVersion", "NotFound"})
_TIMEOUT_CODES = frozenset({"RequestTimeout", "RequestTimeoutException"})
_SERVICE_UNAVAILABLE_CODES = frozenset(
    {
        "SlowDown",
        "Throttling",
        "ThrottlingException",
        "ServiceUnavailable",
        "RequestLimitExceeded",
        "ProvisionedThroughputExceededException",
    }
)
_SERVICE_ERROR_CODES = frozenset({"InternalError", "InternalServerError"})

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
s3_client = boto3.client("s3", config=S3_CLIENT_CONFIG)


class ValidationError(ValueError):
    def __init__(
        self, reason_code: str, object_context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.object_context = object_context or {}


class OperationalError(RuntimeError):
    pass


def parse_single_line_json(
    data: bytes, max_file_bytes: int = MAX_FILE_BYTES
) -> dict[str, Any]:
    if len(data) > max_file_bytes:
        raise ValidationError("object_too_large")

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValidationError("invalid_utf8") from error

    if text.endswith("\r\n"):
        line = text[:-2]
    elif text.endswith("\n"):
        line = text[:-1]
    else:
        line = text

    if not line or not line.strip():
        raise ValidationError("empty_input")
    if "\n" in line or "\r" in line:
        raise ValidationError("multiline_input")

    try:
        parsed = json.loads(line, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError, RecursionError) as error:
        raise ValidationError("invalid_json") from error

    if not isinstance(parsed, dict):
        raise ValidationError("non_object_json")

    return parsed


def _reject_json_constant(value: str) -> None:
    raise ValueError(value)


def process_s3_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValidationError("invalid_s3_record")
    if record.get("eventSource") != "aws:s3":
        raise ValidationError("unexpected_event_source")

    try:
        s3_record = record["s3"]
        bucket_name = s3_record["bucket"]["name"]
        object_record = s3_record["object"]
        encoded_key = object_record["key"]
    except (KeyError, TypeError) as error:
        raise ValidationError("invalid_s3_record") from error

    if not isinstance(bucket_name, str) or not isinstance(encoded_key, str):
        raise ValidationError("invalid_s3_record")
    if not _is_utf8_text(bucket_name) or not _is_utf8_text(encoded_key):
        raise ValidationError("invalid_s3_record")

    object_key = unquote_plus(encoded_key)
    if not _is_utf8_text(object_key):
        raise ValidationError("invalid_s3_record")

    raw_version_id = object_record.get("versionId")
    version_id = _normalized_version_id(raw_version_id)
    if raw_version_id is not None and version_id is None and raw_version_id != "null":
        raise ValidationError("invalid_s3_record")
    raw_sequencer = object_record.get("sequencer")
    sequencer = _bounded_string(raw_sequencer)
    if raw_sequencer is not None and sequencer is None:
        raise ValidationError("invalid_s3_record")
    raw_reported_size = object_record.get("size")
    reported_size = _nonnegative_integer(raw_reported_size)
    if raw_reported_size is not None and reported_size is None:
        raise ValidationError("invalid_s3_record")
    object_context = {
        "object_ref": _object_reference(bucket_name, object_key, version_id),
        "version_id": version_id,
        "sequencer": sequencer,
        "reported_object_size": reported_size,
    }

    if not object_key.startswith("incoming/") or not object_key.endswith(".json"):
        raise ValidationError("unexpected_object_key", object_context)

    if reported_size is not None and reported_size > MAX_FILE_BYTES:
        raise ValidationError("object_too_large", object_context)

    get_object_parameters = {"Bucket": bucket_name, "Key": object_key}
    if version_id:
        get_object_parameters["VersionId"] = version_id

    response = s3_client.get_object(**get_object_parameters)
    body = response["Body"]
    content_length = _nonnegative_integer(response.get("ContentLength"))
    object_context["content_length"] = content_length

    if isinstance(content_length, int) and content_length > MAX_FILE_BYTES:
        body.close()
        raise ValidationError("object_too_large", object_context)

    try:
        data = body.read(MAX_FILE_BYTES + 1)
    finally:
        body.close()

    try:
        parsed = parse_single_line_json(data)
    except ValidationError as error:
        raise ValidationError(error.reason_code, object_context) from error

    return {
        "status": "processed",
        **object_context,
        "parsed_field_count": len(parsed),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", None)
    if isinstance(event, dict) and event.get("Event") == "s3:TestEvent":
        result = {"status": "ignored", "event_type": "s3:TestEvent"}
        if request_id:
            result["request_id"] = request_id
        logger.info(_serialize_log(result))
        return {"results": [result]}

    records = event.get("Records") if isinstance(event, dict) else None
    if not isinstance(records, list) or not records:
        failure = {
            "status": "failed",
            "failure_code": "invalid_event_envelope",
            "error_type": "OperationalError",
        }
        if request_id:
            failure["request_id"] = request_id
        logger.error(_serialize_log(failure))
        raise OperationalError("invalid_invocation_event") from None

    results = []

    for record in records:
        safe_context: dict[str, Any] = {}
        try:
            safe_context = _safe_record_context(record)
            result = process_s3_record(record)
        except ValidationError as error:
            result = {
                "status": "rejected",
                **safe_context,
                **error.object_context,
                "reason_code": error.reason_code,
            }
            if request_id:
                result["request_id"] = request_id
            logger.info(_serialize_log(result))
            results.append(result)
            continue
        except Exception as error:
            failure = {
                "status": "failed",
                "failure_code": _operational_failure_code(error),
                "error_type": type(error).__name__,
                **safe_context,
            }
            if request_id:
                failure["request_id"] = request_id
            logger.error(_serialize_log(failure))
            raise OperationalError("retryable_object_processing_failure") from None

        if request_id:
            result["request_id"] = request_id
        logger.info(_serialize_log(result))
        results.append(result)

    return {"results": results}


def _operational_failure_code(error: BaseException) -> str:
    if isinstance(error, (ConnectTimeoutError, ReadTimeoutError)):
        return "s3_timeout"
    if isinstance(error, EndpointConnectionError):
        return "s3_service_unavailable"
    if not isinstance(error, ClientError):
        return "unexpected_error"

    response = error.response if isinstance(error.response, dict) else {}
    error_block = response.get("Error")
    code = error_block.get("Code") if isinstance(error_block, dict) else None
    metadata = response.get("ResponseMetadata")
    status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None

    if code in _ACCESS_DENIED_CODES:
        return "s3_access_denied"
    if code in _OBJECT_UNAVAILABLE_CODES:
        return "s3_object_unavailable"
    if code in _TIMEOUT_CODES:
        return "s3_timeout"
    if code in _SERVICE_UNAVAILABLE_CODES or status == 503:
        return "s3_service_unavailable"
    if code in _SERVICE_ERROR_CODES or (isinstance(status, int) and status >= 500):
        return "s3_service_error"
    return "unexpected_error"


def _safe_record_context(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}

    try:
        s3_record = record["s3"]
        object_record = s3_record["object"]
        bucket_record = s3_record["bucket"]
        if not isinstance(object_record, dict) or not isinstance(bucket_record, dict):
            return {}
        encoded_key = object_record.get("key")
        object_key = unquote_plus(encoded_key) if isinstance(encoded_key, str) else None
        bucket_name = bucket_record.get("name")
        version_id = _normalized_version_id(object_record.get("versionId"))
        object_ref = None
        if (
            isinstance(bucket_name, str)
            and isinstance(object_key, str)
            and _is_utf8_text(bucket_name)
            and _is_utf8_text(object_key)
            and (version_id is None or isinstance(version_id, str))
        ):
            object_ref = _object_reference(bucket_name, object_key, version_id)
        return {
            "object_ref": object_ref,
            "version_id": version_id,
            "sequencer": _bounded_string(object_record.get("sequencer")),
            "reported_object_size": _nonnegative_integer(object_record.get("size")),
        }
    except (KeyError, TypeError, UnicodeEncodeError):  # fmt: skip
        return {}


def _is_utf8_text(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _bounded_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        encoded_value = value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if len(encoded_value) > MAX_LOG_METADATA_BYTES:
        return None
    return value


def _normalized_version_id(value: Any) -> str | None:
    if value is None or value == "null":
        return None
    return _bounded_string(value)


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _object_reference(bucket: str, key: str, version_id: str | None) -> str:
    digest = hashlib.sha256()
    for value in (bucket, key, version_id or ""):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)
    return digest.hexdigest()


def _serialize_log(message: dict[str, Any]) -> str:
    envelope = {
        **message,
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
        "log_schema_version": LOG_SCHEMA_VERSION,
    }
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True)
