# Intentional omissions

| Omitted | Why not now | Add when |
| --- | --- | --- |
| Kinesis (logs or events) | These are operational logs, not a business event stream. CloudWatch Logs + Insights already filter/query structured JSON. | Real-time multi-consumer streaming, or org-mandated stream fan-out |
| Firehose / OpenSearch in this stack | Central log forwarding is a **platform** concern. Log group has `CentralLoggingOptIn` only. | Account logging platform owns subscription filters |
| SQS + DLQ | Assignment is direct S3→Lambda. | Buffering, backpressure, poison isolation, durable replay |
| VPC / NAT / endpoints | No private dependency to reach. “Private bucket” is IAM/policy, not VPC-only. | Private-only upload path or private dependency |
| KMS (SSE-KMS) | SSE-S3 encrypts without key-policy surface. | CMK / compliance requirement |
| CloudWatch alarms | Not required to prove the parser path. | Operator must be paged on errors/throttles |
| Idempotency store | No side effects beyond logs today. | Before DB writes or outbound actions |
| Downstream business sink | The current contract is validate and observe; inventing a database, webhook, or event destination would add unspecified data and retry behavior. | Product requirements define the destination, schema, side effects, and idempotency contract |
| Vendored boto3 | Runtime boto3 keeps the Lambda asset small; current SDK use is narrow and tested. | Exact SDK patch reproducibility or a supply-chain freeze is required |
| Object/noncurrent-version expiration | No approved data-retention period exists, and automatic deletion is destructive. | Legal/operations approve a retention and recovery policy |
| Continuous drift detection | Merge-triggered change sets reconcile declared updates but do not continuously scan for console drift. | Multiple operators or compliance requirements justify scheduled drift reporting |
| CloudFormation termination protection | Retaining the bucket and policy protects data, but it does not prevent deletion of the stack's control-plane resources. | Accidental stack deletion becomes an operational risk and the owner accepts the recovery workflow |
| S3 data-event audit trail | CloudTrail data events are an account/platform monitoring concern and can add per-event cost. The application stack does not create a second logging destination. | Production access investigations or compliance require object-level API history |
