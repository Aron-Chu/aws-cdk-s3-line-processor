from aws_cdk import Aws, CfnOutput, Duration, Names, RemovalPolicy, Stack, Tags
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3_notifications
from constructs import Construct


class S3LineProcessorStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        name_suffix = Names.unique_id(self).lower()[-8:]
        bucket_name = f"s3-line-processor-{Aws.ACCOUNT_ID}-{Aws.REGION}-{name_suffix}"
        bucket_arn = Stack.of(self).format_arn(
            service="s3", region="", account="", resource=bucket_name
        )

        bucket = s3.Bucket(
            self,
            "InputBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            bucket_name=bucket_name,
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[
                s3.LifecycleRule(
                    abort_incomplete_multipart_upload_after=Duration.days(7)
                )
            ],
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
        )

        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="DenyInsecureTransport",
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:*"],
                resources=[bucket_arn, f"{bucket_arn}/*"],
                conditions={"Bool": {"aws:SecureTransport": "false"}},
            )
        )
        if bucket.policy is None:
            raise TypeError("InputBucket policy must be created")
        bucket.policy.apply_removal_policy(RemovalPolicy.RETAIN)

        log_group = logs.LogGroup(
            self,
            "ProcessorLogGroup",
            retention=logs.RetentionDays.TWO_WEEKS,
            removal_policy=RemovalPolicy.DESTROY,
        )

        processor = lambda_.Function(
            self,
            "Processor",
            runtime=lambda_.Runtime.PYTHON_3_14,
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_.Code.from_asset("lambda_src"),
            handler="handler.lambda_handler",
            memory_size=256,
            timeout=Duration.seconds(15),
            environment={"MAX_FILE_BYTES": str(1024 * 1024)},
            log_group=log_group,
        )

        processor.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:GetObjectVersion"],
                resources=[f"{bucket_arn}/incoming/*"],
            )
        )

        cfn_bucket = bucket.node.default_child
        if not isinstance(cfn_bucket, s3.CfnBucket):
            raise TypeError("InputBucket must synthesize to AWS::S3::Bucket")

        destination = s3_notifications.LambdaDestination(processor).bind(self, bucket)
        cfn_bucket.notification_configuration = (
            s3.CfnBucket.NotificationConfigurationProperty(
                lambda_configurations=[
                    s3.CfnBucket.LambdaConfigurationProperty(
                        event="s3:ObjectCreated:*",
                        function=destination.arn,
                        filter=s3.CfnBucket.NotificationFilterProperty(
                            s3_key=s3.CfnBucket.S3KeyFilterProperty(
                                rules=[
                                    s3.CfnBucket.FilterRuleProperty(
                                        name="prefix", value="incoming/"
                                    ),
                                    s3.CfnBucket.FilterRuleProperty(
                                        name="suffix", value=".json"
                                    ),
                                ]
                            )
                        ),
                    )
                ]
            )
        )
        for dependency in destination.dependencies:
            if isinstance(dependency, lambda_.CfnPermission):
                dependency.source_arn = bucket_arn
            cfn_bucket.add_dependency(dependency)

        CfnOutput(self, "InputBucketName", value=bucket.bucket_name)
        CfnOutput(self, "ProcessorFunctionName", value=processor.function_name)

        Tags.of(self).add("Project", "S3LineProcessor")
        Tags.of(self).add("ManagedBy", "CDK")
        Tags.of(self).add("Environment", "Sandbox")
