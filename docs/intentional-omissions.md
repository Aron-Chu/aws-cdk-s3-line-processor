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
