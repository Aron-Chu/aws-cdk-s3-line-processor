#!/usr/bin/env bash
# Mask CloudFormation stack OutputValue entries in GitHub Actions logs.
# Missing stacks are a no-op. Other describe-stacks failures abort.
set -euo pipefail

STACK_NAME="${1:-S3LineProcessorStack}"
STACK_JSON="$(mktemp)"
STACK_ERR="$(mktemp)"
trap 'rm -f "$STACK_JSON" "$STACK_ERR"' EXIT

set +e
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --output json >"$STACK_JSON" 2>"$STACK_ERR"
status=$?
set -e

if [ "$status" -ne 0 ]; then
  if grep -Eqi '\(ValidationError\).*DescribeStacks.*Stack with id .* does not exist' \
    "$STACK_ERR"; then
    exit 0
  fi
  cat "$STACK_ERR" >&2
  exit "$status"
fi

# Percent-encode workflow command metacharacters so OutputValue cannot inject
# additional Actions commands or break ::add-mask::.
jq -r '
  .Stacks[0].Outputs[]?
  | .OutputValue?
  | strings
  | select(length > 0)
  | gsub("%"; "%25")
  | gsub("\r"; "%0D")
  | gsub("\n"; "%0A")
  | "::add-mask::" + .
' "$STACK_JSON"
