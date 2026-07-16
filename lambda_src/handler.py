import json
import logging
import os
from typing import Any
from urllib.parse import unquote_plus

import boto3

MAX_FILE_BYTES = int(os.environ.get("MAX_FILE_BYTES", 1024 * 1024))
SERVICE_NAME = os.environ.get("SERVICE_NAME", "s3-line-processor")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "sandbox")
LOG_SCHEMA_VERSION = 1

logger = logging.getLogger()
logger.setLevel(logging.INFO)
s3_client = boto3.client("s3")


class ValidationError(ValueError):
    def __init__(
        self, reason_code: str, object_context: dict[str, Any] | None = None
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.object_context = object_context or {}


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

    object_key = unquote_plus(encoded_key)
    version_id = object_record.get("versionId")
    if version_id == "null":
        version_id = None
    elif version_id is not None and not isinstance(version_id, str):
        raise ValidationError("invalid_s3_record")
    object_context = {
        "bucket": bucket_name,
        "key": object_key,
        "version_id": version_id,
        "etag": object_record.get("eTag"),
        "sequencer": object_record.get("sequencer"),
        "reported_object_size": object_record.get("size"),
    }

    if not object_key.startswith("incoming/") or not object_key.endswith(".json"):
        raise ValidationError("unexpected_object_key", object_context)

    reported_size = object_record.get("size")
    if isinstance(reported_size, int) and reported_size > MAX_FILE_BYTES:
        raise ValidationError("object_too_large", object_context)

    get_object_parameters = {"Bucket": bucket_name, "Key": object_key}
    if version_id:
        get_object_parameters["VersionId"] = version_id

    response = s3_client.get_object(**get_object_parameters)
    body = response["Body"]
    content_length = response.get("ContentLength")
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
        raise ValueError("Records must be a non-empty list")

    results = []

    for record in records:
        safe_context = _safe_record_context(record)
        try:
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
                "error_type": type(error).__name__,
                **safe_context,
            }
            if request_id:
                failure["request_id"] = request_id
            logger.error(_serialize_log(failure))
            raise

        if request_id:
            result["request_id"] = request_id
        logger.info(_serialize_log(result))
        results.append(result)

    return {"results": results}


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
        return {
            "bucket": bucket_record.get("name"),
            "key": object_key,
            "version_id": object_record.get("versionId"),
            "etag": object_record.get("eTag"),
            "sequencer": object_record.get("sequencer"),
            "reported_object_size": object_record.get("size"),
        }
    except (KeyError, TypeError):  # fmt: skip
        return {}


def _serialize_log(message: dict[str, Any]) -> str:
    envelope = {
        **message,
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT,
        "log_schema_version": LOG_SCHEMA_VERSION,
    }
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True)
