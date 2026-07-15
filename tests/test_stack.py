import json
from collections.abc import Iterator
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from s3_line_processor.stack import S3LineProcessorStack


@pytest.fixture(scope="module")
def synthesized_template() -> dict[str, Any]:
    app = cdk.App()
    stack = S3LineProcessorStack(app, "TestStack")
    return Template.from_stack(stack).to_json()


def resources_of_type(
    template: dict[str, Any], resource_type: str
) -> dict[str, dict[str, Any]]:
    return {
        logical_id: resource
        for logical_id, resource in template["Resources"].items()
        if resource["Type"] == resource_type
    }


def policy_statements(template: dict[str, Any]) -> Iterator[dict[str, Any]]:
    policy_types = ["AWS::IAM::Policy", "AWS::S3::BucketPolicy"]
    for policy_type in policy_types:
        for resource in resources_of_type(template, policy_type).values():
            yield from resource["Properties"]["PolicyDocument"]["Statement"]


def actions_for(statement: dict[str, Any]) -> set[str]:
    actions = statement["Action"]
    return {actions} if isinstance(actions, str) else set(actions)


def test_creates_exactly_one_bucket_and_lambda(
    synthesized_template: dict[str, Any],
) -> None:
    assert len(resources_of_type(synthesized_template, "AWS::S3::Bucket")) == 1
    assert len(resources_of_type(synthesized_template, "AWS::Lambda::Function")) == 1


def test_bucket_has_private_versioned_encrypted_owner_enforced_configuration(
    synthesized_template: dict[str, Any],
) -> None:
    bucket = next(
        iter(resources_of_type(synthesized_template, "AWS::S3::Bucket").values())
    )
    properties = bucket["Properties"]

    assert properties["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    }
    assert properties["VersioningConfiguration"] == {"Status": "Enabled"}
    assert properties["OwnershipControls"] == {
        "Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]
    }
    assert properties["BucketEncryption"] == {
        "ServerSideEncryptionConfiguration": [
            {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
        ]
    }
    assert bucket["DeletionPolicy"] == "Retain"
    assert bucket["UpdateReplacePolicy"] == "Retain"
    assert properties["LifecycleConfiguration"]["Rules"][0][
        "AbortIncompleteMultipartUpload"
    ] == {"DaysAfterInitiation": 7}


def test_bucket_policy_denies_insecure_transport_for_bucket_and_objects(
    synthesized_template: dict[str, Any],
) -> None:
    policies = resources_of_type(synthesized_template, "AWS::S3::BucketPolicy")
    assert len(policies) == 1
    statements = next(iter(policies.values()))["Properties"]["PolicyDocument"][
        "Statement"
    ]
    deny = next(
        statement
        for statement in statements
        if statement.get("Sid") == "DenyInsecureTransport"
    )

    assert deny["Effect"] == "Deny"
    assert deny["Principal"] == {"AWS": "*"}
    assert deny["Action"] == "s3:*"
    assert deny["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
    assert len(deny["Resource"]) == 2
    serialized_resources = json.dumps(deny["Resource"])
    assert ":s3:::" in serialized_resources
    assert "s3-line-processor-" in serialized_resources
    assert "/*" in serialized_resources


def test_lambda_runtime_architecture_resources_and_logs(
    synthesized_template: dict[str, Any],
) -> None:
    function = next(
        iter(resources_of_type(synthesized_template, "AWS::Lambda::Function").values())
    )
    properties = function["Properties"]

    assert properties["Runtime"] == "python3.14"
    assert properties["Architectures"] == ["arm64"]
    assert properties["MemorySize"] == 256
    assert properties["Timeout"] == 15
    assert properties["Handler"] == "handler.lambda_handler"
    assert properties["Environment"]["Variables"]["MAX_FILE_BYTES"] == "1048576"

    log_groups = resources_of_type(synthesized_template, "AWS::Logs::LogGroup")
    assert len(log_groups) == 1
    assert next(iter(log_groups.values()))["Properties"]["RetentionInDays"] == 14


def test_s3_notification_has_expected_event_prefix_and_suffix(
    synthesized_template: dict[str, Any],
) -> None:
    bucket = next(
        iter(resources_of_type(synthesized_template, "AWS::S3::Bucket").values())
    )
    notification = bucket["Properties"]["NotificationConfiguration"][
        "LambdaConfigurations"
    ][0]
    rules = notification["Filter"]["S3Key"]["Rules"]

    assert notification["Event"] == "s3:ObjectCreated:*"
    assert {"Name": "prefix", "Value": "incoming/"} in rules
    assert {"Name": "suffix", "Value": ".json"} in rules


def test_lambda_s3_permissions_are_read_only_and_prefix_restricted(
    synthesized_template: dict[str, Any],
) -> None:
    allow_statements = [
        statement
        for statement in policy_statements(synthesized_template)
        if statement["Effect"] == "Allow"
    ]
    s3_statements = [
        statement
        for statement in allow_statements
        if any(action.startswith("s3:") for action in actions_for(statement))
    ]

    assert len(s3_statements) == 1
    statement = s3_statements[0]
    assert actions_for(statement) == {"s3:GetObject", "s3:GetObjectVersion"}
    assert "incoming/*" in json.dumps(statement["Resource"])
    assert statement["Resource"] != "*"

    forbidden_actions = {
        "s3:*",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:AbortMultipartUpload",
    }
    assert all(
        actions_for(candidate).isdisjoint(forbidden_actions)
        for candidate in allow_statements
    )


def test_lambda_role_trusts_only_lambda_service(
    synthesized_template: dict[str, Any],
) -> None:
    roles = resources_of_type(synthesized_template, "AWS::IAM::Role")
    assert len(roles) == 1
    trust_statements = next(iter(roles.values()))["Properties"][
        "AssumeRolePolicyDocument"
    ]["Statement"]

    assert trust_statements == [
        {
            "Action": "sts:AssumeRole",
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
        }
    ]


def test_s3_invocation_permission_is_constrained_to_source_bucket(
    synthesized_template: dict[str, Any],
) -> None:
    permissions = resources_of_type(synthesized_template, "AWS::Lambda::Permission")
    assert len(permissions) == 1
    properties = next(iter(permissions.values()))["Properties"]

    assert properties["Action"] == "lambda:InvokeFunction"
    assert properties["Principal"] == "s3.amazonaws.com"
    serialized_source_arn = json.dumps(properties["SourceArn"])
    assert ":s3:::" in serialized_source_arn
    assert "s3-line-processor-" in serialized_source_arn
    assert "*" not in serialized_source_arn
    assert properties["SourceAccount"] == {"Ref": "AWS::AccountId"}


def test_outputs_only_bucket_and_function_names(
    synthesized_template: dict[str, Any],
) -> None:
    assert set(synthesized_template["Outputs"]) == {
        "InputBucketName",
        "ProcessorFunctionName",
    }
